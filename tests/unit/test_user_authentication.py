"""账号完整链路验证：SQLite 仓储、真实事务、替代 Redis 的会话契约。"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy_transactional.asyncio import sessionmaker_context

from agent_platform.application.dto.authentication_dto import AuthenticationError
from agent_platform.application.dto.user_command import CreateUserCommand
from agent_platform.application.interfaces.login_sessions import LoginSession, LoginSessions
from agent_platform.application.interfaces.password_hasher import PasswordHasher
from agent_platform.application.services.authentication_application_service import (
    AuthenticationApplicationService,
)
from agent_platform.application.services.user_application_service import UserApplicationService
from agent_platform.domain.services.user_domain_service import UserDomainService
from agent_platform.infrastructure.persistence.entities.sys_tenant import TenantRecord
from agent_platform.infrastructure.persistence.entities.sys_user import UserRecord
from agent_platform.infrastructure.persistence.repositories.user_repository import (
    PostgresUserRepository,
)
from agent_platform.interface.api.app import create_app
from agent_platform.interface.api.dependencies import get_authentication_service, get_user_service


class OfflinePasswords(PasswordHasher):
    """仅供用例测试的替代实现，生产不会装配此对象。"""

    def hash(self, password: str) -> str:
        return "test-only:" + password

    def verify(self, password: str, password_hash: str | None) -> bool:
        return password_hash == self.hash(password)


class OfflineSessions(LoginSessions):
    def __init__(self):
        self.sessions = {}  # 测试会话
        self.sequence = 0  # 测试令牌计数

    async def create(self, session: LoginSession) -> str:
        self.sequence += 1
        token = f"offline-session-{self.sequence}"
        self.sessions[token] = session
        return token

    async def get(self, token: str) -> LoginSession | None:
        return self.sessions.get(token)

    async def delete(self, token: str) -> None:
        self.sessions.pop(token, None)

    async def check_login_limit(self, client: str, account: str) -> None:
        pass


class UserAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as connection:
            await connection.run_sync(TenantRecord.__table__.create)
            await connection.run_sync(UserRecord.__table__.create)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        boundary = sessionmaker_context(self.factory)
        await boundary.__aenter__()
        repository = PostgresUserRepository()
        self.sessions = OfflineSessions()
        passwords = OfflinePasswords()
        self.auth = AuthenticationApplicationService(repository, passwords, self.sessions, 3600)
        self.users = UserApplicationService(UserDomainService(repository), passwords)
        self.admin = await self.users.initialize_tenant(
            "company",
            "测试公司",
            CreateUserCommand(
                username="admin",
                display_name="管理员",
                password="initial-password",
                role="admin",
            ),
        )
        self.other_admin = await self.users.initialize_tenant(
            "another",
            "另一公司",
            CreateUserCommand(
                username="other_admin",
                display_name="其他管理员",
                password="initial-password",
                role="admin",
            ),
        )
        await boundary.__aexit__(None, None, None)
        with patch(
            "agent_platform.interface.api.app.get_settings",
            return_value=SimpleNamespace(app_name="auth-test"),
        ):
            self.app = create_app()
        self.app.state.container = SimpleNamespace(
            database=SimpleNamespace(session_factory=self.factory)
        )
        self.app.dependency_overrides[get_authentication_service] = lambda: self.auth
        self.app.dependency_overrides[get_user_service] = lambda: self.users
        self.client = await self.enterAsyncContext(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://test",
            )
        )

    async def login(self, username="admin", password="initial-password"):
        response = await self.client.post(
            "/api/v1/auth/login",
            json={
                "username": username,
                "password": password,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["access_token"]

    @staticmethod
    def headers(token):
        return {"Authorization": f"Bearer {token}"}

    async def create_member(self, token, username="member"):
        response = await self.client.post(
            "/api/v1/users",
            headers=self.headers(token),
            json={
                "username": username,
                "display_name": "测试成员",
                "password": "member-password",
                "role": "user",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def test_login_identity_and_logout(self):
        self.assertEqual((await self.client.get("/api/v1/auth/me")).status_code, 401)
        token = await self.login()
        me = await self.client.get("/api/v1/auth/me", headers=self.headers(token))
        self.assertEqual(me.status_code, 200)
        self.assertIs(type(me.json()["id"]), int)
        self.assertEqual(me.json()["tenant_code"], "company")
        self.assertNotIn("password", me.text)
        response = await self.client.post("/api/v1/auth/logout", headers=self.headers(token))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            (await self.client.get("/api/v1/auth/me", headers=self.headers(token))).status_code, 401
        )

    async def test_generic_login_failure_and_no_development_bypass(self):
        for username, password in (("admin", "wrong"), ("missing", "wrong")):
            response = await self.client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": password},
            )
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["detail"], "用户名或密码错误")
        self.assertEqual(
            (
                await self.client.get("/api/v1/auth/me", headers=self.headers("offline-token"))
            ).status_code,
            401,
        )

    async def test_member_forbidden_and_tenant_isolation(self):
        admin_token = await self.login()
        member = await self.create_member(admin_token)
        member_token = await self.login("member", "member-password")
        response = await self.client.get("/api/v1/users", headers=self.headers(member_token))
        self.assertEqual(response.status_code, 403)
        response = await self.client.patch(
            f"/api/v1/users/{member['id']}",
            headers=self.headers(await self.login(username="other_admin")),
            json={"enabled": False},
        )
        self.assertEqual(response.status_code, 404)
        response = await self.client.get(
            "/api/v1/users", headers=self.headers(await self.login(username="other_admin"))
        )
        self.assertEqual([item["id"] for item in response.json()["items"]], [self.other_admin.id])
        response = await self.client.post(
            "/api/v1/users",
            headers=self.headers(admin_token),
            json={
                "username": "forged",
                "display_name": "伪造",
                "password": "member-password",
                "tenant_id": 999,
            },
        )
        self.assertEqual(response.status_code, 422)

    async def test_admin_constraint_disable_and_reenable(self):
        token = await self.login()
        for changes in ({"enabled": False}, {"role": "user"}):
            response = await self.client.patch(
                f"/api/v1/users/{self.admin.id}", headers=self.headers(token), json=changes
            )
            self.assertEqual(response.status_code, 409, response.text)
        member = await self.create_member(token)
        member_token = await self.login("member", "member-password")
        response = await self.client.patch(
            f"/api/v1/users/{member['id']}", headers=self.headers(token), json={"enabled": False}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (
                await self.client.get("/api/v1/auth/me", headers=self.headers(member_token))
            ).status_code,
            401,
        )
        response = await self.client.post(
            "/api/v1/auth/login",
            json={"username": "member", "password": "member-password"},
        )
        self.assertEqual(response.status_code, 401)
        await self.client.patch(
            f"/api/v1/users/{member['id']}", headers=self.headers(token), json={"enabled": True}
        )
        await self.login("member", "member-password")

    async def test_password_reset_revokes_all_sessions(self):
        admin_token = await self.login()
        member = await self.create_member(admin_token)
        old_tokens = [await self.login("member", "member-password") for _ in range(2)]
        response = await self.client.post(
            f"/api/v1/users/{member['id']}/reset-password",
            headers=self.headers(admin_token),
            json={"password": "replacement-password"},
        )
        self.assertEqual(response.status_code, 204)
        for token in old_tokens:
            self.assertEqual(
                (await self.client.get("/api/v1/auth/me", headers=self.headers(token))).status_code,
                401,
            )
        await self.login("member", "replacement-password")

    async def test_password_change_requires_old_password(self):
        token = await self.login()
        response = await self.client.put(
            "/api/v1/auth/password",
            headers=self.headers(token),
            json={"current_password": "bad", "new_password": "replacement-password"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            (await self.client.get("/api/v1/auth/me", headers=self.headers(token))).status_code, 200
        )
        response = await self.client.put(
            "/api/v1/auth/password",
            headers=self.headers(token),
            json={"current_password": "initial-password", "new_password": "replacement-password"},
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            (await self.client.get("/api/v1/auth/me", headers=self.headers(token))).status_code, 401
        )
        await self.login(password="replacement-password")

    async def test_pagination_duplicates_and_display_name(self):
        token = await self.login()
        member = await self.create_member(token)
        duplicate = await self.client.post(
            "/api/v1/users",
            headers=self.headers(token),
            json={"username": "member", "display_name": "重复", "password": "member-password"},
        )
        self.assertEqual(duplicate.status_code, 409)
        response = await self.client.get("/api/v1/users?limit=1", headers=self.headers(token))
        cursor = response.json()["next_cursor"]
        self.assertIs(type(cursor), int)
        response = await self.client.get(
            f"/api/v1/users?limit=1&after_id={cursor}", headers=self.headers(token)
        )
        self.assertEqual(response.json()["items"][0]["id"], member["id"])
        response = await self.client.patch(
            f"/api/v1/users/{self.admin.id}",
            headers=self.headers(token),
            json={"display_name": "新名字"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (await self.client.get("/api/v1/auth/me", headers=self.headers(token))).json()[
                "display_name"
            ],
            "新名字",
        )
        self.assertEqual(
            (
                await self.client.patch(
                    "/api/v1/users/not-an-int", headers=self.headers(token), json={"enabled": False}
                )
            ).status_code,
            422,
        )

    async def test_login_selects_company_from_account_and_rejects_company_input(self):
        token = await self.login(username="other_admin")
        response = await self.client.get("/api/v1/auth/me", headers=self.headers(token))
        self.assertEqual(response.json()["tenant_code"], "another")
        self.assertEqual(response.json()["id"], self.other_admin.id)
        response = await self.client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": "initial-password",
                "tenant_code": "another",
            },
        )
        self.assertEqual(response.status_code, 422)

    async def test_username_is_unique_across_companies(self):
        token = await self.login()
        await self.create_member(token)
        other_token = await self.login(username="other_admin")
        response = await self.client.post(
            "/api/v1/users",
            headers=self.headers(other_token),
            json={
                "username": "member",
                "display_name": "重名成员",
                "password": "member-password",
            },
        )
        self.assertEqual(response.status_code, 409)
        # 冲突不影响既有账号的密码和公司归属。
        member_token = await self.login("member", "member-password")
        response = await self.client.get("/api/v1/auth/me", headers=self.headers(member_token))
        self.assertEqual(response.json()["tenant_code"], "company")

    async def test_worker_rejects_disabled_account(self):
        token = await self.login()
        member = await self.create_member(token)
        member_token = await self.login("member", "member-password")
        response = await self.client.get("/api/v1/auth/me", headers=self.headers(member_token))
        from agent_platform.domain.types.common import Principal

        body = response.json()
        identity = Principal(
            tenant_id=body["tenant_id"], user_id=body["id"], project_id=body["project_id"]
        )
        await self.client.patch(
            f"/api/v1/users/{member['id']}", headers=self.headers(token), json={"enabled": False}
        )
        async with sessionmaker_context(self.factory):
            with self.assertRaises(AuthenticationError):
                await self.auth.require_active_principal(identity)


class RedisSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_keys_revocation_and_rate_limit(self):
        from agent_platform.application.dto.authentication_dto import LoginLimitedError
        from agent_platform.infrastructure.security.redis_login_sessions import RedisLoginSessions

        class RedisStub:
            def __init__(self):
                self.data = {}
                self.counts = {}
                self.expiry = {}

            async def set(self, key, value, ex):
                self.data[key], self.expiry[key] = value, ex

            async def get(self, key):
                return self.data.get(key)

            async def delete(self, key):
                self.data.pop(key, None)

            async def eval(self, script, number, key, window):
                self.counts[key] = self.counts.get(key, 0) + 1
                return self.counts[key]

        redis = RedisStub()
        sessions = RedisLoginSessions(redis, ttl=3600, login_limit=2, login_window=300)
        session = LoginSession(tenant_id=1, user_id=2, auth_revision=1)
        token = await sessions.create(session)
        self.assertNotIn(token, str(redis.data))
        self.assertEqual(await sessions.get(token), session)
        self.assertEqual(list(redis.expiry.values()), [3600])
        await sessions.delete(token)
        self.assertIsNone(await sessions.get(token))
        await sessions.check_login_limit("client", "account")
        await sessions.check_login_limit("client", "account")
        with self.assertRaises(LoginLimitedError):
            await sessions.check_login_limit("client", "account")
