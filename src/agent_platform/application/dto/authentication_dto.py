"""认证和用户管理返回的安全数据，不包含密码摘要。"""

from datetime import datetime
from typing import Literal

from agent_platform.domain.aggregates.user import User
from agent_platform.domain.types.common import Principal, StrictModel
from agent_platform.domain.types.tenant import Tenant


class CurrentUser(StrictModel):
    id: int  # 整数用户主键
    tenant_id: int  # 所属租户
    tenant_code: str  # 公司代码
    tenant_name: str  # 公司名称
    project_id: str  # 服务端确定的默认项目
    username: str  # 登录名
    display_name: str  # 显示名称
    role: Literal["admin", "user"]  # 当前角色

    @classmethod
    def from_user(cls, user: User, tenant: Tenant) -> "CurrentUser":
        return cls(
            id=user.id,
            tenant_id=tenant.id,
            tenant_code=tenant.code,
            tenant_name=tenant.name,
            project_id=tenant.default_project_id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
        )

    def principal(self) -> Principal:
        return Principal(tenant_id=self.tenant_id, user_id=self.id, project_id=self.project_id)


class UserSummary(StrictModel):
    id: int  # 整数用户主键
    username: str  # 登录名
    display_name: str  # 显示名称
    role: Literal["admin", "user"]  # 账号角色
    enabled: bool  # 是否启用
    created_at: datetime  # 创建时间
    last_login_at: datetime | None  # 最近登录时间

    @classmethod
    def from_user(cls, user: User) -> "UserSummary":
        return cls.model_validate({key: getattr(user, key) for key in cls.model_fields})


class UserPage(StrictModel):
    items: tuple[UserSummary, ...]  # 当前页用户
    next_cursor: int | None  # 下一页整数游标


class AuthenticationError(Exception):
    """凭据无效或会话失效。"""


class LoginLimitedError(Exception):
    """登录尝试过于频繁。"""

    def __init__(self, message: str, *, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after  # 距离可以重试的保守等待秒数
