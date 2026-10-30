"""长期记忆仓储接口，由基础设施层实现。"""

from abc import ABC, abstractmethod

from agent_platform.domain.types.common import Principal
from agent_platform.domain.types.memory_match import MemoryMatch
from agent_platform.domain.types.user_memory import UserMemory


class MemoryRepository(ABC):
    """记忆管理的仓储契约，不暴露 ORM、连接或事务实现。"""

    @abstractmethod
    async def list_recent(
        self,
        *,
        principal: Principal,
        before_id: int | None,
        limit: int,
    ) -> list[UserMemory]:
        """按编号倒序读取当前用户的记忆，不按向量模型过滤。"""
        raise NotImplementedError

    @abstractmethod
    async def update(
        self,
        *,
        principal: Principal,
        memory_id: int,
        content: str,
        embedding: list[float],
        embedding_model: str,
    ) -> bool:
        """在同一事务中替换当前用户记忆的正文、向量和模型标识。"""
        raise NotImplementedError

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

    @abstractmethod
    async def delete(
        self,
        *,
        principal: Principal,
        memory_id: int,
    ) -> bool:
        """删除当前用户的指定记忆，返回是否删除了记录。"""
        raise NotImplementedError
