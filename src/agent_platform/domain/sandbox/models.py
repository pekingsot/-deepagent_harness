from agent_platform.domain.common.models import RunContext, StrictModel


class Sandbox(StrictModel):
    id: str
    context: RunContext
    provider: str
