"""认证模块独立配置，复用项目统一的 .env 路径。"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_platform.paths import ENV_DIR


class AuthenticationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTH_", env_file=ENV_DIR, env_file_encoding="utf-8", extra="ignore", frozen=True
    )
    session_ttl: int = Field(default=28800, ge=300, le=604800)  # 会话绝对有效期，秒
    login_limit: int = Field(default=10, ge=1, le=100)  # 单账号每个窗口最多尝试次数
    login_window: int = Field(default=300, ge=30, le=3600)  # 登录限制窗口，秒


@lru_cache(maxsize=1)
def get_authentication_settings() -> AuthenticationSettings:
    return AuthenticationSettings()
