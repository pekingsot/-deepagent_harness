"""用内存数据库验证记忆管理的权限、分页和事务，不访问外部服务。"""

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import create_autospec, patch

from langchain_core.embeddings import Embeddings
from pydantic import ValidationError
from sqlalchemy import DateTime, Integer, JSON, String, Text, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy_transactional.asyncio import current_session, sessionmaker_context, transactional
from sqlalchemy_transactional.common import Propagation, SessionNotBoundError

from agent_platform.application.services.user_memory_application_service import UserMemoryApplicationService
from agent_platform.domain.types.common import Principal, TaskContext
from agent_platform.infrastructure.harness.tools.builtins.user_memory import create_user_memory_tools
from agent_platform.infrastructure.persistence.repositories.user_memory_repository import PostgresMemoryRepository


class MemoryTestBase(DeclarativeBase):
    pass


class MemoryRow(MemoryTestBase):
    """测试映射以 JSON 替代向量列，仅验证通用 CRUD，不模拟向量检索。"""

    __tablename__ = "user_memory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # 测试编号
    tenant_id: Mapped[int] = mapped_column(Integer)  # 租户编号
    user_id: Mapped[int] = mapped_column(Integer)  # 用户编号
    content: Mapped[str] = mapped_column(Text)  # 正文
    embedding: Mapped[list[float]] = mapped_column(JSON)  # 测试向量
    embedding_model: Mapped[str] = mapped_column(String(128))  # 模型标识
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())  # 创建时间
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())  # 更新时间


class UserMemoryManagementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as connection:
            await connection.run_sync(MemoryTestBase.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        boundary = sessionmaker_context(self.factory)
        await boundary.__aenter__()
        self.addAsyncCleanup(boundary.__aexit__, None, None, None)
        mapping = patch(
            "agent_platform.infrastructure.persistence.repositories.user_memory_repository.UserMemoryRecord",
            MemoryRow,
        )
        mapping.start()
        self.addCleanup(mapping.stop)
        self.embeddings = create_autospec(Embeddings, instance=True)
        self.embeddings.aembed_documents.return_value = [[0.5] * 1024]
        self.service = UserMemoryApplicationService(
            repository=PostgresMemoryRepository(), embeddings=self.embeddings, embedding_model="test-bge",
        )
        self.owner = Principal(tenant_id=1, user_id=2, project_id="test")

    async def test_create_update_list_delete(self):
        memory_id = await self.service.save(self.owner, " 喜欢蓝色 ")
        self.embeddings.aembed_documents.return_value = [[0.25] * 1024]
        self.assertTrue(await self.service.update(self.owner, memory_id, " 喜欢绿色 "))
        page = await self.service.list_recent(self.owner)
        self.assertEqual([(row.id, row.content) for row in page.items], [(memory_id, "喜欢绿色")])
        async with self.factory() as session:
            self.assertEqual((await session.get(MemoryRow, memory_id)).embedding, [0.25] * 1024)
        self.assertTrue(await self.service.delete(self.owner, memory_id))
        self.assertFalse(await self.service.delete(self.owner, memory_id))
        self.assertEqual((await self.service.list_recent(self.owner)).items, ())

    async def test_identity_scope(self):
        memory_id = await self.service.save(self.owner, "私人偏好")
        for tenant, user in [(1, 3), (2, 2)]:
            principal = Principal(tenant_id=tenant, user_id=user, project_id="test")
            self.assertEqual((await self.service.list_recent(principal)).items, ())
            self.assertFalse(await self.service.update(principal, memory_id, "不得覆盖"))
            self.assertFalse(await self.service.delete(principal, memory_id))
        self.assertEqual((await self.service.list_recent(self.owner)).items[0].content, "私人偏好")

    async def test_cursor_pagination_without_embedding(self):
        ids = [await self.service.save(self.owner, f"偏好{index}") for index in range(5)]
        self.embeddings.reset_mock()
        first = await self.service.list_recent(self.owner, limit=2)
        second = await self.service.list_recent(self.owner, cursor=first.next_cursor, limit=2)
        third = await self.service.list_recent(self.owner, cursor=second.next_cursor, limit=2)
        self.assertEqual([row.id for row in first.items + second.items + third.items], ids[::-1])
        self.assertIsNone(third.next_cursor)
        self.embeddings.aembed_documents.assert_not_awaited()
        self.embeddings.aembed_query.assert_not_awaited()

    async def test_list_includes_other_embedding_models(self):
        other = UserMemoryApplicationService(
            repository=PostgresMemoryRepository(), embeddings=self.embeddings, embedding_model="older-model",
        )
        memory_id = await other.save(self.owner, "旧模型的记忆")
        self.assertEqual((await self.service.list_recent(self.owner)).items[0].id, memory_id)

    async def test_embedding_failure_preserves_original_memory(self):
        memory_id = await self.service.save(self.owner, "原记忆")
        self.embeddings.aembed_documents.side_effect = RuntimeError("向量模型失败")
        with self.assertRaisesRegex(RuntimeError, "向量模型失败"):
            await self.service.update(self.owner, memory_id, "新记忆")
        self.assertEqual((await self.service.list_recent(self.owner)).items[0].content, "原记忆")

    async def test_outer_transaction_rolls_back_update_and_delete(self):
        first = await self.service.save(self.owner, "原记忆")
        second = await self.service.save(self.owner, "保留记录")

        @transactional(Propagation.REQUIRED)
        async def use_case():
            outer = current_session()
            await self.service.update(self.owner, first, "不应提交")
            await self.service.delete(self.owner, second)
            self.assertIs(current_session(), outer)
            raise RuntimeError("整个用例失败")

        with self.assertRaisesRegex(RuntimeError, "整个用例失败"):
            await use_case()
        page = await self.service.list_recent(self.owner)
        self.assertEqual({row.id: row.content for row in page.items}, {first: "原记忆", second: "保留记录"})

    async def test_update_embeds_before_opening_transaction(self):
        memory_id = await self.service.save(self.owner, "原记忆")

        async def encode(texts):
            with self.assertRaises(SessionNotBoundError):
                current_session()
            return [[0.25] * 1024]

        self.embeddings.aembed_documents.side_effect = encode
        self.assertTrue(await self.service.update(self.owner, memory_id, "新记忆"))

    async def test_invalid_input(self):
        for memory_id in [True, 0, -1, "1", 9223372036854775808]:
            with self.assertRaises(ValueError):
                await self.service.update(self.owner, memory_id, "正文")
        for text in [" ", "x" * 8001]:
            with self.assertRaises(ValueError):
                await self.service.save(self.owner, text)
            with self.assertRaises(ValueError):
                await self.service.update(self.owner, 1, text)
        for cursor, limit in [(True, 20), (0, 20), (None, True), (None, 51)]:
            with self.assertRaises(ValueError):
                await self.service.list_recent(self.owner, cursor=cursor, limit=limit)
        self.embeddings.aembed_documents.assert_not_awaited()

    async def test_tools_hide_identity_and_complete_crud(self):
        tools = {tool.name: tool for tool in create_user_memory_tools(self.service)}
        self.assertEqual(set(tools), {
            "save_user_memory", "search_user_memory", "list_user_memories", "update_user_memory", "delete_user_memory",
        })
        for tool in tools.values():
            properties = tool.tool_call_schema.model_json_schema()["properties"]
            self.assertFalse({"runtime", "tenant_id", "user_id", "principal"} & properties.keys())
        with self.assertRaises(ValidationError):
            tools["update_user_memory"].tool_call_schema.model_validate({"memory_id": "1", "content": "正文"})
        with self.assertRaises(RuntimeError):
            await tools["list_user_memories"].coroutine(runtime=SimpleNamespace(context=None))
        runtime = SimpleNamespace(context=TaskContext(tenant_id=1, user_id=2, project_id="test"))
        saved = await tools["save_user_memory"].coroutine(content="工具保存", runtime=runtime)
        memory_id = saved["memory_id"]
        self.assertTrue((await tools["update_user_memory"].coroutine(memory_id=memory_id, content="工具更新", runtime=runtime))["updated"])
        page = await tools["list_user_memories"].coroutine(runtime=runtime, limit=1)
        self.assertEqual(page["items"][0]["content"], "工具更新")
        self.assertFalse(page["has_more"])
        self.assertTrue((await tools["delete_user_memory"].coroutine(memory_id=memory_id, runtime=runtime))["deleted"])
