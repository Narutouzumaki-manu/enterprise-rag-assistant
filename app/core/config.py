from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEV_JWT_SECRET = "dev-only-secret-change-me-before-deploying"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_ignore_empty=True,
    )

    environment: str = "development"  # "development" or "production"

    # Connections
    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    redis_url: str = "redis://localhost:6379/0"

    # Storage
    chroma_path: str = "data/chroma"
    upload_dir: str = "data/uploads"

    # Limits (starting values, tune from real usage)
    max_upload_mb: int = Field(default=25, ge=1)
    max_query_chars: int = Field(default=2000, ge=1)
    ingest_max_concurrent: int = Field(default=1, ge=1)

    # Rate limits (starting values, tune from real usage)
    rate_limit_enabled: bool = True
    login_rate_limit: str = "5/minute"    # per client address
    chat_rate_limit: str = "10/minute"    # per user, /chat and /chat/stream together
    upload_rate_limit: str = "10/hour"    # per user

    # Agent runtime
    agent_max_concurrent: int = Field(default=2, ge=1)
    agent_wait_seconds: float = Field(default=20.0, gt=0)
    retry_after_seconds: int = Field(default=5, ge=1)  # sent with AGENT_BUSY
    agent_enabled: bool = True  # False: start without building the retriever and agent (dev only)

    # Streaming
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0)

    # Shutdown
    shutdown_grace_seconds: float = Field(default=30.0, ge=0)  # starting value, tune from real use

    # Auth
    jwt_secret: str = DEV_JWT_SECRET  # must be overridden in production
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = Field(default=60, ge=1)

    @model_validator(mode="after")
    def _refuse_a_weak_secret_in_production(self) -> "Settings":
        if self.environment == "production" and (
            self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32
        ):
            raise ValueError(
                "JWT_SECRET must be a random value of at least 32 characters in production."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()