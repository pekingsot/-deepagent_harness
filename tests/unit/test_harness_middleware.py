"""替代人工演示，确定地验证模型预算和工具审批约束。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from test_agents import ToolChatModel

from agent_platform.domain.types.common import TaskContext
from agent_platform.infrastructure.harness.middleware.custom_model_call_limit import (
    CustomModelCallLimitMiddleware,
    ModelCallLimitExceededError,
)
from agent_platform.infrastructure.harness.middleware.human_approval import (
    HumanApprovalMiddleware,
    ToolApprovalRejectedError,
)


class ModelBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_loop_stops_before_exceeding_budget(self):
        calls = []

        @tool
        def record_value(value: int) -> str:
            """Record a value in the offline test."""
            calls.append(value)
            return "recorded"

        model = ToolChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "record_value",
                            "args": {"value": value},
                            "id": f"call-{value}",
                        }
                    ],
                )
                for value in (1, 2, 3)
            ]
        )
        graph = create_agent(
            model=model,
            tools=[record_value],
            middleware=[CustomModelCallLimitMiddleware(max_calls=2)],
            checkpointer=InMemorySaver(),
            context_schema=TaskContext,
        )
        with self.assertRaises(ModelCallLimitExceededError):
            await graph.ainvoke(
                {"messages": [("user", "keep recording")]},
                config={"configurable": {"thread_id": "offline-model-budget"}},
                context=TaskContext(tenant_id=1, user_id=2, project_id="test"),
            )
        self.assertEqual(calls, [1, 2])


class HumanApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_explicit_approval_allows_tool_execution(self):
        middleware = HumanApprovalMiddleware(approval_tools={"record_value"})
        request = SimpleNamespace(
            tool_call={
                "name": "record_value",
                "id": "call-1",
                "args": {"value": 1},
            }
        )
        for decision in (True, False, "yes"):
            with self.subTest(decision=decision):
                handler = AsyncMock(return_value=ToolMessage(content="done", tool_call_id="call-1"))
                with patch(
                    "agent_platform.infrastructure.harness.middleware.human_approval.interrupt",
                    return_value=decision,
                ):
                    if decision is True:
                        result = await middleware.awrap_tool_call(request, handler)
                        self.assertEqual(result.content, "done")
                        handler.assert_awaited_once_with(request)
                    else:
                        expected = ToolApprovalRejectedError if decision is False else TypeError
                        with self.assertRaises(expected):
                            await middleware.awrap_tool_call(request, handler)
                        handler.assert_not_awaited()
