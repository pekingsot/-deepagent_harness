"""账号操作参数，集中验证合法的字段和值。"""

from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator

from agent_platform.domain.types.common import StrictModel

type AccountName = Annotated[
    str, Field(min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
]
type DisplayName = Annotated[str, Field(min_length=1, max_length=80)]


class LoginCommand(StrictModel):
    username: AccountName  # 登录名，统一小写
    password: SecretStr = Field(min_length=1, max_length=128)  # 原始密码，不记录日志


class CreateUserCommand(StrictModel):
    username: AccountName  # 全系统唯一的登录名
    display_name: DisplayName  # 页面显示名称
    password: SecretStr = Field(min_length=12, max_length=128)  # 初始密码
    role: Literal["admin", "user"] = "user"  # 新账号角色

    @field_validator("display_name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("显示名称不能为空")
        return value.strip()


class UpdateUserCommand(StrictModel):
    display_name: DisplayName | None = None  # 不传表示不修改
    role: Literal["admin", "user"] | None = None  # 新角色
    enabled: bool | None = None  # 启停状态

    @field_validator("display_name")
    @classmethod
    def name_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("显示名称不能为空")
        return value.strip() if value is not None else None


class ResetPasswordCommand(StrictModel):
    password: SecretStr = Field(min_length=12, max_length=128)  # 新密码


class ChangePasswordCommand(StrictModel):
    current_password: SecretStr = Field(min_length=1, max_length=128)  # 旧密码
    new_password: SecretStr = Field(min_length=12, max_length=128)  # 新密码
