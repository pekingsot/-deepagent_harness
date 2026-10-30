from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_platform.domain.types.common import Principal
from agent_platform.paths import ENV_DIR


class Settings(BaseSettings):
    # Environment strings are parsed here; domain/DTO models use strict validation.
    model_config = SettingsConfigDict(
        env_prefix="HARNESS_",
        env_file=ENV_DIR,
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        frozen=True,
    )

    app_name: str = "DeepAgent Enterprise Harness"
    environment: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    checkpoint_backend: Literal["redis", "postgres"] = "redis"
    database_url: str = (
        "postgresql+psycopg://pekingsot:sunset%40123@192.168.1.250:5434/agent_platform"
    )
    redis_url: str = "redis://192.168.1.250:6379/0"
    langfuse_enabled: bool = False
    worker_enabled: bool = False  # 是否随 API 启动任务消费者
    worker_concurrency: int = Field(default=1, ge=1, le=32)  # 当前进程的消费者数量
    task_queue_stream: str = Field(
        default="agent_platform:tasks",
        min_length=1,
    )  # 任务队列名称

    task_queue_group: str = Field(
        default="agent_platform:task_workers",
        min_length=1,
    )  # 任务消费组

    development_token: SecretStr | None = None  # 显式配置的本地联调令牌
    development_principal: Principal | None = None  # 由服务端配置的本地联调身份


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取当前manux项目的配置信息，并对内容进行缓存，避免重复读取"""
    load_dotenv(ENV_DIR, override=False)

    settings = Settings()
    return settings
