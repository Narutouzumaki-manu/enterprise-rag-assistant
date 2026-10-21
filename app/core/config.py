from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Connections
    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    redis_url: str = "redis://localhost:6379/0"

    # Storage
    chroma_path: str = "data/chroma"
    upload_dir: str = "data/uploads"

    # Limits (starting values, tune from real usage)
    max_upload_mb: int = Field(default=25, ge=1)
    max_query_chars: int = Field(default=2000, ge=1)

    # Agent runtime
    agent_max_concurrent: int = Field(default=2, ge=1)
    agent_wait_seconds: float = Field(default=20.0, gt=0)

    # Streaming
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0)

    # Auth (dev-only default secret; must be overridden outside development)
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = Field(default=60, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()