"""用户仓储契约，领域不依赖数据库实现。"""

from abc import ABC, abstractmethod

from agent_platform.domain.aggregates.user import User
from agent_platform.domain.types.tenant import Tenant


class UserRepository(ABC):
    @abstractmethod
    async def tenant_by_code(self, code: str) -> Tenant | None: ...

    @abstractmethod
    async def tenant(self, tenant_id: int, *, lock: bool = False) -> Tenant | None: ...

    @abstractmethod
    async def by_name(self, username: str) -> User | None:
        """仅用于登录和账号唯一性检查；业务查询仍按租户及用户 ID 隔离。"""
        ...

    @abstractmethod
    async def get(self, tenant_id: int, user_id: int) -> User | None: ...

    @abstractmethod
    async def list_users(self, tenant_id: int, *, after_id: int, limit: int) -> list[User]: ...

    @abstractmethod
    async def count_admins(self, tenant_id: int) -> int: ...

    @abstractmethod
    async def create(
        self, tenant_id: int, username: str, display_name: str, password_hash: str, role: str
    ) -> User: ...

    @abstractmethod
    async def save(self, user: User) -> None: ...

    @abstractmethod
    async def record_login(self, user: User) -> bool: ...

    @abstractmethod
    async def create_tenant(self, code: str, name: str) -> Tenant: ...
