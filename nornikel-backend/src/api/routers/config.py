"""Runtime configuration (LLM provider, etc.)."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import clear_service_caches
from infra.llm_runtime import (
    get_llm_provider,
    get_local_model,
    get_yandex_model,
    set_llm_provider,
    set_local_model,
    set_yandex_model,
)
from infra.local_models import (
    default_local_extraction_model,
    get_local_model_info,
    list_local_models,
    local_ingest_profile,
    resolve_local_model_tier,
)
from infra.yandex_models import default_yandex_extraction_model, get_yandex_model_info, list_yandex_models
from settings import get_settings

router = APIRouter(prefix="/config", tags=["config"])


class LLMProviderRequest(BaseModel):
    provider: str = Field(..., description="local | yandex")


class YandexModelRequest(BaseModel):
    model: str = Field(..., description="Yandex AI Studio model id, e.g. qwen3-235b-a22b-fp8/latest")


class LocalModelRequest(BaseModel):
    model: str = Field(..., description="Ollama model id, e.g. qwen2.5:32b-instruct")


@router.get("/llm")
async def get_llm_config():
    settings = get_settings()
    provider = get_llm_provider()
    yandex_ready = bool(settings.yandex_api_key and settings.yandex_folder_id)
    yandex_model = get_yandex_model()
    model_info = get_yandex_model_info(yandex_model)
    local_profile = local_ingest_profile(get_local_model())
    extraction_chars = (
        model_info.extraction_chars
        if model_info and provider == "yandex"
        else local_profile["extraction_chars"]
    )
    return {
        "provider": provider,
        "local_model": get_local_model(),
        "local_tier": local_profile["tier"],
        "local_models": list_local_models(),
        "local_recommended": default_local_extraction_model(),
        "local_profile": local_profile,
        "yandex_model": yandex_model,
        "yandex_models": list_yandex_models(),
        "yandex_recommended": default_yandex_extraction_model(),
        "yandex_ready": yandex_ready,
        "hybrid_routing": settings.ingest_hybrid_routing,
        "local_max_pages": settings.ingest_local_max_pages,
        "local_full_coverage": settings.ingest_local_full_coverage,
        "embed_max_chunks": settings.ingest_embed_max_chunks,
        "table_vlm_enabled": settings.ingest_table_vlm,
        "vlm_model": settings.vlm_model,
        "yandex_moderation_risk": bool(model_info and model_info.moderation_risk),
        "extraction_max_chars": extraction_chars,
        "effective_model": (
            f"gpt://{settings.yandex_folder_id}/{yandex_model}"
            if provider == "yandex" and yandex_ready
            else get_local_model()
        ),
    }


@router.post("/llm")
async def update_llm_provider(body: LLMProviderRequest):
    settings = get_settings()
    try:
        provider = set_llm_provider(body.provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if provider == "yandex" and not (settings.yandex_api_key and settings.yandex_folder_id):
        set_llm_provider("local")
        raise HTTPException(
            status_code=400,
            detail="Yandex API is not configured. Set YANDEX_API_KEY and YANDEX_FOLDER_ID in backend .env.",
        )

    clear_service_caches()
    return await get_llm_config()


@router.post("/llm/yandex-model")
async def update_yandex_model(body: YandexModelRequest):
    settings = get_settings()
    if not (settings.yandex_api_key and settings.yandex_folder_id):
        raise HTTPException(
            status_code=400,
            detail="Yandex API is not configured.",
        )
    info = get_yandex_model_info(body.model)
    if info is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown Yandex model: {body.model}",
        )
    set_yandex_model(body.model)
    clear_service_caches()
    return await get_llm_config()


logger = logging.getLogger(__name__)


@router.post("/llm/local-model")
async def update_local_model(body: LocalModelRequest):
    """Switch Ollama extraction model (must be pulled in Ollama first)."""
    info = get_local_model_info(body.model)
    tier = info.tier if info else resolve_local_model_tier(body.model)
    if tier == "light":
        logger.warning(
            "Local model %s is light tier (~50-60%% Yandex quality). "
            "Use qwen2.5:32b-instruct for ~90%% parity.",
            body.model,
        )
    set_local_model(body.model)
    clear_service_caches()
    return await get_llm_config()
