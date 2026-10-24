from abc import ABC, abstractmethod

from langchain_core.language_models import BaseChatModel

from agent_platform.domain.common.models import RunContext


class ModelProvider(ABC):
    @abstractmethod
    def resolve(self, profile: str, context: RunContext) -> BaseChatModel:
        """Resolve per-agent models and server-managed tenant credentials."""
        raise NotImplementedError
