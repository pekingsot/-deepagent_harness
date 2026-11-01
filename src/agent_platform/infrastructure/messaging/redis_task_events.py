"""通过 Redis Streams 保存执行事件，供多个 SSE 连接独立读取。"""

import json
import re

from pydantic import JsonValue
from redis.asyncio import Redis

from agent_platform.application.dto.task_event_dto import TaskEvent
from agent_platform.application.dto.task_event_types import STREAMING_EVENTS
from agent_platform.application.interfaces.task_events import TaskEvents
from agent_platform.domain.types.common import TaskContext


class RedisTaskEvents(TaskEvents):
    def __init__(self, client: Redis) -> None:
        self._client = client  # 复用进程已有的异步 Redis 客户端

    @staticmethod
    def stream_key(context: TaskContext) -> str:
        """根据已认证的任务上下文隔离不同用户的事件。"""
        return (
            f"agent_platform:task_events:{context.tenant_id}:"
            f"{context.project_id}:{context.user_id}:{context.task_id}"
        )

    async def initialize(self, context: TaskContext) -> None:
        await self._client.eval(
            "if redis.call('EXISTS', KEYS[1]) == 0 then "
            "redis.call('XADD', KEYS[1], '*', 'event', 'initialized', 'data', '{}'); "
            "redis.call('SET', KEYS[2], '!') end return 1",
            2,
            self.stream_key(context),
            self.stream_key(context) + ":execution",
        )

    async def activate(self, context: TaskContext, execution_id: str, *, active: bool) -> None:
        await self._client.eval(
            "if redis.call('EXISTS', KEYS[1]) == 1 then "
            "return redis.call('SET', KEYS[2], ARGV[1]) end return 0",
            2,
            self.stream_key(context),
            self.stream_key(context) + ":execution",
            execution_id if active else "!" + execution_id,
        )

    async def delete(self, context: TaskContext) -> None:
        """事件组件负责自己的键，发布和删除由 Redis 原子串行执行。"""
        await self._client.delete(self.stream_key(context), self.stream_key(context) + ":execution")

    async def publish(self, context: TaskContext, event: str, data: dict[str, JsonValue]) -> str:
        payload = TaskEvent(id="0-0", event=event, data=data)
        return await self._client.eval(
            "local generation = redis.call('GET', KEYS[2]); "
            "if redis.call('EXISTS', KEYS[1]) == 0 then return '' end; "
            "if generation ~= ARGV[1] and "
            "(ARGV[2] == '1' or generation ~= '!' .. ARGV[1]) then return '' end; "
            "return redis.call('XADD', KEYS[1], '*', 'event', ARGV[3], 'data', ARGV[4])",
            2,
            self.stream_key(context),
            self.stream_key(context) + ":execution",
            str(data.get("execution_id") or ""),
            "1" if event in STREAMING_EVENTS else "0",
            payload.event,
            json.dumps(payload.data, ensure_ascii=False),
        )

    async def read(
        self, context: TaskContext, after_id: str, *, block_ms: int = 1000
    ) -> list[TaskEvent]:
        if re.fullmatch(r"\d+-\d+", after_id) is None:
            raise ValueError("事件游标必须是 Redis Stream 编号")
        if block_ms < 1:
            raise ValueError("事件读取等待时间必须大于零")

        streams = await self._client.xread(
            {self.stream_key(context): after_id}, count=100, block=block_ms
        )
        return [
            TaskEvent(
                id=message_id,
                event=fields["event"],
                data=json.loads(fields["data"]),
            )
            for _, messages in streams
            for message_id, fields in messages
        ]
