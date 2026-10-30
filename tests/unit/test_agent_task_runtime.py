"""通过离线模型验证重构后的执行和人工恢复链路。"""

import unittest
from typing import Any
from unittest.mock import Mock

from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent_platform.application.dto.agent_task_dto import ResumeAgentTask, TextReply
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.domain.types.common import ConflictError, TaskContext
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

        waiting = await runtime.execute(task)
        self.assertEqual(waiting.status, "waiting")
        self.assertEqual(waiting.interrupts[0].payload.question, "本次版本的目标日期？")
        with self.assertRaises(ConflictError):
            await runtime.execute(task)

        completed = await runtime.resume(
            task,
            ResumeAgentTask(answers={waiting.interrupts[0].id: TextReply(answer="下周五")}),
        )
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.output, "已根据目标日期完成任务计划。")
        self.assertEqual(await runtime.get_state(task), completed)
