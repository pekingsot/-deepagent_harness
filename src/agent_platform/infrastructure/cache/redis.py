import logging
import os
from functools import lru_cache

from redis.asyncio import Redis as AsyncRedis

from agent_platform.bootstrap.settings import get_settings, Settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis客户端，用于完成redis缓存连接&使用"""

    def __init__(self)->None:
        """构造函数，完成redis客户端的创建"""
        self._client: AsyncRedis | None = None

    async def init(self) -> None:
        """完成redis客户端的初始化"""
        # 1.判断redis客户端是否存在，如果存在表示已经连接上，无需承诺更新连接
        if self._client is not None:
            return
        # 2.创建redis客户端
        url=os.environ.get("REDIS_URL","")
        if not url.strip():
            raise ValueError("REDIS_URL 不能为空")

        client = AsyncRedis.from_url(url=url, decode_responses=True)
        try:
            # 3.测试redis客户端
            await client.ping()
        except Exception as e:
            await client.aclose()
            logger.error(f"redis初始化失败:{str(e)}")

            raise e
        self._client = client
        logger.info("redis客户端初始化成功")

    async def shutdown(self)->None:
        """关闭redis时执行的操作"""
        # 1.客户端存在则关闭客户端并提示
        if self._client is not None:
            await  self._client.aclose()
            self._client = None
            logger.info("Redis客户端成功关闭")
        # 2.清除缓存
        # get_redis.cache_clear()

    @property
    def client(self) -> AsyncRedis:
        """只读属性返回redis客户端"""
        if self._client is None:
            raise RuntimeError("Redis客户端为初始化，获取客户端失败")
        return self._client


@lru_cache(maxsize=1)
def get_redis() -> RedisClient:
    """使用lrucache实现单例模式获取redis"""
    return RedisClient()
