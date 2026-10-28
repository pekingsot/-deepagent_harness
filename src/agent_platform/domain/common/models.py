from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

type Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, validate_default=True)


class Principal(StrictModel):
    tenant_id: Annotated[int, Field(gt=0, le=9223372036854775807)]
    user_id: Annotated[int, Field(gt=0, le=9223372036854775807)]
    project_id: Identifier


class RunContext(Principal):
    run_id: UUID = Field(default_factory=uuid4)
    thread_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID = Field(default_factory=uuid4)



class NotFoundError(Exception):
    """Unknown and inaccessible resources have the same response."""


class ConflictError(Exception):
    """Illegal transition or concurrent modification."""
