"""Provider contract and module-owned model connection settings."""

from abc import ABC, abstractmethod

from langchain_core.language_models import BaseChatModel
from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_platform.domain.types.common import TaskContext
from agent_platform.paths import PROJECT_ROOT


class ModelProvider(BaseSettings, ABC):
    """Subclasses select an environment prefix and implement model access.

    Credentials here belong to the platform, not an individual tenant.
    Instantiate from the project root when using the default .env path.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    model_name: str = Field(min_length=1)
    base_url: AnyHttpUrl
    api_key: SecretStr = Field(min_length=1)
    # timeout_seconds: float = Field(default=60.0, gt=0)
    # max_retries: int = Field(default=2, ge=0, le=5)

    @abstractmethod
    def get_model(self, context: TaskContext | None = None) -> BaseChatModel:
        """暂时未使用用户的信息来获取大模型配置.目前是写死的配置里"""
        raise NotImplementedError
