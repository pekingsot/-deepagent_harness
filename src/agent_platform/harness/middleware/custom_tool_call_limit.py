from typing import NotRequired, Any

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import StateT
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime
from langgraph.typing import ContextT

from agent_platform.domain.common.models import RunContext


class ToolCallLimitExceededError(RuntimeError):
    pass


class ToolCallState(AgentState):
    tool_call_count:NotRequired[int]
    tool_call_counts:NotRequired[dict[str,int]]


class CustomToolCallLimitExceededMiddleware(AgentMiddleware[ToolCallState,RunContext]):
    state_schema = ToolCallState

    def __init__(self,*,max_calls:int,tool_limits:dict[str,int]) -> None:
        if type(max_calls) is not int or max_calls <= 0:
            raise ValueError("max_calls 必须是正整数")

        for name,limit in tool_limits.items():
            if not isinstance(name,str) or not name.strip():
                raise ValueError("工具名称必须是非空字符串")
            if type(limit) is not int or limit <= 0:
                raise ValueError(f"{name}的调用上限必须正整数")

        self.max_calls = max_calls
        self.tool_limits = dict(tool_limits)
    def after_model(self, state: ToolCallState, runtime: Runtime[RunContext]) -> dict[str, int|dict[str,int]] | None:
        message=state["messages"][-1]
        if not isinstance(message,AIMessage) or not message.tool_calls:
            return None

        total =state.get("tool_call_count",0)
        next_total=total+len(message.tool_calls)
        if next_total>self.max_calls:
            raise ToolCallLimitExceededError(
                f"工具总次数超限："
                f"已使用 {total} 次，本批请求 {len(message.tool_calls)} 次，"
                f"上限 {self.max_calls} 次"
            )

        #把内容复制出来，避免直接修改原始state
        counts = dict(state.get("tool_call_counts",{}))
        for tool_call in message.tool_calls:
            name = tool_call["name"]
            counts[name]=counts.get(name,0)+1
            limit=self.tool_limits.get(name)
            if limit is not None and counts[name]>limit:
                raise ToolCallLimitExceededError(
                    f"工具 {name} 超限："
                    f"本批执行后将达到 {counts[name]} 次，"
                    f"上限 {limit} 次"
                )

        return {
            "tool_call_count":next_total,
            "tool_call_counts":counts
        }

    async def aafter_model(self, state: ToolCallState, runtime: Runtime[RunContext]) -> dict[str, int|dict[str,int]] | None:
        return self.after_model(state, runtime)








