"""复用已有 Redis，保存人工恢复与合并消息所需的追踪上下文。"""

import logging

from redis.asyncio import Redis

from agent_platform.application.dto.trace_context import TraceContext
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.infrastructure.harness.runtime.checkpoint_namespace import checkpoint_thread
from agent_platform.infrastructure.messaging.redis_task_events import RedisTaskEvents

logger = logging.getLogger(__name__)


class RedisTraceContextStore:
    def __init__(self, client: Redis) -> None:
        self._client = client  # 共享连接池，不单独创建或关闭客户端

    @staticmethod
    def key(task: AgentTask, suffix: str) -> str:
        return f"harness:tracing:{checkpoint_thread(task.context)}:{task.id}:{suffix}"

    async def get(self, task: AgentTask, suffix: str) -> TraceContext | None:
        try:
            value = await self._client.get(self.key(task, suffix))
            return TraceContext.model_validate_json(value) if value else None
        except Exception:
            logger.warning("读取追踪上下文失败，继续业务执行", exc_info=True)
            return None

    async def delete_task(self, task: AgentTask) -> None:
        """追踪组件清理自己维护的键；事件流关闭后迟到回调无法重建。"""
        batch = []
        async for key in self._client.scan_iter(match=self.key(task, "*"), count=200):
            batch.append(key)
            if len(batch) == 200:
                await self._client.delete(*batch)
                batch.clear()
        if batch:
            await self._client.delete(*batch)

    async def put(self, task: AgentTask, suffix: str, context: TraceContext) -> None:
        try:
            # 不设置短 TTL，避免等待人工处理期间失去关联；按任务归档时统一清理。
            # 与删除事件流原子互斥，迟到的 API 追踪回调不得重建已删除会话的键。
            event_key = RedisTaskEvents.stream_key(task.context)
            await self._client.eval(
                "if redis.call('EXISTS', KEYS[1]) == 1 then "
                "return redis.call('SET', KEYS[2], ARGV[1]) end return 0",
                2,
                event_key,
                self.key(task, suffix),
                context.model_dump_json(),
            )
        except Exception:
            logger.warning("保存追踪上下文失败，继续业务执行", exc_info=True)
