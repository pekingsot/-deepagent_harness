from datetime import UTC, datetime
from enum import StrEnum

from pydantic import Field

from agent_platform.domain.common.models import (
    ConflictError,
    Identifier,
    RunContext,
    StrictModel,
)


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({
        RunStatus.RUNNING,
        RunStatus.CANCELLED,
    }),
    RunStatus.RUNNING: frozenset({
        RunStatus.WAITING_HUMAN,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }),
    RunStatus.WAITING_HUMAN: frozenset({
        RunStatus.RUNNING,
        RunStatus.CANCELLED,
    }),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


class Run(StrictModel):
    context: RunContext
    agent: Identifier
    prompt: str = Field(min_length=1, max_length=32000)

    status: RunStatus = RunStatus.QUEUED
    result: str | None = None
    error: str | None = None

    attempt: int = Field(default=0, ge=0)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )

    def transition(
        self,
        target: RunStatus,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> "Run":
        if target not in _TRANSITIONS[self.status]:
            raise ConflictError(
                f"不允许从 {self.status} 转换为 {target}"
            )

        if target == RunStatus.FAILED and not error:
            raise ValueError("失败状态必须提供错误说明")

        if result is not None and target != RunStatus.SUCCEEDED:
            raise ValueError("只有成功状态可以保存最终结果")

        if error is not None and target != RunStatus.FAILED:
            raise ValueError("只有失败状态可以保存错误说明")

        data = self.model_dump()
        data.update(
            status=target,
            result=result,
            error=error,
            updated_at=datetime.now(UTC),
        )

        return type(self).model_validate(data)


class JobLease(StrictModel):
    run: Run
    owner: str