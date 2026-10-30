"""human approval extension point.

Scaffold only; business behavior is intentionally left unimplemented.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command, interrupt

from agent_platform.domain.types.common import TaskContext


class ToolApprovalRejectedError(RuntimeError):
    pass


class HumanApprovalMiddleware(AgentMiddleware[AgentState, TaskContext]):
    def __init__(self, *, approval_tools: set[str]) -> None:
        if not isinstance(approval_tools, set):
            raise TypeError("approval_tools must be a set.")
        for name in approval_tools:
            if not isinstance(name, str) or not name.strip():
                raise TypeError("approval_tools must be a string.")

        self.approval_tools = frozenset(approval_tools)

    def _approve(self, request: ToolCallRequest) -> None:
        name = request.tool_call["name"]
        if name not in self.approval_tools:
            return
        decision = interrupt(
            {
                "type": "tool_approval",
                "tool_name": name,
                "tool_call_id": request.tool_call["id"],
                "args": request.tool_call["args"],
            }
        )
        if type(decision) is not bool:
            raise TypeError("approval_tools must return a boolean.")
        if not decision:
            raise ToolApprovalRejectedError(f"用户拒绝执行工具：{name}")

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        self._approve(request)
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        self._approve(request)
        return await handler(request)
