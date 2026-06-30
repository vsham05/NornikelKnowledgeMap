import json
import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from infra.json_utils import extract_json_object
from settings import Settings

logger = logging.getLogger(__name__)

JSON_SYSTEM_PROMPT = (
    "You extract structured scientific data. "
    'Reply with ONLY a valid JSON object. No markdown fences, no explanations. '
    'If nothing applies, return {"materials":[],"experiments":[]}.'
)


class LLMClient:
    """
    Клиент для работы с LLM на базе LangChain.
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.1,
            max_retries=3,
            request_timeout=120.0
        )
        logger.info(f"Initialized LLM client: {settings.llm_model}")
    
    async def chat(
        self,
        user_message: str,
        system_message: str | None = None,
        temperature: float | None = None
    ) -> str:
        """
        Простой chat completion.
        
        Args:
            user_message: Сообщение пользователя
            system_message: Системный промпт (опционально)
            temperature: Температура генерации
        
        Returns:
            Текст ответа
        """
        messages = []
        
        if system_message:
            messages.append(SystemMessage(content=system_message))
        
        messages.append(HumanMessage(content=user_message))
        
        # Override temperature если указан
        llm = self.llm
        if temperature is not None:
            llm = self.llm.bind(temperature=temperature)
        
        logger.info(f"Calling LLM with {len(messages)} messages")
        
        response = await llm.ainvoke(messages)
        content = response.content
        
        logger.info(f"LLM response: {len(content)} chars")
        return content
    
    async def chat_json(
        self,
        user_message: str,
        system_message: str | None = None,
        temperature: float = 0.1
    ) -> dict:
        """
        Chat completion with JSON output.
        Ollama does not reliably support OpenAI json_object mode, so we parse flexibly.
        """
        system = system_message or JSON_SYSTEM_PROMPT
        messages = [
            SystemMessage(content=system),
            HumanMessage(content=user_message),
        ]

        llm = self.llm.bind(temperature=temperature)
        logger.info("Calling LLM for JSON extraction")

        response = await llm.ainvoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)

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
        system_message: str | None = None
    ) -> Any:
        """
        Chat completion со структурированным выводом через Pydantic.
        
        Args:
            user_message: Сообщение пользователя
            output_schema: Pydantic модель для вывода
            system_message: Системный промпт
        
        Returns:
            Экземпляр Pydantic модели
        """
        messages = []
        
        if system_message:
            messages.append(SystemMessage(content=system_message))
        
        messages.append(HumanMessage(content=user_message))
        
        # Используем structured output
        structured_llm = self.llm.with_structured_output(output_schema)
        
        logger.info(f"Calling LLM (structured) with schema: {output_schema.__name__}")
        
        result = await structured_llm.ainvoke(messages)
        
        logger.info(f"LLM structured response: {type(result).__name__}")
        return result
    
    def create_prompt(
        self,
        template: str,
        input_variables: list[str]
    ) -> ChatPromptTemplate:
        """
        Создает промпт из шаблона.
        
        Args:
            template: Шаблон промпта с {переменными}
            input_variables: Список переменных
        
        Returns:
            ChatPromptTemplate
        """
        return ChatPromptTemplate.from_template(template)