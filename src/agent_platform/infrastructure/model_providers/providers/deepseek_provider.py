"""DeepSeek uses the shared client and reads DEEPSEEK_ settings."""

from functools import cached_property

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic_settings import SettingsConfigDict

from agent_platform.domain.common.models import RunContext
from agent_platform.infrastructure.model_providers.factory import ModelProvider


class DeepSeekProvider(ModelProvider):
    model_config = SettingsConfigDict(env_prefix="DEEPSEEK_")

    @cached_property
    def _client(self) -> ChatOpenAI:
        return ChatOpenAI(
            model=self.model_name,
            base_url=str(self.base_url),
            api_key=self.api_key,
            # timeout=self.timeout_seconds,
            # max_retries=self.max_retries,
            use_responses_api=False,
            temperature=0.7,

        )

    def get_model(self, context: RunContext | None = None) -> BaseChatModel:
        # This provider owns a single platform connection; profile/context do not select it.
        return self._client
