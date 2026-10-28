"""Qwen uses the shared client and reads QWEN_ settings."""

from pydantic_settings import SettingsConfigDict

from agent_platform.infrastructure.model_providers.providers.opanai_provider import OpenAIProvider


class QwenProvider(OpenAIProvider):
    model_config = SettingsConfigDict(env_prefix="QWEN_")
