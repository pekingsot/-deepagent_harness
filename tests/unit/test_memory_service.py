"""在不访问真实模型和数据库的情况下验证记忆用例。"""

import unittest
from unittest.mock import create_autospec

from langchain_core.embeddings import Embeddings

from agent_platform.application.services.user_memory_application_service import (
    UserMemoryApplicationService,
)
from agent_platform.domain.repositories.user_memory_repository import MemoryRepository
from agent_platform.domain.types.common import Principal
from agent_platform.domain.types.memory_match import MemoryMatch


class MemoryServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.repository = create_autospec(MemoryRepository, instance=True)  # 替代数据库实现
        self.embeddings = create_autospec(Embeddings, instance=True)  # 替代真实模型推理
        self.principal = Principal(tenant_id=1, user_id=2, project_id="test")  # 已验证身份
        self.service = UserMemoryApplicationService(
            repository=self.repository,
            embeddings=self.embeddings,
            embedding_model="offline-bge",
        )

    async def test_save_preserves_identity_and_encodes_document(self) -> None:
        self.embeddings.aembed_documents.return_value = [[0.5] * 1024]
        self.repository.save.return_value = 7

        memory_id = await self.service.save(self.principal, "  注释使用中文  ")

        self.assertEqual(memory_id, 7)
        self.embeddings.aembed_documents.assert_awaited_once_with(["注释使用中文"])
        self.repository.save.assert_awaited_once_with(
            principal=self.principal,
            content="注释使用中文",
            embedding=[0.5] * 1024,
            embedding_model="offline-bge",
        )

    async def test_embedding_failure_does_not_write_memory(self) -> None:
        self.embeddings.aembed_documents.side_effect = RuntimeError("模型推理失败")

        with self.assertRaisesRegex(RuntimeError, "模型推理失败"):
            await self.service.save(self.principal, "注释使用中文")

        self.repository.save.assert_not_awaited()

    async def test_search_uses_query_encoder_and_tenant_scope(self) -> None:
        self.embeddings.aembed_query.return_value = [0.5] * 1024
        matches = [MemoryMatch(id=7, content="注释使用中文", similarity=0.8)]
        self.repository.search.return_value = matches

        result = await self.service.search(self.principal, " 注释语言？ ", limit=3)

        self.assertEqual(result, matches)
        self.embeddings.aembed_query.assert_awaited_once_with("注释语言？")
        self.repository.search.assert_awaited_once_with(
            principal=self.principal,
            embedding=[0.5] * 1024,
            embedding_model="offline-bge",
            limit=3,
        )

    async def test_invalid_input_does_not_call_model_or_repository(self) -> None:
        with self.assertRaises(ValueError):
            await self.service.save(self.principal, "  ")
        with self.assertRaises(ValueError):
            await self.service.search(self.principal, "查询", limit=0)

        self.embeddings.aembed_documents.assert_not_awaited()
        self.embeddings.aembed_query.assert_not_awaited()
        self.repository.save.assert_not_awaited()
        self.repository.search.assert_not_awaited()

    def test_repository_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            MemoryRepository()  # type: ignore[abstract]
