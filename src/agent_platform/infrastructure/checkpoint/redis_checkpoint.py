from functools import lru_cache

from langgraph.checkpoint.redis import AsyncRedisSaver

from agent_platform.infrastructure.cache.redis import get_redis


@lru_cache(maxsize=1)
def get_redis_checkpointer() -> AsyncRedisSaver:
    return AsyncRedisSaver(redis_client=get_redis().client)
