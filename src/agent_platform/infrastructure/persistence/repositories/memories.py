import math
from agent_platform.domain.common.models import Principal
from sqlalchemy import select

from pydantic import Field
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from agent_platform.infrastructure.persistence.models import Memory

from agent_platform.domain.common.models import StrictModel


class MemoryMatch(StrictModel):
    """查询返回的记忆，不包含完整向量。"""

    id: int = Field(gt=0)  # 记忆编号，用于定位、修改或删除
    content: str = Field(min_length=1)  # 记忆的文字内容
    similarity: float = Field(allow_inf_nan=False)  # 与问题的余弦相似度，越大越相似


class PostgresMemoryRepository:
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

        memory = Memory(
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

        distance = Memory.embedding.cosine_distance(embedding)

        statement = (
            select(
                Memory.id,
                Memory.content,
                (1 - distance).label("similarity"),
            )
            .where(
                Memory.tenant_id == principal.tenant_id,
                Memory.user_id == principal.user_id,
                Memory.embedding_model == embedding_model,
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
