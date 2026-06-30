from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения из переменных окружения."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
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
    llm_model: str = "qwen2.5-7b-instruct"
    
    # VLM
    vlm_api_key: str = "ollama"
    vlm_base_url: str = "http://localhost:11434/v1"
    vlm_model: str = "qwen2.5-7b-instruct"
    
    # Embedding (Ollama)
    embedding_api_key: str = "ollama"
    embedding_base_url: str = "http://localhost:11434/v1"
    embedding_model: str = "mxbai-embed-large"
    embedding_dimensions: int = 1024
    
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
    return _settings