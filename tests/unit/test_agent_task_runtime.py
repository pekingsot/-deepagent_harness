"""通过离线模型验证重构后的执行和人工恢复链路。"""

import asyncio
import unittest
from typing import Any
from unittest.mock import Mock

from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agent_platform.application.dto.agent_task_dto import ResumeAgentTask, TextReply
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.domain.types.common import ConflictError, TaskContext
from agent_platform.domain.types.task_message import TaskMessage
from agent_platform.infrastructure.harness.agents.base import BaseAgent
from agent_platform.infrastructure.harness.runtime.deepagents_task_runtime import (
    DeepAgentsTaskRuntime,
)
from agent_platform.infrastructure.harness.tools.builtins.ask_user import ask_user


class OfflineToolModel(FakeMessagesListChatModel):
    def bind_tools(self, *args: Any, **kwargs: Any) -> "OfflineToolModel":
        return self


class AgentTaskRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_interrupt_resume_and_read_state(self) -> None:
        model = OfflineToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ask_user",
                            "args": {"question": "本次版本的目标日期？"},
                            "id": "ask-date",
                        }
                    ],
                ),
                AIMessage(content="已根据目标日期完成任务计划。"),
            ]
        )
        graph = create_deep_agent(
            name="task_planning",
            model=model,
            tools=[ask_user],
            context_schema=TaskContext,
            checkpointer=InMemorySaver(),
        )
        agent = Mock(spec=BaseAgent)  # 只替代 Agent 组装，执行图使用真实框架
        agent.name = "task_planning"
        agent.build.return_value = graph
        runtime = DeepAgentsTaskRuntime({agent.name: agent})
        task = AgentTask(
            context=TaskContext(tenant_id=1, user_id=2, project_id="test"),
            prompt="请制定版本迭代计划，先询问目标日期。",
        )

        waiting = await runtime.execute(
            task, messages=(TaskMessage(role="user", content=task.prompt),)
        )
        self.assertEqual(waiting.status, "waiting")
        self.assertEqual(waiting.interrupts[0].payload.question, "本次版本的目标日期？")
        with self.assertRaises(ConflictError):
            await runtime.execute(task, messages=(TaskMessage(role="user", content=task.prompt),))

        completed = await runtime.resume(
            task,
            ResumeAgentTask(answers={waiting.interrupts[0].id: TextReply(answer="下周五")}),
        )
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.output, "已根据目标日期完成任务计划。")
        self.assertEqual(await runtime.get_state(task), completed)


class StopRestartRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_round_has_own_title_and_plan_without_renaming_session(self):
        from agent_platform.infrastructure.harness.middleware.execution_title import (
            ExecutionTitleMiddleware,
        )

        model = OfflineToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "set_execution_title",
                            "args": {"title": "编写地图策划"},
                            "id": "title-1",
                        },
                        {
                            "name": "write_todos",
                            "args": {"todos": [{"content": "编写地图", "status": "in_progress"}]},
                            "id": "plan-1",
                        },
                    ],
                ),
                AIMessage(content="地图策划完成"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "set_execution_title",
                            "args": {"title": "检查上线风险"},
                            "id": "title-2",
                        },
                    ],
                ),
                AIMessage(content="风险检查完成"),
            ]
        )
        graph = create_deep_agent(
            model=model,
            middleware=[ExecutionTitleMiddleware()],
            context_schema=TaskContext,
            checkpointer=InMemorySaver(),
        )
        agent = Mock(spec=BaseAgent)
        agent.name = "task_planning"
        agent.build.return_value = graph
        runtime = DeepAgentsTaskRuntime({agent.name: agent})
        task = AgentTask(
            context=TaskContext(tenant_id=1, user_id=2, project_id="test"),
            prompt="版本开发",
            title="版本开发总会话",
        ).start()
        from unittest.mock import AsyncMock

        on_title = AsyncMock()
        first = await runtime.execute(
            task, messages=(TaskMessage(role="user", content="编写策划"),), on_title=on_title
        )
        self.assertEqual(first.title, "编写地图策划")
        on_title.assert_awaited_once_with("编写地图策划")
        second = await runtime.execute(
            task.complete("已完成").queue_next().start(),
            messages=(TaskMessage(role="user", content="按刚才的版本检查上线风险"),),
        )
        self.assertEqual(second.title, "检查上线风险")
        self.assertEqual(second.todos, ())
        self.assertEqual(task.title, "版本开发总会话")

    async def test_failed_tool_does_not_resume_when_new_input_arrives(self):
        calls = []  # 旧工具发生故障后，不能在新一轮自动重试

        @tool
        async def failing_work() -> str:
            """模拟已经发生副作用后抛错的外部工具。"""
            calls.append("old")
            raise RuntimeError("旧工具执行失败")

        graph = create_deep_agent(
            model=OfflineToolModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "failing_work",
                                "args": {},
                                "id": "failed-tool",
                            }
                        ],
                    ),
                    AIMessage(content="新要求已完成"),
                ]
            ),
            tools=[failing_work],
            context_schema=TaskContext,
            checkpointer=InMemorySaver(),
        )
        agent = Mock(spec=BaseAgent)
        agent.name = "task_planning"
        agent.build.return_value = graph
        runtime = DeepAgentsTaskRuntime({agent.name: agent})
        task = AgentTask(
            context=TaskContext(tenant_id=1, user_id=2, project_id="test"), prompt="旧输入"
        ).start()
        with self.assertRaises(RuntimeError):
            await runtime.execute(task, messages=(TaskMessage(role="user", content="旧输入"),))
        restarted = task.fail("工具故障").queue_next().start()
        result = await runtime.execute(
            restarted,
            messages=(TaskMessage(role="user", content="新要求"),),
            restart_after_interruption=True,
        )
        self.assertEqual(result.output, "新要求已完成")
        self.assertEqual(calls, ["old"])

    async def test_cancelled_tool_does_not_run_again_on_corrected_input(self):
        entered = asyncio.Event()
        exited = asyncio.Event()
        calls = []  # 记录真实图对旧工具的调用次数

        @tool
        async def blocking_work() -> str:
            """模拟可被取消的旧请求工具。"""
            calls.append("old")
            entered.set()
            try:
                await asyncio.Event().wait()
                return "旧任务完成"
            finally:
                exited.set()

        model = OfflineToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "blocking_work",
                            "args": {},
                            "id": "old-tool",
                        }
                    ],
                ),
                AIMessage(content="新请求完成"),
            ]
        )
        graph = create_deep_agent(
            model=model,
            tools=[blocking_work],
            context_schema=TaskContext,
            checkpointer=InMemorySaver(),
        )
        agent = Mock(spec=BaseAgent)
        agent.name = "task_planning"
        agent.build.return_value = graph
        runtime = DeepAgentsTaskRuntime({agent.name: agent})
        task = AgentTask(
            context=TaskContext(tenant_id=1, user_id=2, project_id="test"), prompt="错误输入"
        ).start()
        execution = asyncio.create_task(
            runtime.execute(
                task,
                messages=(TaskMessage(role="user", content="错误输入"),),
            )
        )
        await asyncio.wait_for(entered.wait(), 2)
        execution.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await execution
        self.assertTrue(exited.is_set())
        restarted = task.cancel().confirm_cancelled().queue_next().start()
        result = await runtime.execute(
            restarted,
            messages=(TaskMessage(role="user", content="正确输入"),),
            restart_after_interruption=True,
        )
        self.assertEqual(result.output, "新请求完成")
        self.assertEqual(calls, ["old"])

    async def test_stopped_interrupt_is_not_resumed_and_keeps_thread_history(self):
        model = OfflineToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ask_user",
                            "args": {"question": "旧请求的问题？"},
                            "id": "old-ask",
                        }
                    ],
                ),
                AIMessage(content="按照新要求执行完成。"),
            ]
        )
        graph = create_deep_agent(
            name="task_planning",
            model=model,
            tools=[ask_user],
            context_schema=TaskContext,
            checkpointer=InMemorySaver(),
        )
        agent = Mock(spec=BaseAgent)
        agent.name = "task_planning"
        agent.build.return_value = graph
        runtime = DeepAgentsTaskRuntime({agent.name: agent})
        task = AgentTask(
            context=TaskContext(tenant_id=1, user_id=2, project_id="test"), prompt="旧要求"
        ).start()
        waiting = await runtime.execute(
            task, messages=(TaskMessage(role="user", content="旧要求"),)
        )
        self.assertEqual(waiting.status, "waiting")
        restarted = task.wait_for_user().cancel().queue_next().start()
        result = await runtime.execute(
            restarted,
            messages=(TaskMessage(role="user", content="正确的新要求"),),
            restart_after_interruption=True,
        )
        self.assertEqual(result.status, "completed")
        snapshot = await graph.aget_state(runtime._config(restarted))
        self.assertFalse(snapshot.next)
        self.assertFalse(snapshot.interrupts)
        history = snapshot.values["messages"]
        self.assertEqual(
            [m.content for m in history if isinstance(m, HumanMessage)], ["旧要求", "正确的新要求"]
        )
        replies = [m for m in history if isinstance(m, ToolMessage) and m.tool_call_id == "old-ask"]
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].status, "error")

    async def test_stopped_round_without_checkpoint_can_start_again(self):
        graph = create_deep_agent(
            model=OfflineToolModel(responses=[AIMessage(content="新输入已完成")]),
            context_schema=TaskContext,
            checkpointer=InMemorySaver(),
        )
        agent = Mock(spec=BaseAgent)
        agent.name = "task_planning"
        agent.build.return_value = graph
        runtime = DeepAgentsTaskRuntime({agent.name: agent})
        task = (
            AgentTask(
                context=TaskContext(tenant_id=1, user_id=2, project_id="test"), prompt="旧输入"
            )
            .start()
            .cancel()
            .confirm_cancelled()
            .queue_next()
            .start()
        )
        with self.assertRaises(ConflictError):
            await runtime.execute(task, messages=(TaskMessage(role="user", content="正确输入"),))
        result = await runtime.execute(
            task,
            messages=(TaskMessage(role="user", content="正确输入"),),
            restart_after_interruption=True,
        )
        self.assertEqual(result.output, "新输入已完成")
