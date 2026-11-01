"""Langfuse 模块独立读取配置，不放入全局 Settings。"""

from typing import Self

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_platform.paths import ENV_DIR


class LangfuseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LANGFUSE_",
        env_file=ENV_DIR,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    tracing_enabled: bool = False  # 是否初始化并上报追踪，默认关闭
    base_url: AnyHttpUrl | None = None  # 明确指定自己的 Langfuse 服务地址
    public_key: SecretStr | None = None  # Langfuse 项目的公开访问标识
    secret_key: SecretStr | None = None  # Langfuse 项目密钥，不写日志
    tracing_environment: str = Field(default="development", min_length=1, max_length=64)  # 追踪环境
    timeout: int = Field(default=5, ge=1, le=30)  # SDK 单次 HTTP 请求超时秒数

    @field_validator("base_url", mode="before")
    @classmethod
    def empty_url(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def require_connection(self) -> Self:
        if self.tracing_enabled and (
            self.base_url is None
            or self.public_key is None
            or self.secret_key is None
            or not self.public_key.get_secret_value().strip()
            or not self.secret_key.get_secret_value().strip()
        ):
            raise ValueError("启用 Langfuse 时必须配置 BASE_URL、PUBLIC_KEY 和 SECRET_KEY")
        return self
