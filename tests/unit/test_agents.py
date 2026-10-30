"""Offline checks for direct graph composition and independent skill resources."""

import unittest
from typing import Any, ClassVar, cast
from unittest.mock import patch

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import AnyHttpUrl, SecretStr
from pydantic_settings import SettingsConfigDict

from agent_platform.domain.types.common import TaskContext
from agent_platform.infrastructure.harness.agents import (
    CoderAgent,
    ResearcherAgent,
    ReviewerAgent,
    TaskPlanningAgent,
)
from agent_platform.infrastructure.model_providers.base import ModelProvider


class ToolChatModel(FakeMessagesListChatModel):
    def bind_tools(self, *args: Any, **kwargs: Any) -> "ToolChatModel":
        return self


def agent_classes(
    model: BaseChatModel,
) -> tuple[type[TaskPlanningAgent], type[ResearcherAgent]]:
    # 测试使用离线 Provider，不读取真实模型凭据或调用外部接口
    class TestProvider(ModelProvider):
        model_config = SettingsConfigDict(env_file=None, env_prefix="TEST_AGENT_")
        model_name: str = "offline-test"
        base_url: AnyHttpUrl = AnyHttpUrl("https://example.com")
        api_key: SecretStr = SecretStr("test-only")
        chat: ClassVar[BaseChatModel] = model

        def get_model(self, context: TaskContext | None = None) -> BaseChatModel:
            return self.chat

    class Planner(TaskPlanningAgent):
        provider_class = TestProvider
        fallback_provider_class = TestProvider

    class Researcher(ResearcherAgent):
        provider_class = TestProvider

    return Planner, Researcher


class AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = TaskContext(tenant_id=1, project_id="test", user_id=2)

    def test_planning_tool_updates_state(self) -> None:
        model = ToolChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_todos",
                            "args": {
                                "todos": [{"content": "Compare products", "status": "pending"}]
                            },
                            "id": "plan-1",
                        }
                    ],
                ),
                AIMessage(content="Plan prepared."),
            ]
        )
        Planner, _ = agent_classes(model)
        graph = Planner(checkpointer=InMemorySaver()).build(self.context)
        result = graph.invoke(
            {"messages": [("user", "Plan a comparison")]},
            config={"configurable": {"thread_id": "planning-test"}},
            context=self.context,
        )
        self.assertEqual(result["todos"], [{"content": "Compare products", "status": "pending"}])

    def test_custom_child_is_built_independently(self) -> None:
        model = ToolChatModel(responses=[AIMessage(content="Done.")])
        Planner, Researcher = agent_classes(model)
        child = Researcher(checkpointer=InMemorySaver())
        agent = Planner(checkpointer=InMemorySaver(), subagents=[child])
        graph = agent.build(self.context)
        self.assertEqual(graph.name, "task_planning")
        self.assertEqual(child.as_subagent(self.context)["name"], "researcher")
        self.assertNotEqual(agent.directory, child.directory)

    def test_skill_mounts_are_independent(self) -> None:
        model = ToolChatModel(responses=[AIMessage(content="Done.")])
        Planner, Researcher = agent_classes(model)
        parent = Planner(checkpointer=InMemorySaver())
        Planner, Researcher = agent_classes(model)
        child = Researcher(checkpointer=InMemorySaver())
        self.assertIsNone(parent.backend().read("/skills/task-planning/SKILL.md").error)
        self.assertIsNone(child.backend().read("/skills/web-research/SKILL.md").error)
        self.assertIsNotNone(child.backend().read("/skills/task-planning/SKILL.md").error)

    def test_duplicate_children_rejected(self) -> None:
        model = ToolChatModel(responses=[AIMessage(content="Done.")])
        with self.assertRaises(ValueError):
            Planner, Researcher = agent_classes(model)
            Planner(
                checkpointer=InMemorySaver(),
                subagents=[Researcher(checkpointer=InMemorySaver())] * 2,
            )

    def test_model_argument_is_not_accepted(self) -> None:
        with self.assertRaises(TypeError):
            TaskPlanningAgent(model="invalid")  # type: ignore[call-arg]

    def test_provider_and_client_contract(self) -> None:
        model = ToolChatModel(responses=[AIMessage(content="Done.")])
        Planner, _ = agent_classes(model)
        agent = Planner(checkpointer=InMemorySaver())
        self.assertIs(agent.provider, agent.provider)
        self.assertIs(agent.model(self.context), model)
        with patch.object(type(agent.provider), "get_model", return_value="bad"):
            with self.assertRaises(TypeError):
                agent.model(self.context)

    def test_specialists_keep_injected_checkpointer(self) -> None:
        """独立注册的专用 Agent 必须使用传入的 Checkpoint。"""
        model = ToolChatModel(responses=[AIMessage(content="Done.")])
        Planner, _ = agent_classes(model)
        for agent_type in (ResearcherAgent, CoderAgent, ReviewerAgent):
            with self.subTest(agent=agent_type.name):
                offline_type = type(
                    "OfflineAgent",
                    (agent_type,),
                    {"provider_class": Planner.provider_class},
                )
                saver = InMemorySaver()
                graph = offline_type(checkpointer=saver).build(self.context)
                self.assertIs(graph.checkpointer, saver)

    def test_invalid_provider_class_is_rejected(self) -> None:
        class InvalidAgent(TaskPlanningAgent):
            provider_class = cast(type[ModelProvider], str)

        with self.assertRaises(TypeError):
            InvalidAgent()


if __name__ == "__main__":
    unittest.main()
