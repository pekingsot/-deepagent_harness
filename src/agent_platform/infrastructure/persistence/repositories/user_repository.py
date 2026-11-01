"""用户仓储实现；沿用当前会话，事务边界由应用层控制。"""

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy_transactional.asyncio import current_session

from agent_platform.domain.aggregates.user import User
from agent_platform.domain.repositories.user_repository import UserRepository
from agent_platform.domain.types.common import ConflictError
from agent_platform.domain.types.tenant import Tenant
from agent_platform.infrastructure.persistence.entities.sys_tenant import TenantRecord
from agent_platform.infrastructure.persistence.entities.sys_user import UserRecord


def user_from_record(row: UserRecord) -> User:
    return User.model_validate({key: getattr(row, key) for key in User.model_fields})


def tenant_from_record(row: TenantRecord) -> Tenant:
    return Tenant.model_validate({key: getattr(row, key) for key in Tenant.model_fields})


class PostgresUserRepository(UserRepository):
    async def tenant_by_code(self, code: str) -> Tenant | None:
        row = await current_session().scalar(select(TenantRecord).where(TenantRecord.code == code))
        return tenant_from_record(row) if row else None

    async def tenant(self, tenant_id: int, *, lock: bool = False) -> Tenant | None:
        query = select(TenantRecord).where(TenantRecord.id == tenant_id)
        if lock:
            query = query.with_for_update()
        row = await current_session().scalar(query)
        return tenant_from_record(row) if row else None

    async def by_name(self, username: str) -> User | None:
        result = await current_session().execute(
            select(UserRecord).where(UserRecord.username == username)
        )
        # 未完成唯一约束迁移时如有同名记录，明确失败，不能随意选一个用户。
        row = result.scalar_one_or_none()
        return user_from_record(row) if row else None

    async def get(self, tenant_id: int, user_id: int) -> User | None:
        row = await current_session().scalar(
            select(UserRecord).where(
                UserRecord.tenant_id == tenant_id,
                UserRecord.id == user_id,
            )
        )
        return user_from_record(row) if row else None

    async def list_users(self, tenant_id: int, *, after_id: int, limit: int) -> list[User]:
        rows = await current_session().scalars(
            select(UserRecord)
            .where(
                UserRecord.tenant_id == tenant_id,
                UserRecord.id > after_id,
            )
            .order_by(UserRecord.id)
            .limit(limit)
        )
        return [user_from_record(row) for row in rows]

    async def count_admins(self, tenant_id: int) -> int:
        return int(
            await current_session().scalar(
                select(func.count())
                .select_from(UserRecord)
                .where(
                    UserRecord.tenant_id == tenant_id,
                    UserRecord.role == "admin",
                    UserRecord.enabled.is_(True),
                )
            )
            or 0
        )

    async def create(
        self, tenant_id: int, username: str, display_name: str, password_hash: str, role: str
    ) -> User:
        row = UserRecord(
            tenant_id=tenant_id,
            username=username,
            display_name=display_name,
            password_hash=password_hash,
            role=role,
            enabled=True,
            auth_revision=1,
        )
        current_session().add(row)
        try:
            await current_session().flush()
        except IntegrityError as exc:
            # 数据库唯一约束兜住不同租户同时创建同名账号的竞争。
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint == "uq_sys_user_username":
                raise ConflictError("该登录名已存在") from exc
            raise
        return user_from_record(row)

    async def save(self, user: User) -> None:
        await current_session().execute(
            update(UserRecord)
            .where(
                UserRecord.tenant_id == user.tenant_id,
                UserRecord.id == user.id,
            )
            .values(
                display_name=user.display_name,
                password_hash=user.password_hash.get_secret_value(),
                role=user.role,
                enabled=user.enabled,
                auth_revision=user.auth_revision,
            )
        )

    async def record_login(self, user: User) -> bool:
        result = await current_session().execute(
            update(UserRecord)
            .where(
                UserRecord.id == user.id,
                UserRecord.tenant_id == user.tenant_id,
                UserRecord.enabled.is_(True),
                UserRecord.auth_revision == user.auth_revision,
            )
            .values(last_login_at=func.now())
            .returning(UserRecord.id)
        )
        return result.scalar_one_or_none() is not None

    async def create_tenant(self, code: str, name: str) -> Tenant:
        row = TenantRecord(code=code, name=name, enabled=True, default_project_id="default")
        current_session().add(row)
        await current_session().flush()
        return tenant_from_record(row)
