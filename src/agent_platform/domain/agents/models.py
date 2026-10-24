from agent_platform.domain.common.models import Identifier, StrictModel


class AgentProfile(StrictModel):
    name: Identifier
    version: str = "1.0.0"
    model_profile: str
    backend_profile: str = "state"
    subagents: tuple[str, ...] = ()
    skill_sources: tuple[str, ...] = ()
