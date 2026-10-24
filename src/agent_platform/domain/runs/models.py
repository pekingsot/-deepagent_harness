from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field

from agent_platform.domain.common.models import Identifier, RunContext, StrictModel


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CreateRun(StrictModel):
    agent: Identifier = "orchestrator"
    prompt: Annotated[str, Field(min_length=1, max_length=32000)]


class Run(StrictModel):
    context: RunContext
    agent: Identifier
    prompt: str
    status: RunStatus = RunStatus.QUEUED
    result: str | None = None
    error: str | None = None
    attempt: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JobLease(StrictModel):
    run: Run
    owner: str
