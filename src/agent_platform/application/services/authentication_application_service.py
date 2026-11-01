"""登录编排：数据库账号、密码能力和可撤销会话。"""

import asyncio

from sqlalchemy_transactional.asyncio import transactional
from sqlalchemy_transactional.common import Propagation

from agent_platform.application.dto.authentication_dto import AuthenticationError, CurrentUser
from agent_platform.application.dto.user_command import ChangePasswordCommand, LoginCommand
from agent_platform.application.interfaces.login_sessions import LoginSession, LoginSessions
from agent_platform.application.interfaces.password_hasher import PasswordHasher
from agent_platform.domain.aggregates.user import User
from agent_platform.domain.repositories.user_repository import UserRepository
from agent_platform.domain.types.common import Principal
from agent_platform.domain.types.tenant import Tenant


class AuthenticationApplicationService:
    def __init__(
        self,
        repository: UserRepository,
        passwords: PasswordHasher,
        sessions: LoginSessions,
        session_ttl: int,
    ) -> None:
        self._repository = repository  # 用户仓储接口
        self._passwords = passwords  # 密码摘要接口
        self._sessions = sessions  # 登录会话接口
        self.session_ttl = session_ttl  # 登录有效秒数，绝对过期

    async def login(self, command: LoginCommand, client: str) -> tuple[str, CurrentUser]:
        await self._sessions.check_login_limit(client, command.username)
        tenant, user = await self._credentials(command)
        valid = await asyncio.to_thread(
            self._passwords.verify,
            command.password.get_secret_value(),
            user.password_hash.get_secret_value() if user else None,
        )
        if not valid or tenant is None or user is None or not tenant.enabled or not user.enabled:
            raise AuthenticationError("用户名或密码错误")
        await self._record_login(user)
        token = await self._sessions.create(
            LoginSession(
                tenant_id=user.tenant_id,
                user_id=user.id,
                auth_revision=user.auth_revision,
            )
        )
        return token, CurrentUser.from_user(user, tenant)

    @transactional(Propagation.REQUIRED)
    async def _credentials(self, command: LoginCommand) -> tuple[Tenant | None, User | None]:
        user = await self._repository.by_name(command.username)
        tenant = await self._repository.tenant(user.tenant_id) if user else None
        return tenant, user

    @transactional(Propagation.REQUIRED)
    async def _record_login(self, user: User) -> None:
        if not await self._repository.record_login(user):
            raise AuthenticationError("账号已变更，请重新登录")

    async def authenticate(self, token: str) -> CurrentUser:
        session = await self._sessions.get(token)
        if session is None:
            raise AuthenticationError("请先登录，或重新登录已过期的账号")
        tenant, user = await self._identity(session.tenant_id, session.user_id)
        if (
            tenant is None
            or not tenant.enabled
            or user is None
            or not user.enabled
            or user.auth_revision != session.auth_revision
        ):
            await self._sessions.delete(token)
            raise AuthenticationError("登录已失效，请重新登录")
        return CurrentUser.from_user(user, tenant)

    @transactional(Propagation.REQUIRED)
    async def _identity(self, tenant_id: int, user_id: int) -> tuple[Tenant | None, User | None]:
        return (
            await self._repository.tenant(tenant_id),
            await self._repository.get(tenant_id, user_id),
        )

    async def require_active_principal(self, principal: Principal) -> None:
        """Worker 在开始新执行前复核账号，退出登录不会撤销已接收的任务。"""
        tenant, user = await self._identity(principal.tenant_id, principal.user_id)
        if (
            tenant is None
            or not tenant.enabled
            or user is None
            or not user.enabled
            or tenant.default_project_id != principal.project_id
        ):
            raise AuthenticationError("任务所属账号已停用或不存在")

    async def logout(self, token: str) -> None:
        await self._sessions.delete(token)

    async def change_password(self, principal: Principal, command: ChangePasswordCommand) -> None:
        _, user = await self._identity(principal.tenant_id, principal.user_id)
        if user is None or not await asyncio.to_thread(
            self._passwords.verify,
            command.current_password.get_secret_value(),
            user.password_hash.get_secret_value() if user else None,
        ):
            raise AuthenticationError("当前密码不正确")
        password_hash = await asyncio.to_thread(
            self._passwords.hash, command.new_password.get_secret_value()
        )
        await self._change_password(user, password_hash)

    @transactional(Propagation.REQUIRED)
    async def _change_password(self, previous: User, password_hash: str) -> None:
        await self._repository.tenant(previous.tenant_id, lock=True)
        user = await self._repository.get(previous.tenant_id, previous.id)
        if user is None or not user.enabled or user.auth_revision != previous.auth_revision:
            raise AuthenticationError("账号已变更，请重新登录")
        await self._repository.save(user.revise(password_hash=password_hash))
