"""离线验证跨进程数据契约，不初始化真实 SDK 或访问外部服务。"""

import asyncio
import json
import sys
import unittest
from contextlib import contextmanager
from contextvars import ContextVar
from types import ModuleType
from unittest.mock import Mock, patch
from uuid import uuid4

from pydantic import SecretStr

from agent_platform.application.dto.trace_context import TraceContext
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.domain.types.common import TaskContext
from agent_platform.infrastructure.messaging.redis_job_queue import RedisJobQueue
from agent_platform.infrastructure.observability.langfuse import LangfuseTracing
from agent_platform.infrastructure.observability.redis_trace_context import RedisTraceContextStore
from agent_platform.infrastructure.observability.settings import LangfuseSettings


class MemoryRedis:
    def __init__(self):
        self.values = {}  # 模拟进程重启后仍保留的 Redis 数据
        self.records = []  # 队列字段必须是可序列化字符串

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.values[key] = value

    async def eval(self, script, number, *args):
        if "XADD" in script:
            fields = dict(zip(args[number::2], args[number + 1 :: 2], strict=True))
            return await self.xadd(name=args[0], fields=fields)
        # 测试只模拟追踪 SET，真实的事件流关闭互斥另行验证。
        return await self.set(args[1], args[2])

    async def xadd(self, *, name, fields):
        self.records.append(("1-0", json.loads(json.dumps(fields))))
        return "1-0"

    async def xreadgroup(self, **kwargs):
        return [("jobs", [self.records.pop(0)])] if self.records else []


class LocalClient:
    def __init__(self):
        self.current = ContextVar("test_trace", default=None)
        self.records = []
        self.tags = ContextVar("test_tags", default=())  # 模拟 SDK 的协程标签传播
        self.tag_records = []  # 记录实际进入的片段及标签

    @contextmanager
    def propagate_attributes(self, *, tags):
        current = tuple(dict.fromkeys((*self.tags.get(), *tags)))
        token = self.tags.set(current)
        self.tag_records.append((self.current.get(), current))
        try:
            yield
        finally:
            self.tags.reset(token)

    @contextmanager
    def start_as_current_observation(self, *, name, trace_context, **kwargs):
        parent = trace_context or self.current.get()
        context = TraceContext(
            trace_id=parent["trace_id"] if parent else uuid4().hex,
            parent_span_id=uuid4().hex[:16],
        )
        self.records.append((name, parent, context))
        token = self.current.set(context.model_dump())
        try:
            yield
        finally:
            self.current.reset(token)

    def get_current_trace_id(self):
        current = self.current.get()
        return current["trace_id"] if current else None

    def get_current_observation_id(self):
        current = self.current.get()
        return current["parent_span_id"] if current else None


class DistributedTracingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.redis = MemoryRedis()
        self.client = LocalClient()
        sdk = ModuleType("langfuse")
        sdk.Langfuse = Mock(return_value=self.client)
        sdk.propagate_attributes = self.client.propagate_attributes
        integration = ModuleType("langfuse.langchain")
        self.handler = Mock(return_value=object())
        integration.CallbackHandler = self.handler
        modules = patch.dict(sys.modules, {"langfuse": sdk, "langfuse.langchain": integration})
        modules.start()
        self.addCleanup(modules.stop)
        self.settings = LangfuseSettings(
            _env_file=None,
            tracing_enabled=True,
            base_url="http://localhost:3001",
            public_key=SecretStr("offline"),
            secret_key=SecretStr("offline"),
        )
        self.tracing = self.make_tracing()
        self.task = AgentTask(
            context=TaskContext(tenant_id=1, user_id=2, project_id="test"),
            prompt="规划任务",
        ).start()

    def make_tracing(self):
        return LangfuseTracing(self.settings, RedisTraceContextStore(self.redis))

    async def test_api_queue_worker_agent_use_one_trace_and_nested_spans(self):
        queue = RedisJobQueue(
            client=self.redis, stream_name="jobs", group_name="g", tracing=self.tracing
        )
        async with self.tracing.api("create") as api:
            await queue.enqueue(self.task.context)
        _, job = await queue.receive()
        self.assertEqual(job.trace_context, api)
        self.assertIsNone(self.tracing.current_context())
        with self.tracing.observation("worker.consume", parent=job.trace_context) as worker:
            async with self.tracing.agent(self.task, "execute"):
                agent = self.tracing.current_context()
                self.tracing.invocation_config(self.task, "execute")
                self.assertEqual(self.handler.call_args.kwargs["trace_context"], agent.model_dump())
                self.assertEqual(agent.trace_id, api.trace_id)
                self.assertNotEqual(agent.parent_span_id, worker.parent_span_id)
                self.assertEqual(self.client.records[-1][1], worker.model_dump())
        self.assertIsNone(self.tracing.current_context())

    async def test_human_resume_after_restart_reuses_trace_but_next_input_does_not(self):
        async with self.tracing.api("create") as first:
            async with self.tracing.agent(self.task, "execute"):
                original_agent = self.tracing.current_context()
        restarted = self.make_tracing()
        async with restarted.api("resume", task=self.task) as resumed:
            self.assertEqual(first.trace_id, resumed.trace_id)
            self.assertEqual(self.client.records[-1][1], original_agent.model_dump())
        async with restarted.api("message", task=self.task) as next_input:
            self.assertNotEqual(first.trace_id, next_input.trace_id)

    async def test_parallel_requests_do_not_leak_context(self):
        async def one():
            async with self.tracing.api("create") as context:
                await asyncio.sleep(0)
                self.assertEqual(context, self.tracing.current_context())
                return context.trace_id

        ids = await asyncio.gather(one(), one(), one())
        self.assertEqual(len(set(ids)), 3)
        self.assertIsNone(self.tracing.current_context())

    async def test_tags_cover_api_worker_agent_and_leave_no_shared_state(self):
        async with self.tracing.api("create") as api:
            self.assertIn("boundary:api", self.client.tags.get())
            self.assertIn("operation:create", self.client.tags.get())
        self.assertEqual(self.client.tags.get(), ())
        with self.tracing.observation("worker.consume", parent=api):
            self.assertIn("boundary:worker", self.client.tags.get())
            async with self.tracing.agent(self.task, "execute"):
                self.assertIn("agent:task_planning", self.client.tags.get())
                self.assertIn("round:first", self.client.tags.get())
            self.assertNotIn("agent:task_planning", self.client.tags.get())
        self.assertEqual(self.client.tags.get(), ())

    async def test_parallel_tag_scopes_and_exception_cleanup(self):
        async def one(operation):
            async with self.tracing.api(operation, task=self.task):
                await asyncio.sleep(0)
                tags = self.client.tags.get()
                self.assertIn(f"operation:{operation}", tags)
                self.assertNotIn(
                    "operation:message" if operation == "resume" else "operation:resume", tags
                )

        await asyncio.gather(one("message"), one("resume"))
        for error in (ValueError("业务失败"), asyncio.CancelledError()):
            with self.assertRaises(type(error)):
                async with self.tracing.agent(self.task, "execute"):
                    raise error
            self.assertEqual(self.client.tags.get(), ())

    async def test_merged_inputs_link_both_sources(self):
        sources = []
        for message_id in ("a", "b"):
            async with self.tracing.api("message", task=self.task, message_id=message_id) as source:
                sources.append(source)
        with patch.object(self.tracing, "_link") as link:
            async with self.tracing.agent(self.task, "execute", ("a", "b")):
                pass
        self.assertEqual([call.args[0] for call in link.call_args_list], sources)

    async def test_business_exception_and_cancellation_propagate_and_clean_context(self):
        for error in (ValueError("业务失败"), asyncio.CancelledError()):
            with self.assertRaises(type(error)):
                async with self.tracing.api("create"):
                    raise error
            self.assertIsNone(self.tracing.current_context())

    async def test_trace_store_failure_does_not_fail_execution(self):
        with patch.object(self.redis, "set", side_effect=RuntimeError("Redis unavailable")):
            with self.assertLogs(level="WARNING"):
                async with self.tracing.agent(self.task, "execute"):
                    pass

    async def test_old_or_corrupt_queue_tracing_does_not_reject_business_message(self):
        queue = RedisJobQueue(client=self.redis, stream_name="jobs", group_name="g")
        self.redis.records.append(("1-0", {"context": self.task.context.model_dump_json()}))
        _, job = await queue.receive()
        self.assertIsNone(job.trace_context)
        self.redis.records.append(
            ("2-0", {"context": self.task.context.model_dump_json(), "trace_context": "not-json"})
        )
        with self.assertLogs(level="WARNING"):
            _, job = await queue.receive()
        self.assertIsNone(job.trace_context)

    async def test_callback_failure_does_not_fail_business_execution(self):
        self.handler.side_effect = RuntimeError("callback unavailable")
        with self.assertLogs(level="WARNING"):
            self.assertEqual(self.tracing.invocation_config(self.task, "execute"), {})

    async def test_zero_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            TraceContext(trace_id="0" * 32, parent_span_id="1" * 16)

    async def test_links_use_real_otel_span_context(self):
        source = TraceContext(trace_id="1" * 32, parent_span_id="2" * 16)
        with patch("opentelemetry.trace.get_current_span") as current:
            self.tracing._link(source, "message-1")
        context, attributes = current.return_value.add_link.call_args.args
        self.assertEqual(context.trace_id, int(source.trace_id, 16))
        self.assertEqual(context.span_id, int(source.parent_span_id, 16))
        self.assertEqual(attributes, {"message_id": "message-1"})


if __name__ == "__main__":
    unittest.main()
