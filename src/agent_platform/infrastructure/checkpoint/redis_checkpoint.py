from functools import lru_cache

from langgraph.checkpoint.redis import AsyncRedisSaver

from agent_platform.infrastructure.cache.redis import get_redis


class TaskRedisSaver(AsyncRedisSaver):
    """Redis Checkpoint 适配器负责补齐自身版本遗留键的清理。"""

    async def adelete_thread(self, thread_id: str) -> None:
        await super().adelete_thread(thread_id)
        for prefix in ("checkpoint", "checkpoint_write", "checkpoint_latest", "write_keys_zset"):
            batch = []
            async for key in self._redis.scan_iter(match=f"{prefix}:{thread_id}:*", count=200):
                batch.append(key)
                if len(batch) == 200:
                    await self._redis.delete(*batch)
                    batch.clear()
            if batch:
                await self._redis.delete(*batch)


@lru_cache(maxsize=1)
def get_redis_checkpointer() -> AsyncRedisSaver:
    return TaskRedisSaver(redis_client=get_redis().client)
