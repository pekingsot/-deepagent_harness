"""用户管理用例：调用领域规则，不暴露 ORM 或密码摘要。"""

import asyncio

from pydantic import TypeAdapter
from sqlalchemy_transactional.asyncio import transactional
from sqlalchemy_transactional.common import Propagation

from agent_platform.application.dto.authentication_dto import UserPage, UserSummary
from agent_platform.application.dto.user_command import (
    AccountName,
    CreateUserCommand,
    UpdateUserCommand,
)
from agent_platform.application.interfaces.password_hasher import PasswordHasher
from agent_platform.domain.services.user_domain_service import UserDomainService
from agent_platform.domain.types.common import Principal


class UserApplicationService:
    def __init__(self, users: UserDomainService, passwords: PasswordHasher) -> None:
        self._users = users  # 用户领域服务
        self._passwords = passwords  # 密码处理能力

    @transactional(Propagation.REQUIRED)
    async def list_users(
        self, principal: Principal, *, after_id: int = 0, limit: int = 20
    ) -> UserPage:
        if not 1 <= limit <= 100 or after_id < 0:
            raise ValueError("分页参数不正确")
        users = await self._users.list_users(
            principal.tenant_id, principal.user_id, after_id=after_id, limit=limit + 1
        )
        return UserPage(
            items=tuple(UserSummary.from_user(user) for user in users[:limit]),
            next_cursor=users[limit - 1].id if len(users) > limit else None,
        )

    async def create(self, principal: Principal, command: CreateUserCommand) -> UserSummary:
        await self._check_admin(principal)
        password_hash = await asyncio.to_thread(
            self._passwords.hash, command.password.get_secret_value()
        )
        return await self._create(principal, command, password_hash)

    @transactional(Propagation.REQUIRED)
    async def _check_admin(self, principal: Principal) -> None:
        await self._users.require_admin(principal.tenant_id, principal.user_id)

    @transactional(Propagation.REQUIRED)
    async def _create(
        self, principal: Principal, command: CreateUserCommand, password_hash: str
    ) -> UserSummary:
        user = await self._users.create(
            principal.tenant_id,
            principal.user_id,
            username=command.username,
            display_name=command.display_name,
            password_hash=password_hash,
            role=command.role,
        )
        return UserSummary.from_user(user)

    @transactional(Propagation.REQUIRED)
    async def update(
        self, principal: Principal, user_id: int, command: UpdateUserCommand
    ) -> UserSummary:
        return UserSummary.from_user(
            await self._users.update(
                principal.tenant_id,
                principal.user_id,
                user_id,
                display_name=command.display_name,
                role=command.role,
                enabled=command.enabled,
            )
        )

    async def reset_password(self, principal: Principal, user_id: int, password: str) -> None:
        await self._check_admin(principal)
        password_hash = await asyncio.to_thread(self._passwords.hash, password)
        await self._reset_password(principal, user_id, password_hash)

    @transactional(Propagation.REQUIRED)
    async def _reset_password(self, principal: Principal, user_id: int, password_hash: str) -> None:
        await self._users.update(
            principal.tenant_id, principal.user_id, user_id, password_hash=password_hash
        )

    async def initialize_tenant(
        self, code: str, name: str, command: CreateUserCommand
    ) -> UserSummary:
        """仅供本地初始化命令调用；不提供公开 API。"""
        if not name.strip() or len(name) > 80:
            raise ValueError("公司名称应为1到80个字符")
        code = TypeAdapter(AccountName).validate_python(code, strict=True)
        password_hash = await asyncio.to_thread(
            self._passwords.hash, command.password.get_secret_value()
        )
        return await self._initialize_tenant(code, name.strip(), command, password_hash)

    @transactional(Propagation.REQUIRED)
    async def _initialize_tenant(
        self, code: str, name: str, command: CreateUserCommand, password_hash: str
    ) -> UserSummary:
        user = await self._users.initialize_tenant(
            code,
            name,
            username=command.username,
            display_name=command.display_name,
            password_hash=password_hash,
        )
        return UserSummary.from_user(user)
