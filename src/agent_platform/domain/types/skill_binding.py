from pydantic import Field

from agent_platform.domain.types.common import Identifier, StrictModel


class SkillBinding(StrictModel):
    name: Identifier
    version: str
    source: str
    tenant_id: int | None = Field(default=None, gt=0, le=9223372036854775807)  # 空值表示非租户专属
