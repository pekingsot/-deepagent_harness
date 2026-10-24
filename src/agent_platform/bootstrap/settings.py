from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Environment strings are parsed here; domain/DTO models use strict validation.
    model_config = SettingsConfigDict(
        env_prefix="HARNESS_", env_file=".env", extra="ignore", frozen=True,
    )

    app_name: str = "DeepAgent Enterprise Harness"
    environment: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "postgresql+psycopg://localhost/agent_platform"
    redis_url: str = "redis://localhost:6379/0"
    langfuse_enabled: bool = False
