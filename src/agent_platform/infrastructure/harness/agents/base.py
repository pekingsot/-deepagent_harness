"""Small shared contract and resource helpers for concrete agents."""

import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar

from deepagents import CompiledSubAgent, FilesystemPermission
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.backends.protocol import BackendProtocol
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from agent_platform.domain.types.common import TaskContext
from agent_platform.infrastructure.model_providers.base import ModelProvider

type AgentGraph = CompiledStateGraph[Any, Any, Any, Any]
type ContextMiddleware = AgentMiddleware[Any, TaskContext]

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    directory: ClassVar[Path]
    provider_class: ClassVar[type[ModelProvider]]

    def __init__(
        self,
        *,
        tools: Sequence[BaseTool] = (),
        middleware: Sequence[ContextMiddleware] = (),
        backend: BackendProtocol | None = None,
        subagents: Sequence["BaseAgent"] = (),
        checkpointer: BaseCheckpointSaver[Any] | None = None,
    ) -> None:
        cls = getattr(type(self), "provider_class", None)
        if not isinstance(cls, type) or not issubclass(cls, ModelProvider):
            raise TypeError("Agent must declare provider_class inheriting ModelProvider")
        self.tools = list(tools)
        self.middleware = list(middleware)
        self._backend = backend
        self.subagents = tuple(subagents)

        if not isinstance(checkpointer, BaseCheckpointSaver):
            raise TypeError("checkpointer 必须是 BaseCheckpointSaver 实例")

        self.checkpointer = checkpointer

        names = [agent.name for agent in self.subagents]
        if len(names) != len(set(names)) or "general-purpose" in names:
            raise ValueError("Custom subagent names must be unique and not general-purpose")

    @cached_property
    def provider(self) -> ModelProvider:
        return self.provider_class()

    def model(self, context: TaskContext) -> BaseChatModel:
        model = self.provider.get_model(context)
        if not isinstance(model, BaseChatModel):
            raise TypeError("Provider.get_model() must return a BaseChatModel instance")
        return model

    def system_prompt(self) -> str:
        return (self.directory / "system_prompt.md").read_text(encoding="utf-8")

    def backend(self) -> BackendProtocol:
        # Workspace files are graph-state files. Only this agent's skill resources
        # are mounted from disk; create_deep_agent permissions prohibit editing them.
        return CompositeBackend(
            default=self._backend if self._backend is not None else StateBackend(),
            routes={"/skills/": FilesystemBackend(root_dir=self.directory / "skills")},
        )

    def permissions(self) -> list[FilesystemPermission]:
        return [FilesystemPermission(operations=["write"], paths=["/skills/**"], mode="deny")]

    def as_subagent(self, context: TaskContext) -> CompiledSubAgent:
        return {"name": self.name, "description": self.description, "runnable": self.build(context)}

    @abstractmethod
    def build(self, context: TaskContext) -> AgentGraph:
        """Build a graph for this run; do not cache tenant-specific graphs globally."""
        raise NotImplementedError
