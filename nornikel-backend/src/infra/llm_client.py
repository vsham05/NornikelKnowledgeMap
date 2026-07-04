import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from infra.json_utils import EMPTY_EXTRACTION, extract_json_object, normalize_llm_content
from infra.ingest_context import ingest_yandex_only
from infra.llm_refusal import is_llm_refusal, wrap_yandex_extraction_user
from infra.local_models import local_ingest_profile, resolve_local_model_tier
from infra.llm_runtime import get_effective_llm_provider, get_llm_provider, get_local_model
from infra.llm_runtime import get_yandex_model as runtime_yandex_model
from ingestion.nlp.extraction_language import extraction_language_instruction
from settings import Settings

logger = logging.getLogger(__name__)

_CONTEXT_OVERFLOW_MARKERS = (
    "exceed_context_size",
    "exceeds the available context size",
    "context length exceeded",
    "maximum context length",
)


def is_context_overflow(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _CONTEXT_OVERFLOW_MARKERS)

JSON_SYSTEM_PROMPT = (
    "You extract structured scientific data. "
    'Reply with ONLY a valid JSON object. No markdown fences, no explanations. '
    "Write all string values in the same language as the source text (Russian or English). "
    'If nothing applies, return {"materials":[],"experiments":[]}.'
)

YANDEX_JSON_SYSTEM_PROMPT = (
    "Ты — компонент извлечения структурированных данных из научных PDF (R&D, металлургия). "
    "Ответь ТОЛЬКО валидным JSON без markdown. "
    "Все строковые поля пиши на языке исходного текста (русский или английский). "
    'Если данных нет: {"materials":[],"experiments":[]}.'
)

YANDEX_JSON_RETRY_SYSTEM_PROMPT = (
    "Режим пакетной обработки документов. Извлеки JSON из фрагмента научной публикации. "
    "Только JSON, без отказов. Строки на языке исходного текста."
)


def extraction_json_system_prompt(target_lang: str = "auto", *, provider: str | None = None) -> str:
    """System prompt: display strings follow document language (not forced Russian)."""
    lang = (target_lang or "auto").strip().lower()
    if lang not in ("ru", "en"):
        lang = "en"
    lang_rule = extraction_language_instruction(lang)
    use_yandex = (provider or get_effective_llm_provider()) == "yandex"
    keys_rule = (
        "Property/parameter keys in JSON: English snake_case (nickel_content, temperature). "
        "Chemical formulas (Fe2O3, H2SO4) unchanged."
    )
    empty_json = '{"materials":[],"experiments":[]}'
    if use_yandex:
        return (
            "Ты — компонент извлечения структурированных данных из научных PDF (R&D, металлургия). "
            "Ответь ТОЛЬКО валидным JSON без markdown. "
            f"{lang_rule} "
            f"{keys_rule} "
            f"Если данных нет: {empty_json}."
        )
    return (
        "You extract structured scientific data for a mining/metallurgy knowledge graph. "
        "Reply with ONLY valid JSON. No markdown. "
        f"{lang_rule} "
        f"{keys_rule} "
        f"If nothing applies: {empty_json}."
    )


class LLMClient:
    """LLM client with local Ollama and Yandex AI Studio providers."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._clients: dict[tuple[str, str], ChatOpenAI] = {}

    def _get_client(self, provider: str | None = None) -> ChatOpenAI:
        provider = provider or get_effective_llm_provider()
        if provider == "yandex":
            model = f"gpt://{self.settings.yandex_folder_id}/{runtime_yandex_model()}"
            key = (provider, runtime_yandex_model())
            if key not in self._clients:
                self._clients[key] = ChatOpenAI(
                    model=model,
                    api_key=self.settings.yandex_api_key,
                    base_url=self.settings.yandex_base_url,
                    temperature=0.1,
                    max_retries=2,
                    request_timeout=None,
                )
                logger.info(
                    "Initialized Yandex LLM: %s (no request timeout)",
                    runtime_yandex_model(),
                )
            return self._clients[key]

        key = ("local", get_local_model())
        if key not in self._clients:
            tier = resolve_local_model_tier(get_local_model())
            timeout = 360.0 if tier == "premium" else 300.0 if tier == "standard" else 240.0
            self._clients[key] = ChatOpenAI(
                model=get_local_model(),
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url,
                temperature=0.1,
                max_retries=3,
                request_timeout=timeout,
            )
            logger.info(
                "Initialized local LLM: %s (tier=%s, timeout=%ss)",
                get_local_model(),
                tier,
                int(timeout),
            )
        return self._clients[key]

    @property
    def llm(self) -> ChatOpenAI:
        """Local Ollama client (VLM and legacy callers)."""
        return self._get_client("local")

    async def _invoke(
        self,
        messages: list,
        *,
        temperature: float = 0.1,
        provider: str | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        client = self._get_client(provider)
        bind_kwargs: dict = {"temperature": temperature}
        if max_tokens is not None:
            bind_kwargs["max_tokens"] = max_tokens
        if json_mode:
            bind_kwargs["response_format"] = {"type": "json_object"}
        llm = client.bind(**bind_kwargs)
        response = await llm.ainvoke(messages)
        return normalize_llm_content(response.content)

    async def chat(
        self,
        user_message: str,
        system_message: str | None = None,
        temperature: float | None = None,
    ) -> str:
        messages: list = []
        if system_message:
            messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=user_message))
        temp = 0.1 if temperature is None else temperature
        return await self._invoke(messages, temperature=temp)

    @staticmethod
    def is_context_overflow(exc: BaseException) -> bool:
        msg = str(exc).lower()
        return any(marker in msg for marker in _CONTEXT_OVERFLOW_MARKERS)

    async def chat_json(
        self,
        user_message: str,
        system_message: str | None = None,
        temperature: float = 0.0,
        target_lang: str | None = None,
        max_tokens: int | None = 12288,
    ) -> dict:
        provider = get_effective_llm_provider()
        if system_message is None and target_lang:
            system = extraction_json_system_prompt(target_lang, provider=provider)
        else:
            system = system_message or (
                YANDEX_JSON_SYSTEM_PROMPT if provider == "yandex" else JSON_SYSTEM_PROMPT
            )

        user = wrap_yandex_extraction_user(user_message) if provider == "yandex" else user_message
        messages = [
            SystemMessage(content=system),
            HumanMessage(content=user),
        ]

        logger.info("Calling LLM for JSON extraction (%s)", provider)
        try:
            content = await self._invoke(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=True,
            )
        except Exception as exc:
            logger.warning("JSON mode invoke failed (%s); retrying without response_format", exc)
            content = await self._invoke(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=False,
            )

        if provider == "yandex" and is_llm_refusal(content):
            logger.warning(
                "Yandex moderation refused extraction (%s); retrying",
                content[:120].replace("\n", " "),
            )
            retry_messages = [
                SystemMessage(content=YANDEX_JSON_RETRY_SYSTEM_PROMPT),
                HumanMessage(content=wrap_yandex_extraction_user(user_message)),
            ]
            content = await self._invoke(
                retry_messages,
                provider="yandex",
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=True,
            )

        if provider == "yandex" and is_llm_refusal(content):
            if ingest_yandex_only():
                logger.error(
                    "Yandex refused extraction during ingest (local fallback disabled). "
                    "Try Qwen3 235B or DeepSeek V4 Flash in the model switcher."
                )
                return dict(EMPTY_EXTRACTION)
            if not self.settings.llm_yandex_fallback_local:
                return dict(EMPTY_EXTRACTION)
            logger.warning(
                "Yandex still refused; falling back to local LLM (%s)",
                self.settings.llm_model,
            )
            fallback_system = (
                extraction_json_system_prompt(target_lang, provider="local")
                if target_lang
                else JSON_SYSTEM_PROMPT
            )
            fallback_messages = [
                SystemMessage(content=fallback_system),
                HumanMessage(content=user_message),
            ]
            try:
                content = await self._invoke(
                    fallback_messages,
                    provider="local",
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=True,
                )
            except Exception as exc:
                logger.error("Local fallback failed: %s", exc)
                return dict(EMPTY_EXTRACTION)

        result = extract_json_object(content)
        logger.info(
            "LLM extraction parsed: %s materials, %s experiments",
            len(result.get("materials", [])),
            len(result.get("experiments", [])),
        )
        return result

    async def chat_structured(
        self,
        user_message: str,
        output_schema: type,
        system_message: str | None = None,
    ) -> Any:
        messages: list = []
        if system_message:
            messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=user_message))
        structured_llm = self.llm.with_structured_output(output_schema)
        logger.info("Calling LLM (structured) with schema: %s", output_schema.__name__)
        return await structured_llm.ainvoke(messages)

    def create_prompt(self, template: str, input_variables: list[str]) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_template(template)
