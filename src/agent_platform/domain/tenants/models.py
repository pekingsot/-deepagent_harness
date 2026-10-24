from agent_platform.domain.common.models import Identifier, StrictModel


class Tenant(StrictModel):
    id: Identifier
    name: str
    enabled: bool = True
