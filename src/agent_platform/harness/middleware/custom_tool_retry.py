import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agent_platform.domain.common.models import RunContext


class CustomToolRetryMiddleware(
    AgentMiddleware[AgentState, RunContext]
):
    def __init__(
        self,
        *,
        retry_tools: set[str],
        max_retries: int = 2,
    ) -> None:
        if not isinstance(retry_tools, set):
            raise TypeError("retry_tools 必须是 set")

        for name in retry_tools:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("工具名必须是非空字符串")

        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries 必须是非负整数")

        self.retry_tools = frozenset(retry_tools)
        self.max_retries = max_retries

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[
            [ToolCallRequest],
            ToolMessage | Command[Any],
        ],
    ) -> ToolMessage | Command[Any]:
        if request.tool_call["name"] not in self.retry_tools:
            return handler(request)

        for attempt in range(self.max_retries):
            try:
                return handler(request)
            except (TimeoutError, ConnectionError):
                time.sleep(2 ** attempt)

        # 最后一次尝试：仍然失败，就向外抛出异常。
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[
            [ToolCallRequest],
            Awaitable[ToolMessage | Command[Any]],
        ],
    ) -> ToolMessage | Command[Any]:
        if request.tool_call["name"] not in self.retry_tools:
            return await handler(request)

        for attempt in range(self.max_retries):
            try:
                return await handler(request)
            except (TimeoutError, ConnectionError):
                await asyncio.sleep(2 ** attempt)

        return await handler(request)