from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "EDB Circulars"
    app_env: str = "development"
    jwt_secret: str = "change-me"
    jwt_expire_hours: int = 72
    admin_username: str = "admin"
    admin_password: str = "000000"
    cors_origins: str = "http://localhost:4000"

    database_url: str = "postgresql+asyncpg://edb:edb_secret@db:5432/edb_circulars"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "edb-docs"
    minio_public_url: str = "http://localhost:9000"
    minio_secure: bool = False
    storage_backend: Literal["local", "minio"] = "local"
    local_storage_path: str = "/data/files"

    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-2.5-flash"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    jina_api_key: str = ""
    jina_embedding_model: str = "jina-embeddings-v3"
    jina_embedding_dim: int = 1024

    llm_provider: Literal["openrouter", "ollama"] = "openrouter"
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.2"

    crawl_user_agent: str = "EDBCircularsBot/1.0"
    crawl_rate_limit_seconds: float = 1.5
    crawl_enabled: bool = True
    sources_config_path: str = "/config/sources.yaml"

    dify_enabled: bool = False
    dify_api_url: str = "http://dify-api:5001"
    dify_dataset_api_key: str = ""
    dify_app_api_key: str = ""
    dify_dataset_id: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
