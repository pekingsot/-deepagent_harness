from typing import NotRequired

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from agent_platform.domain.types.common import TaskContext


class ModelCallLimitExceededError(RuntimeError):
    pass


class ModelCallState(AgentState):
    model_call_count: NotRequired[int]


class CustomModelCallLimitMiddleware(AgentMiddleware[ModelCallState, TaskContext]):
    """调用次数上限设置"""

    state_schema = ModelCallState

    def __init__(self, max_calls: int = 10) -> None:
        if type(max_calls) is not int or max_calls <= 0:
            raise ValueError("max_calls 必须是正整数")
        self.max_calls = max_calls

    def before_model(self, state: ModelCallState, runtime: Runtime[TaskContext]) -> dict[str, int]:
        count = state.get("model_call_count", 0)
        if count >= self.max_calls:
            raise ModelCallLimitExceededError(f"模型调用已达到上限：{count}/{self.max_calls}")

        return {"model_call_count": count + 1}

    async def abefore_model(
        self, state: ModelCallState, runtime: Runtime[TaskContext]
    ) -> dict[str, int]:
        return self.before_model(state, runtime)
