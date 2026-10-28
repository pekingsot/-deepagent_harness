from typing import Callable, Any, Awaitable

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware,ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agent_platform.domain.common.models import RunContext


class ToolPermissionError(RuntimeError):
    pass


class CustomToolPermissionMiddleware(AgentMiddleware[AgentState, RunContext]):
    def __init__(self, *, deny_tools: set[str]) -> None:
        if not isinstance(deny_tools, set):
            raise TypeError("'deny_tools' must be a set.")

        for name in deny_tools:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("'工具名必须是非空字符串")

        self.deny_tools = frozenset(deny_tools)

    def _check_permission(self,request:ToolCallRequest)->None:
        name=request.tool_call["name"]
        if name in self.deny_tools:
            raise ToolPermissionError(f"没有权限调用工具：{name}")

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        self._check_permission(request)
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        self._check_permission(request)
        return await handler(request)
