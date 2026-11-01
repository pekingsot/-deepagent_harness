"""显式启用后验证真实 Redis Lua 的执行隔离和删除互斥。"""

import os
import unittest
from uuid import uuid4

from redis.asyncio import Redis

from agent_platform.domain.types.common import TaskContext
from agent_platform.infrastructure.messaging.redis_task_events import RedisTaskEvents


@unittest.skipUnless(
    os.environ.get("HARNESS_RUN_PIPELINE_INTEGRATION") == "1",
    "Requires an explicitly configured test Redis",
)
class TaskEventFencingTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_replaced_and_deleted_streams_reject_late_callbacks(self):
        client = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        events = RedisTaskEvents(client)
        context = TaskContext(tenant_id=1, user_id=1, project_id="fencing-test")
        old, new = uuid4().hex, uuid4().hex
        try:
            await events.initialize(context)
            await events.activate(context, old, active=True)
            self.assertTrue(await events.publish(context, "text_delta", {"execution_id": old}))
            await events.activate(context, old, active=False)
            self.assertFalse(await events.publish(context, "text_delta", {"execution_id": old}))
            self.assertTrue(await events.publish(context, "completed", {"execution_id": old}))
            await events.activate(context, new, active=True)
            self.assertFalse(await events.publish(context, "text_delta", {"execution_id": old}))
            self.assertTrue(await events.publish(context, "text_delta", {"execution_id": new}))
            await events.delete(context)
            self.assertFalse(await events.publish(context, "text_delta", {"execution_id": new}))
            self.assertEqual(await client.exists(events.stream_key(context)), 0)
        finally:
            await events.delete(context)
            await client.aclose()
