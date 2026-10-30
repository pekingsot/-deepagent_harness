"""离线验证记忆检索的租户和模型过滤条件。"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql

from agent_platform.domain.repositories.user_memory_repository import MemoryRepository
from agent_platform.domain.types.common import Principal
from agent_platform.infrastructure.persistence.repositories.user_memory_repository import (
    PostgresMemoryRepository,
)


class MemoryRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_filters_identity_and_model_before_returning_matches(self) -> None:
        session = AsyncMock()  # 替代数据库会话，不连接真实 PG
        rows = MagicMock()  # 模拟数据库返回的投影结果
        rows.__iter__.return_value = iter([(7, "注释使用中文", 0.8)])
        session.execute.return_value = rows
        repository = PostgresMemoryRepository()

        with patch(
            "agent_platform.infrastructure.persistence.repositories.user_memory_repository.current_session",
            return_value=session,
        ) as get_session:
            matches = await repository.search(
                principal=Principal(tenant_id=11, user_id=22, project_id="test"),
                embedding=[0.5] * 1024,
                embedding_model="offline-bge",
                limit=3,
            )
        get_session.assert_called_once_with()
        session.commit.assert_not_awaited()
        session.close.assert_not_awaited()

        statement = session.execute.call_args.args[0]
        compiled = statement.compile(dialect=postgresql.dialect())
        self.assertIn("user_memory.tenant_id =", str(compiled))
        self.assertIn("user_memory.user_id =", str(compiled))
        self.assertIn("user_memory.embedding_model =", str(compiled))
        self.assertEqual(compiled.params["tenant_id_1"], 11)
        self.assertEqual(compiled.params["user_id_1"], 22)
        self.assertEqual(compiled.params["embedding_model_1"], "offline-bge")
        self.assertEqual(matches[0].id, 7)
        self.assertEqual(matches[0].content, "注释使用中文")
        self.assertIsInstance(repository, MemoryRepository)

    async def test_invalid_vector_does_not_open_session(self) -> None:
        repository = PostgresMemoryRepository()
        with patch(
            "agent_platform.infrastructure.persistence.repositories.user_memory_repository.current_session",
        ) as get_session:
            with self.assertRaises(ValueError):
                await repository.search(
                    principal=Principal(tenant_id=1, user_id=2, project_id="test"),
                    embedding=[0.0] * 1024,
                    embedding_model="offline-bge",
                )
        get_session.assert_not_called()
