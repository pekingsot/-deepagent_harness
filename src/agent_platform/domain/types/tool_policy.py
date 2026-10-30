from agent_platform.domain.types.common import Identifier, StrictModel


class ToolPolicy(StrictModel):
    name: Identifier
    enabled: bool = False
    approval_required: bool = True
