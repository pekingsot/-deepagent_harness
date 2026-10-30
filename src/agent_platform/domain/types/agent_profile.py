from pydantic import Field

from agent_platform.domain.types.common import Identifier, StrictModel


class AgentProfile(StrictModel):
    name: Identifier
    version: str = Field(default="1.0.0", min_length=1)
    enabled: bool = True
