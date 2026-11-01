"""长期记忆应用服务。"""

from sqlalchemy_transactional.asyncio import transactional
from sqlalchemy_transactional.common import Propagation

from agent_platform.application.dto.user_memory_dto import UserMemoryPage
from agent_platform.application.interfaces.text_embeddings import TextEmbeddings
from agent_platform.domain.repositories.user_memory_repository import MemoryRepository
from agent_platform.domain.types.common import Principal
from agent_platform.domain.types.memory_match import MemoryMatch
from agent_platform.domain.types.user_memory import MemoryContent


class UserMemoryApplicationService:
    """编排向量编码和记忆存取，不创建连接或访问具体模型实现。"""

    def __init__(
        self,
        *,
        repository: MemoryRepository,
        embeddings: TextEmbeddings,
        embedding_model: str,
    ) -> None:
        if not embedding_model.strip() or len(embedding_model) > 128:
            raise ValueError("向量模型标识不能为空，且不能超过 128 个字符")

        self._repository = repository  # 记忆仓储抽象接口
        self._embeddings = embeddings  # 复用框架已有的向量编码抽象
        self._embedding_model = embedding_model  # 保存和查询必须使用相同的模型标识

    async def save(self, principal: Principal, content: str) -> int:
        """先生成向量，再保存记忆，避免推理期间占用数据库连接。"""
        content = MemoryContent(content=content).content

        vectors = await self._embeddings.aembed_documents([content])
        return await self._save_memory(
            principal=principal,
            content=content,
            embedding=vectors[0],
        )

    async def search(
        self,
        principal: Principal,
        query: str,
        *,
        limit: int = 5,
    ) -> list[MemoryMatch]:
        """编码查询问题，再检索当前用户的相关记忆。"""
        query = query.strip()
        if not query:
            raise ValueError("检索问题不能为空")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("返回数量必须是 1 到 20 之间的整数")

        vector = await self._embeddings.aembed_query(query)
        return await self._search_memories(
            principal=principal,
            embedding=vector,
            limit=limit,
        )

    @transactional(Propagation.REQUIRED)
    async def _save_memory(
        self,
        *,
        principal: Principal,
        content: str,
        embedding: list[float],
    ) -> int:
        """向量计算完成后才进入短事务；已有事务时加入调用方事务。"""
        return await self._repository.save(
            principal=principal,
            content=content,
            embedding=embedding,
            embedding_model=self._embedding_model,
        )

    @transactional(Propagation.REQUIRED)
    async def _search_memories(
        self,
        *,
        principal: Principal,
        embedding: list[float],
        limit: int,
    ) -> list[MemoryMatch]:
        """为数据库查询提供短事务上下文，不包含查询向量计算。"""
        return await self._repository.search(
            principal=principal,
            embedding=embedding,
            embedding_model=self._embedding_model,
            limit=limit,
        )

    @transactional(Propagation.REQUIRED)
    async def delete(
        self,
        principal: Principal,
        memory_id: int,
    ) -> bool:
        """删除指定记忆，不存在或不属于当前用户时返回 False。"""
        self._validate_memory_id(memory_id)

        return await self._repository.delete(
            principal=principal,
            memory_id=memory_id,
        )

    @staticmethod
    def _validate_memory_id(memory_id: int) -> None:
        """拒绝布尔值、字符串及超出数据库范围的编号。"""
        if type(memory_id) is not int or not 1 <= memory_id <= 9223372036854775807:
            raise ValueError("记忆编号必须是有效的正整数")

    async def update(
        self,
        principal: Principal,
        memory_id: int,
        content: str,
    ) -> bool:
        """校验新正文并重新计算向量，再原子替换原记忆。"""
        self._validate_memory_id(memory_id)
        content = MemoryContent(content=content).content
        vectors = await self._embeddings.aembed_documents([content])
        return await self._update_memory(
            principal=principal,
            memory_id=memory_id,
            content=content,
            embedding=vectors[0],
        )

    @transactional(Propagation.REQUIRED)
    async def _update_memory(
        self,
        *,
        principal: Principal,
        memory_id: int,
        content: str,
        embedding: list[float],
    ) -> bool:
        """数据库更新使用短事务，已有事务时加入。"""
        return await self._repository.update(
            principal=principal,
            memory_id=memory_id,
            content=content,
            embedding=embedding,
            embedding_model=self._embedding_model,
        )

    @transactional(Propagation.REQUIRED)
    async def list_recent(
        self,
        principal: Principal,
        *,
        cursor: int | None = None,
        limit: int = 20,
    ) -> UserMemoryPage:
        """分页列出记忆，额外读取一条判断是否还有下一页，不调用向量模型。"""
        if cursor is not None:
            self._validate_memory_id(cursor)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("每页数量必须是 1 到 50 之间的整数")
        rows = await self._repository.list_recent(
            principal=principal,
            before_id=cursor,
            limit=limit + 1,
        )
        items = tuple(rows[:limit])
        return UserMemoryPage(
            items=items,
            next_cursor=items[-1].id if len(rows) > limit else None,
        )
