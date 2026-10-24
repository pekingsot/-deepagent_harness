from agent_platform.domain.common.models import Identifier, StrictModel


class ToolPolicy(StrictModel):
    name: Identifier
    enabled: bool = False
    approval_required: bool = True
