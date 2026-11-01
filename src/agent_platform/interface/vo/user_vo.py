"""认证接口参数；复用应用命令的字段校验。"""

from pydantic import Field

from agent_platform.application.dto.authentication_dto import CurrentUser
from agent_platform.application.dto.user_command import (
    ChangePasswordCommand,
    CreateUserCommand,
    LoginCommand,
    ResetPasswordCommand,
    UpdateUserCommand,
)
from agent_platform.domain.types.common import StrictModel


class LoginResponse(StrictModel):
    access_token: str = Field(repr=False)  # 只交给服务端代理写入 HttpOnly Cookie
    expires_in: int = Field(gt=0)  # 会话绝对有效秒数
    user: CurrentUser  # 可以向浏览器展示的安全用户信息


class LoginRequest(LoginCommand):
    """登录请求。"""


class CreateUserRequest(CreateUserCommand):
    """管理员创建用户。"""


class UpdateUserRequest(UpdateUserCommand):
    """修改名称、角色和启用状态。"""


class ResetPasswordRequest(ResetPasswordCommand):
    """管理员重置密码。"""


class ChangePasswordRequest(ChangePasswordCommand):
    """本人修改密码。"""
