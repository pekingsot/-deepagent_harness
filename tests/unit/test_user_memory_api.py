"""个人记忆的 HTTP 契约检查，替代应用服务，不连接数据库或模型。"""

import unittest
from datetime import UTC, datetime
from unittest.mock import create_autospec

import httpx
from fastapi import FastAPI, HTTPException

from agent_platform.application.dto.user_memory_dto import UserMemoryPage
from agent_platform.application.services.user_memory_application_service import (
    UserMemoryApplicationService,
)
from agent_platform.domain.types.common import Principal
from agent_platform.domain.types.user_memory import UserMemory
from agent_platform.interface.api.dependencies import (
    get_principal,
    get_user_memory_application_service,
)
from agent_platform.interface.api.routes.v1.user_memories import router


class UserMemoryApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = create_autospec(UserMemoryApplicationService, instance=True)
        self.owner = Principal(tenant_id=1, user_id=2, project_id="default")
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_principal] = lambda: self.owner
        app.dependency_overrides[get_user_memory_application_service] = lambda: self.service
        self.app = app  # 只装配当前路由，不启动生产生命周期
        self.client = await self.enterAsyncContext(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            )
        )

    async def test_list_uses_server_identity_and_cursor(self):
        now = datetime.now(UTC)
        self.service.list_recent.return_value = UserMemoryPage(
            items=(
                UserMemory(
                    id=12,
                    content="偏好中文注释",
                    created_at=now,
                    updated_at=now,
                ),
            ),
            next_cursor=12,
        )
        response = await self.client.get("/api/v1/user-memories?cursor=30&limit=10")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["content"], "偏好中文注释")
        self.assertNotIn("embedding", response.text)
        self.service.list_recent.assert_awaited_once_with(self.owner, cursor=30, limit=10)

    async def test_update_and_delete_confirm_service_result(self):
        self.service.update.return_value = True
        response = await self.client.patch("/api/v1/user-memories/12", json={"content": " 新偏好 "})
        self.assertEqual(response.status_code, 204)
        self.service.update.assert_awaited_once_with(self.owner, 12, "新偏好")
        self.service.delete.return_value = True
        response = await self.client.delete("/api/v1/user-memories/12")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.service.update.return_value = False
        self.service.delete.return_value = False
        updated = await self.client.patch("/api/v1/user-memories/12", json={"content": "新偏好"})
        deleted = await self.client.delete("/api/v1/user-memories/12")
        self.assertEqual(updated.status_code, 404)
        self.assertEqual(deleted.status_code, 404)
        self.assertEqual(updated.json(), deleted.json())

    async def test_rejects_invalid_values_and_forged_identity(self):
        for content in ("", "  ", "a" * 8001):
            response = await self.client.patch(
                "/api/v1/user-memories/12", json={"content": content}
            )
            self.assertEqual(response.status_code, 422)
        response = await self.client.patch(
            "/api/v1/user-memories/12", json={"content": "偏好", "user_id": 99}
        )
        self.assertEqual(response.status_code, 422)
        for suffix in ("?cursor=0", "?limit=51", "?cursor=-1"):
            response = await self.client.get("/api/v1/user-memories" + suffix)
            self.assertEqual(response.status_code, 422)
        self.service.update.assert_not_awaited()
        self.service.list_recent.assert_not_awaited()

    async def test_requires_identity_for_all_operations(self):
        async def unauthenticated():
            raise HTTPException(status_code=401, detail="请先登录")

        self.app.dependency_overrides[get_principal] = unauthenticated
        for method, path, options in (
            ("GET", "/api/v1/user-memories", {}),
            ("PATCH", "/api/v1/user-memories/12", {"json": {"content": "偏好"}}),
            ("DELETE", "/api/v1/user-memories/12", {}),
        ):
            response = await self.client.request(method, path, **options)
            self.assertEqual(response.status_code, 401)
        self.service.list_recent.assert_not_awaited()
        self.service.update.assert_not_awaited()
        self.service.delete.assert_not_awaited()
