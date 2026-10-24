from agent_platform.domain.common.models import Identifier, StrictModel


class SkillBinding(StrictModel):
    name: Identifier
    version: str
    source: str
    tenant_id: Identifier | None = None
