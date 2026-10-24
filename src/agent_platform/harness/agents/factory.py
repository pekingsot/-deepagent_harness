from abc import ABC, abstractmethod
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from agent_platform.domain.common.models import RunContext
from agent_platform.harness.agents.contracts import AgentDefinition


class AgentFactory(ABC):
    @abstractmethod
    def build(
        self, definition: AgentDefinition, context: RunContext,
    ) -> CompiledStateGraph[Any, Any, Any, Any]:
        """Adapt definitions to the installed DeepAgents API in this boundary."""
        raise NotImplementedError
