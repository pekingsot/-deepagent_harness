"""通过 SQLAlchemy 和 pgvector 实现长期记忆仓储。"""

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_platform.domain.repositories.user_memory_repository import MemoryRepository
from agent_platform.domain.types.common import Principal
from agent_platform.domain.types.memory_match import MemoryMatch
from agent_platform.infrastructure.persistence.entities import UserMemoryRecord


class PostgresMemoryRepository(MemoryRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _validate_vector(vector: list[float]) -> None:
        """确保向量维度正确，且不包含非法数值。"""
        if len(vector) != 1024:
            raise ValueError(f"记忆向量必须是 1024 维 当前传入的是 {len(vector)}")

        if not all(math.isfinite(value) for value in vector):
            raise ValueError("记忆向量不能包含 NaN 或无穷值")

        if not any(value != 0 for value in vector):
            raise ValueError("余弦检索不能使用全零向量")

    async def save(
        self,
        *,
        principal: Principal,
        content: str,
        embedding: list[float],
        embedding_model: str,
    ) -> int:
        """保存一条记忆，返回数据库生成的 ID。"""
        content = content.strip()
        if not content:
            raise ValueError("记忆内容不能为空")

        if not embedding_model.strip() or len(embedding_model) > 128:
            raise ValueError("向量模型标识不能为空，且不能超过 128 个字符")

        self._validate_vector(embedding)

        memory = UserMemoryRecord(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            content=content,
            embedding=embedding,
            embedding_model=embedding_model,
        )

        async with self._session_factory.begin() as session:
            session.add(memory)
            await session.flush()
            memory_id = memory.id

        return memory_id

    async def search(
        self,
        *,
        principal: Principal,
        embedding: list[float],
        embedding_model: str,
        limit: int = 5,
    ) -> list[MemoryMatch]:
        """在当前租户、当前用户的记忆中进行余弦检索。"""
        self._validate_vector(embedding)

        if not 1 <= limit <= 20:
            raise ValueError("返回数量必须在 1 到 20 之间")

        distance = UserMemoryRecord.embedding.cosine_distance(embedding)

        statement = (
            select(
                UserMemoryRecord.id,
                UserMemoryRecord.content,
                (1 - distance).label("similarity"),
            )
            .where(
                UserMemoryRecord.tenant_id == principal.tenant_id,
                UserMemoryRecord.user_id == principal.user_id,
                UserMemoryRecord.embedding_model == embedding_model,
            )
            .order_by(distance)
            .limit(limit)
        )

        async with self._session_factory() as session:
            result = await session.execute(statement)

            return [
                MemoryMatch(
                    id=memory_id,
                    content=content,
                    similarity=float(similarity),
                )
                for memory_id, content, similarity in result
            ]
