"""tool call audit extension point.

Scaffold only; business behavior is intentionally left unimplemented.
"""
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Any

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command

from agent_platform.domain.common.models import RunContext


logger = logging.getLogger(__name__)


class ToolCallAuditMiddleware(
    AgentMiddleware[AgentState, RunContext]
):
    @contextmanager
    def _observe(self, request: ToolCallRequest) -> Iterator[None]:
        name = request.tool_call["name"]
        call_id = request.tool_call["id"]
        started = perf_counter()
        outcome = "interrupted"

        logger.info("工具开始 name=%s call_id=%s", name, call_id)

        try:
            yield
        except GraphBubbleUp:
            # 框架暂停等控制信号，不当作工具故障。
            raise
        except Exception as exc:
            outcome = f"exception:{type(exc).__name__}"
            raise
        else:
            outcome = "returned"
        finally:
            logger.info(
                "工具结束 name=%s call_id=%s outcome=%s elapsed=%.3fs",
                name,
                call_id,
                outcome,
                perf_counter() - started,
            )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[
            [ToolCallRequest], ToolMessage | Command[Any]
        ],
    ) -> ToolMessage | Command[Any]:
        with self._observe(request):
            return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[
            [ToolCallRequest],
            Awaitable[ToolMessage | Command[Any]],
        ],
    ) -> ToolMessage | Command[Any]:
        with self._observe(request):
            return await handler(request)