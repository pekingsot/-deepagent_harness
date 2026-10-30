"""在不访问真实模型和数据库的情况下验证记忆用例。"""

import unittest
from unittest.mock import AsyncMock, MagicMock, create_autospec

from langchain_core.embeddings import Embeddings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_transactional.asyncio import current_session, sessionmaker_context, transactional
from sqlalchemy_transactional.common import Propagation, SessionNotBoundError

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

    async def asyncSetUp(self) -> None:
        self.session = MagicMock(spec=AsyncSession)  # 替代数据库会话，不连接真实数据库
        self.session.__aenter__.return_value = self.session
        self.session.begin.return_value.__aenter__ = AsyncMock()
        self.session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
        self.factory = MagicMock(return_value=self.session)  # 模拟入口绑定的会话工厂
        boundary = sessionmaker_context(self.factory)
        await boundary.__aenter__()
        self.addAsyncCleanup(boundary.__aexit__, None, None, None)

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

    async def test_embedding_runs_before_database_transaction(self) -> None:
        async def encode(texts):
            with self.assertRaises(SessionNotBoundError):
                current_session()
            self.factory.assert_not_called()
            return [[0.5] * 1024]

        async def save(**kwargs):
            self.assertIs(current_session(), self.session)
            return 7

        self.embeddings.aembed_documents.side_effect = encode
        self.repository.save.side_effect = save
        self.assertEqual(await self.service.save(self.principal, "中文注释"), 7)
        self.factory.assert_called_once_with()
        with self.assertRaises(SessionNotBoundError):
            current_session()

    async def test_search_embedding_runs_before_database_transaction(self) -> None:
        async def encode(query):
            with self.assertRaises(SessionNotBoundError):
                current_session()
            self.factory.assert_not_called()
            return [0.5] * 1024

        async def search(**kwargs):
            self.assertIs(current_session(), self.session)
            return []

        self.embeddings.aembed_query.side_effect = encode
        self.repository.search.side_effect = search
        self.assertEqual(await self.service.search(self.principal, "注释偏好"), [])
        self.factory.assert_called_once_with()

    async def test_memory_operations_join_outer_transaction(self) -> None:
        sessions = []  # 记录仓储调用时看到的 Session

        async def save(**kwargs):
            sessions.append(current_session())
            return 7

        async def delete(**kwargs):
            sessions.append(current_session())
            return True

        self.embeddings.aembed_documents.return_value = [[0.5] * 1024]
        self.repository.save.side_effect = save
        self.repository.delete.side_effect = delete

        @transactional(Propagation.REQUIRED)
        async def use_case():
            await self.service.save(self.principal, "中文注释")
            await self.service.delete(self.principal, 7)
            raise RuntimeError("撤销整个用例")

        with self.assertRaisesRegex(RuntimeError, "撤销整个用例"):
            await use_case()

        self.assertEqual(sessions, [self.session, self.session])
        self.factory.assert_called_once_with()
        self.session.begin.assert_called_once_with()
        exit_args = self.session.begin.return_value.__aexit__.call_args.args
        self.assertIs(exit_args[0], RuntimeError)
        with self.assertRaises(SessionNotBoundError):
            current_session()
