from uuid import UUID, uuid4

from pydantic import Field

from agent_platform.domain.types.common import Principal, StrictModel


class Session(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    owner: Principal
    agent_name: str
