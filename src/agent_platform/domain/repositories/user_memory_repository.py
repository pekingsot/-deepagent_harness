"""长期记忆仓储接口，由基础设施层实现。"""

from abc import ABC, abstractmethod

from agent_platform.domain.types.common import Principal
from agent_platform.domain.types.memory_match import MemoryMatch


class MemoryRepository(ABC):
    """只定义记忆存取能力，不加载模型，也不暴露 ORM。"""

    @abstractmethod
    async def save(
        self,
        *,
        principal: Principal,  # 服务端验证后的租户和用户身份
        content: str,  # 一条独立记忆的内容
        embedding: list[float],  # 内容对应的向量
        embedding_model: str,  # 生成向量的模型标识
    ) -> int:
        """保存记忆，返回数据库分配的记忆编号。"""
        raise NotImplementedError

    @abstractmethod
    async def search(
        self,
        *,
        principal: Principal,  # 限定记忆所属的租户和用户
        embedding: list[float],  # 查询问题对应的向量
        embedding_model: str,  # 只检索相同模型生成的向量
        limit: int = 5,  # 最多返回的记忆条数
    ) -> list[MemoryMatch]:
        """返回按相关程度排列的个人记忆。"""
        raise NotImplementedError
