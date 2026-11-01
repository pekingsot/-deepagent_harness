"""跨用户的管理规则；调用方负责数据库事务。"""

from typing import Literal

from agent_platform.domain.aggregates.user import User
from agent_platform.domain.repositories.user_repository import UserRepository
from agent_platform.domain.types.common import ConflictError, NotFoundError


class UserDomainService:
    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository  # 用户仓储接口

    async def list_users(
        self, tenant_id: int, actor_id: int, *, after_id: int, limit: int
    ) -> list[User]:
        await self.require_admin(tenant_id, actor_id)
        return await self._repository.list_users(tenant_id, after_id=after_id, limit=limit)

    async def create(
        self,
        tenant_id: int,
        actor_id: int,
        *,
        username: str,
        display_name: str,
        password_hash: str,
        role: Literal["admin", "user"],
    ) -> User:
        await self._repository.tenant(tenant_id, lock=True)
        await self.require_admin(tenant_id, actor_id)
        await self._ensure_available_username(username)
        return await self._repository.create(tenant_id, username, display_name, password_hash, role)

    async def initialize_tenant(
        self,
        code: str,
        name: str,
        *,
        username: str,
        display_name: str,
        password_hash: str,
    ) -> User:
        """公司初始化必须同时建立首位管理员，不能绕过用户名唯一性规则。"""
        if await self._repository.tenant_by_code(code):
            raise ConflictError("公司代码已存在，不能重复初始化")
        await self._ensure_available_username(username)
        tenant = await self._repository.create_tenant(code, name)
        return await self._repository.create(
            tenant.id, username, display_name, password_hash, "admin"
        )

    async def _ensure_available_username(self, username: str) -> None:
        if await self._repository.by_name(username):
            raise ConflictError("该登录名已存在")

    async def require_admin(self, tenant_id: int, user_id: int) -> User:
        tenant = await self._repository.tenant(tenant_id)
        actor = await self._repository.get(tenant_id, user_id)
        if tenant is None or not tenant.enabled or actor is None:
            raise PermissionError("账号或租户不可用")
        actor.require_admin()
        return actor

    async def update(
        self,
        tenant_id: int,
        actor_id: int,
        user_id: int,
        *,
        display_name: str | None = None,
        role: Literal["admin", "user"] | None = None,
        enabled: bool | None = None,
        password_hash: str | None = None,
    ) -> User:
        # 同租户管理写操作锁定租户行，串行维护最后一个管理员约束。
        await self._repository.tenant(tenant_id, lock=True)
        await self.require_admin(tenant_id, actor_id)
        user = await self._repository.get(tenant_id, user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        updated = user.revise(
            display_name=display_name, role=role, enabled=enabled, password_hash=password_hash
        )
        if (
            user.enabled
            and user.role == "admin"
            and (not updated.enabled or updated.role != "admin")
            and await self._repository.count_admins(tenant_id) <= 1
        ):
            raise ConflictError("必须保留至少一个启用的管理员")
        await self._repository.save(updated)
        return updated
