from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_platform.paths import PROJECT_ROOT


class OpenSandboxSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPENSANDBOX_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    domain: str = Field(min_length=1)  # 服务地址，不包含 http://
    api_key: SecretStr = Field(min_length=1)  # 服务端配置的 API Key
    protocol: Literal["http", "https"] = "http"
    use_server_proxy: bool = True  # 通过管理服务代理访问沙箱

    image: str = "python:3.12"

    sandbox_timeout_seconds: int = Field(default=600, gt=0)  # 沙箱存活时间
    ready_timeout_seconds: int = Field(default=120, gt=0)  # 等待启动完成
    request_timeout_seconds: int = Field(default=180, gt=0)  # HTTP 请求超时
    command_timeout_seconds: int = Field(default=120, gt=0)  # 单条命令超时


@lru_cache(maxsize=1)
def get_opensandbox_settings() -> OpenSandboxSettings:
    return OpenSandboxSettings()