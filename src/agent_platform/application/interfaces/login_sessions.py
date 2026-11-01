"""可撤销登录会话契约，不绑定 Redis。"""

from abc import ABC, abstractmethod

from pydantic import Field

from agent_platform.domain.types.common import StrictModel


class LoginSession(StrictModel):
    tenant_id: int = Field(gt=0)  # 登录租户
    user_id: int = Field(gt=0)  # 登录用户
    auth_revision: int = Field(ge=1)  # 登录时的凭据修订号


class LoginSessions(ABC):
    @abstractmethod
    async def create(self, session: LoginSession) -> str: ...

    @abstractmethod
    async def get(self, token: str) -> LoginSession | None: ...

    @abstractmethod
    async def delete(self, token: str) -> None: ...

    @abstractmethod
    async def check_login_limit(self, client: str, account: str) -> None: ...
