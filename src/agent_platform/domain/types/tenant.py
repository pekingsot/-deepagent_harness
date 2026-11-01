"""租户信息：当前只提供账号隔离，不引入组织树。"""

from pydantic import Field

from agent_platform.domain.types.common import Identifier, StrictModel


class Tenant(StrictModel):
    id: int = Field(gt=0, le=9223372036854775807)  # 整数租户主键
    code: str  # 登录时使用的公司代码
    name: str  # 公司名称
    enabled: bool  # 租户是否可用
    default_project_id: Identifier  # 当前默认工作空间
