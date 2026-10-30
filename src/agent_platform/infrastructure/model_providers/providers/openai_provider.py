"""Existing import path for OpenAI-compatible model access."""

from functools import cached_property

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic_settings import SettingsConfigDict

from agent_platform.domain.types.common import TaskContext
from agent_platform.infrastructure.model_providers.base import ModelProvider


class OpenAIProvider(ModelProvider):
    """Reads OPENAI_COMPATIBLE_ settings through its parent class."""

    model_config = SettingsConfigDict(env_prefix="OPENAI_")

    @cached_property
    def _client(self) -> ChatOpenAI:
        return ChatOpenAI(
            model=self.model_name,
            base_url=str(self.base_url),
            api_key=self.api_key,
            # timeout=self.timeout_seconds,
            # max_retries=self.max_retries,
            use_responses_api=False,
        )

    def get_model(self, context: TaskContext | None = None) -> BaseChatModel:
        # This provider owns a single platform connection; profile/context do not select it.
        return self._client
