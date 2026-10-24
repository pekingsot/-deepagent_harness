from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from agent_platform.domain.common.models import RunContext

# Any is limited to the external SDK's extensible state schema.
type ContextMiddleware = AgentMiddleware[Any, RunContext]


class AgentDefinition(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def resource_directory(self) -> Path: ...

    @property
    @abstractmethod
    def backend_profile(self) -> str: ...

    @property
    def children(self) -> tuple[str, ...]:
        return ()

    @abstractmethod
    def model(self, context: RunContext) -> BaseChatModel: ...

    @abstractmethod
    def tools(self, context: RunContext) -> list[BaseTool]: ...

    @abstractmethod
    def middleware(self, context: RunContext) -> list[ContextMiddleware]: ...

    def system_prompt(self) -> str:
        return (self.resource_directory / "system_prompt.md").read_text(encoding="utf-8")
