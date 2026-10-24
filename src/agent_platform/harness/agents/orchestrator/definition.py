from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from agent_platform.domain.common.models import RunContext
from agent_platform.harness.agents.contracts import AgentDefinition, ContextMiddleware
from agent_platform.harness.agents.orchestrator.backend import BACKEND_PROFILE
from agent_platform.harness.agents.orchestrator.middleware import build_middleware
from agent_platform.harness.agents.orchestrator.tools import build_tools
from agent_platform.infrastructure.model_providers.factory import ModelProvider


class OrchestratorDefinition(AgentDefinition):
    def __init__(self, models: ModelProvider, model_name: str) -> None:
        self.models = models
        self.model_name = model_name

    @property
    def name(self) -> str:
        return "orchestrator"

    @property
    def description(self) -> str:
        return "Coordinate specialized agents and synthesize their results."

    @property
    def resource_directory(self) -> Path:
        return Path(__file__).parent

    @property
    def backend_profile(self) -> str:
        return BACKEND_PROFILE

    @property
    def children(self) -> tuple[str, ...]:
        return ("researcher", "coder", "reviewer")

    def model(self, context: RunContext) -> BaseChatModel:
        return self.models.resolve(self.model_name, context)

    def tools(self, context: RunContext) -> list[BaseTool]:
        return build_tools(context)

    def middleware(self, context: RunContext) -> list[ContextMiddleware]:
        return build_middleware(context)
