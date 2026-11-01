"""只使用替代 SDK 验证追踪装配，不初始化真实客户端或发送网络请求。"""

import sys
import unittest
from contextlib import nullcontext
from types import ModuleType
from unittest.mock import MagicMock, Mock, patch

from pydantic import SecretStr, ValidationError

from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.domain.types.common import TaskContext
from agent_platform.infrastructure.observability.langfuse import LangfuseTracing
from agent_platform.infrastructure.observability.settings import LangfuseSettings


def settings(**changes) -> LangfuseSettings:
    values = {
        "tracing_enabled": True,
        "base_url": "http://127.0.0.1:3001",
        "public_key": SecretStr("pk-offline"),
        "secret_key": SecretStr("sk-offline"),
        "tracing_environment": "test",
        "timeout": 2,
    }
    values.update(changes)
    return LangfuseSettings(_env_file=None, **values)


class LangfuseTracingTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()  # 不包含真实 HTTP 能力的客户端
        self.client_factory = Mock(return_value=self.client)
        self.handler_factory = Mock(side_effect=lambda **kwargs: object())
        sdk = ModuleType("langfuse")
        sdk.Langfuse = self.client_factory
        self.propagation = Mock(side_effect=lambda **kwargs: nullcontext())
        sdk.propagate_attributes = self.propagation
        integration = ModuleType("langfuse.langchain")
        integration.CallbackHandler = self.handler_factory
        modules = patch.dict(sys.modules, {"langfuse": sdk, "langfuse.langchain": integration})
        modules.start()
        self.addCleanup(modules.stop)
        self.task = AgentTask(
            context=TaskContext(tenant_id=1, user_id=2, project_id="test"),
            prompt="整理版本计划",
        )

    def test_disabled_does_not_initialize_sdk(self):
        tracing = LangfuseTracing(
            settings(tracing_enabled=False, public_key=None, secret_key=None, base_url=None)
        )
        self.assertEqual(tracing.invocation_config(self.task, "execute"), {})
        tracing.shutdown()
        self.client_factory.assert_not_called()
        self.handler_factory.assert_not_called()
        self.propagation.assert_not_called()

    def test_enabled_requires_explicit_endpoint_and_keys(self):
        for missing in ("base_url", "public_key", "secret_key"):
            with self.assertRaises(ValidationError) as caught:
                settings(**{missing: None})
            self.assertNotIn("sk-offline", str(caught.exception))
        self.client_factory.assert_not_called()

    def test_shared_client_and_distinct_execution_callbacks(self):
        tracing = LangfuseTracing(settings())
        first = tracing.invocation_config(self.task, "execute")
        resumed = tracing.invocation_config(self.task, "resume")
        self.client_factory.assert_called_once_with(
            public_key="pk-offline",
            secret_key="sk-offline",
            base_url="http://127.0.0.1:3001",
            tracing_enabled=True,
            environment="test",
            timeout=2,
        )
        self.assertIsNot(first["callbacks"][0], resumed["callbacks"][0])
        calls = self.handler_factory.call_args_list
        first_id = calls[0].kwargs["trace_context"]["trace_id"]
        second_id = calls[1].kwargs["trace_context"]["trace_id"]
        self.assertRegex(first_id, r"^[0-9a-f]{32}$")
        self.assertNotEqual(first_id, second_id)

    def test_resume_and_execute_are_grouped_in_same_session(self):
        tracing = LangfuseTracing(settings())
        first = tracing.invocation_config(self.task, "execute")
        resumed = tracing.invocation_config(self.task, "resume")
        self.assertEqual(
            first["metadata"]["langfuse_session_id"], resumed["metadata"]["langfuse_session_id"]
        )
        self.assertEqual(first["metadata"]["langfuse_user_id"], "1:2")
        self.assertEqual(resumed["metadata"]["operation"], "resume")
        self.assertEqual(first["metadata"]["task_id"], str(self.task.id))
        self.assertEqual(first["metadata"]["task_trace_id"], str(self.task.context.trace_id))
        self.assertNotIn("整理版本计划", str(first["metadata"]))

    def test_users_do_not_share_session_identity(self):
        tracing = LangfuseTracing(settings())
        other = AgentTask(
            context=TaskContext(tenant_id=2, user_id=2, project_id="test"),
            prompt="另一个任务",
        )
        first = tracing.invocation_config(self.task, "execute")["metadata"]
        second = tracing.invocation_config(other, "execute")["metadata"]
        self.assertNotEqual(first["langfuse_session_id"], second["langfuse_session_id"])
        self.assertNotEqual(first["langfuse_user_id"], second["langfuse_user_id"])

    def test_callback_tags_include_agent_operation_round_and_explicit_langfuse_metadata(self):
        tracing = LangfuseTracing(settings())
        first = tracing.invocation_config(self.task.start(), "execute")
        tags = first["tags"]
        self.assertTrue(
            {
                "agent-platform",
                "workflow:task",
                "boundary:agent",
                "task_planning",
                "agent:task_planning",
                "execute",
                "operation:execute",
                "round:first",
                "invocation:new_round",
            }.issubset(tags)
        )
        self.assertEqual(tags, first["metadata"]["langfuse_tags"])
        self.assertEqual(len(tags), len(set(tags)))
        self.assertNotIn(str(self.task.id), tags)
        resumed = tracing.invocation_config(self.task.start(), "resume")["tags"]
        self.assertIn("invocation:human_resume", resumed)
        self.assertNotIn("invocation:new_round", resumed)
        followup = self.task.start().complete("已完成").queue_next().start()
        self.assertIn("round:followup", tracing.invocation_config(followup, "execute")["tags"])

    def test_propagation_failure_cleans_span_without_stopping_business(self):
        tracing = LangfuseTracing(settings())
        manager = MagicMock()  # 真实上下文管理协议的离线替身
        self.client.start_as_current_observation.return_value = manager
        self.propagation.side_effect = RuntimeError("tags unavailable")
        with self.assertLogs(level="WARNING"):
            with tracing.observation("worker.consume") as context:
                self.assertIsNone(context)
        manager.__exit__.assert_called_once()

    def test_shutdown_flushes_once_and_stops_new_callbacks(self):
        tracing = LangfuseTracing(settings())
        tracing.shutdown()
        tracing.shutdown()
        self.client.shutdown.assert_called_once_with()
        self.assertEqual(tracing.invocation_config(self.task, "execute"), {})
