"""长期记忆应用服务。"""

from langchain_core.embeddings import Embeddings

from agent_platform.domain.repositories.user_memory_repository import MemoryRepository
from agent_platform.domain.types.common import Principal
from agent_platform.domain.types.memory_match import MemoryMatch


class UserMemoryApplicationService:
    """编排向量编码和记忆存取，不创建连接或访问具体模型实现。"""

    def __init__(
        self,
        *,
        repository: MemoryRepository,
        embeddings: Embeddings,
        embedding_model: str,
    ) -> None:
        if not embedding_model.strip() or len(embedding_model) > 128:
            raise ValueError("向量模型标识不能为空，且不能超过 128 个字符")

        self._repository = repository  # 记忆仓储抽象接口
        self._embeddings = embeddings  # 复用框架已有的向量编码抽象
        self._embedding_model = embedding_model  # 保存和查询必须使用相同的模型标识

    async def save(self, principal: Principal, content: str) -> int:
        """先生成向量，再保存记忆，避免推理期间占用数据库连接。"""
        content = content.strip()
        if not content:
            raise ValueError("记忆内容不能为空")

        vectors = await self._embeddings.aembed_documents([content])
        return await self._repository.save(
            principal=principal,
            content=content,
            embedding=vectors[0],
            embedding_model=self._embedding_model,
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
        return await self._repository.search(
            principal=principal,
            embedding=vector,
            embedding_model=self._embedding_model,
            limit=limit,
        )
