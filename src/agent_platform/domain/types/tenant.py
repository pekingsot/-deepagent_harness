from pydantic import Field

from agent_platform.domain.types.common import StrictModel


class Tenant(StrictModel):
    id: int = Field(gt=0, le=9223372036854775807)  # 与登录身份一致的租户编号
    name: str  # 租户名称
    enabled: bool = True  # 是否允许租户使用系统
