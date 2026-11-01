"""用户聚合：账号状态、角色和凭据失效规则。"""

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator

from agent_platform.domain.types.common import Principal, StrictModel


class User(StrictModel):
    id: int = Field(gt=0, le=9223372036854775807)  # 数据库生成的整数用户主键
    tenant_id: int = Field(gt=0, le=9223372036854775807)  # 所属租户主键
    username: str = Field(
        min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$"
    )  # 全系统唯一的登录名
    display_name: str = Field(min_length=1, max_length=80)  # 页面展示名称
    password_hash: SecretStr = Field(min_length=1, max_length=512)  # 仅服务端使用的密码摘要
    role: Literal["admin", "user"]  # 租户管理员或普通用户
    enabled: bool  # 是否允许登录和执行任务
    auth_revision: int = Field(ge=1)  # 凭据修订号，用于使旧会话失效
    created_at: datetime  # 创建时间
    last_login_at: datetime | None  # 最近一次登录时间

    def require_enabled(self) -> None:
        if not self.enabled:
            raise PermissionError("账号已停用")

    def require_admin(self) -> None:
        self.require_enabled()
        if self.role != "admin":
            raise PermissionError("需要管理员权限")

    def principal(self, project_id: str) -> Principal:
        self.require_enabled()
        return Principal(tenant_id=self.tenant_id, user_id=self.id, project_id=project_id)

    @field_validator("display_name")
    @classmethod
    def display_name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("显示名称不能为空")
        return value.strip()

    def revise(
        self,
        *,
        display_name: str | None = None,
        role: Literal["admin", "user"] | None = None,
        enabled: bool | None = None,
        password_hash: str | None = None,
    ) -> Self:
        """安全相关修改递增修订号，显示名称修改不影响已有会话。"""
        changes = {
            key: value
            for key, value in {
                "display_name": display_name,
                "role": role,
                "enabled": enabled,
                "password_hash": password_hash,
            }.items()
            if value is not None
        }
        data = self.model_dump()
        if any(
            key in changes and changes[key] != data[key]
            for key in ("password_hash", "role", "enabled")
        ):
            data["auth_revision"] = self.auth_revision + 1
        data.update(changes)
        return type(self).model_validate(data)
