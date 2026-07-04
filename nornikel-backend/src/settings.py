from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    """Настройки приложения из переменных окружения."""
    
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.is_file() else ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password123"
    
    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection_text: str = "scientific_text"
    qdrant_collection_visual: str = "scientific_visual"
    
    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "scientific-docs"
    minio_secure: bool = False
    
    # LLM (Ollama OpenAI-compatible API)
    llm_api_key: str = "ollama"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "qwen2.5:7b-instruct"
    llm_provider: str = "local"  # local | yandex
    llm_context_tokens: int = 32_768
    llm_extraction_max_chars: int = 28_000
    llm_extraction_max_batches: int = 0  # 0 = process every page batch (no thinning)
    llm_yandex_fallback_local: bool = True
    # ru | en | auto — auto matches labels to document language (recommended)
    extraction_language: str = "auto"
    # Hybrid ingest: short PDFs → local 7B, longer → Yandex (when API keys configured)
    ingest_hybrid_routing: bool = True
    ingest_local_max_pages: int = 28
    ingest_local_full_coverage: bool = True  # long local docs: more batches; short docs auto-capped
    ingest_local_max_enricher_passes: int = 2  # cap multipass on Ollama (1 GPU serializes anyway)
    ingest_local_max_extraction_batches: int = 4  # short docs ≤28 pages — backfills cover the rest
    ingest_local_llm_serial: bool = True  # enrich then extract (avoid Ollama GPU queue thrashing)
    ingest_local_enricher_concurrency: int = 0  # 0 = tier default (2 light / 3 standard / 4 premium)
    # Long PDFs (≥ threshold pages): parallel enricher + batched extraction
    ingest_fast_page_threshold: int = 35
    ingest_embed_max_chunks: int = 0  # 0 = embed all merged chunks (no thinning)
    ingest_parallel_extraction_batches: int = 16
    ingest_llm_concurrency: int = 8
    ingest_target_max_minutes: int = 10
    # Legacy aliases (ignored when parallel ingest is active)
    ingest_balanced_extraction_batches: int = 3
    ingest_enricher_multipass: int = 0  # auto: 2 for 7B tier on long PDFs

    # Yandex Cloud Foundation Models (OpenAI-compatible)
    yandex_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_base_url: str = "https://llm.api.cloud.yandex.net/v1"
    yandex_model: str = "qwen3-235b-a22b-fp8/latest"
    
    # VLM (vision model for image-based tables — separate from text LLM)
    vlm_api_key: str = "ollama"
    vlm_base_url: str = "http://localhost:11434/v1"
    vlm_model: str = "minicpm-v"
    ingest_table_vlm: bool = True
    ingest_table_vlm_max: int = 24
    
    # Embedding (Ollama)
    embedding_api_key: str = "ollama"
    embedding_base_url: str = "http://localhost:11434/v1"
    embedding_model: str = "mxbai-embed-large"
    embedding_dimensions: int = 1024

    # Russian RAG: translate question→EN for search, answer in EN, translate answer→RU
    rag_ru_translate_pipeline: bool = True
    
    # Application
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    @property
    def project_root(self) -> Path:
        """
        Корень проекта — ищем по наличию pyproject.toml,
        поднимаясь вверх от текущего файла.
        """
        current = Path(__file__).resolve().parent
        for parent in [current] + list(current.parents):
            if (parent / "pyproject.toml").exists():
                return parent
        # Fallback — текущая рабочая директория
        return Path.cwd()
    
    @property
    def configs_dir(self) -> Path:
        return self.project_root / "configs"
    
    @property
    def prompts_dir(self) -> Path:
        return self.configs_dir / "prompts"
    
    @property
    def ontology_path(self) -> Path:
        return self.configs_dir / "ontology.yaml"


# Singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        from infra.llm_runtime import init_llm_provider_from_settings, init_local_model_from_settings, init_yandex_model_from_settings

        init_llm_provider_from_settings(_settings.llm_provider)
        init_yandex_model_from_settings(_settings.yandex_model)
        init_local_model_from_settings(_settings.llm_model)
    return _settings