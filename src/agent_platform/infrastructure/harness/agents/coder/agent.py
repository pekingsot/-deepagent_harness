from pathlib import Path

from deepagents import create_deep_agent

from agent_platform.domain.types.common import TaskContext
from agent_platform.infrastructure.harness.agents.base import AgentGraph, BaseAgent
from agent_platform.infrastructure.model_providers.providers.deepseek_provider import (
    DeepSeekProvider,
)


class CoderAgent(BaseAgent):
    name = "coder"
    description = "Develop code and tests using authorized tools."
    directory = Path(__file__).resolve().parent
    provider_class = DeepSeekProvider

    def build(self, context: TaskContext) -> AgentGraph:
        return create_deep_agent(
            name=self.name,
            model=self.model(context),
            system_prompt=self.system_prompt(),
            tools=self.tools,
            middleware=self.middleware,
            backend=self.backend(),
            permissions=self.permissions(),
            skills=["/skills/"],
            subagents=[agent.as_subagent(context) for agent in self.subagents],
            context_schema=TaskContext,
            checkpointer=self.checkpointer,
        )
