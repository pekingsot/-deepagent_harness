from abc import ABC, abstractmethod

from pydantic import Field

from agent_platform.domain.common.models import RunContext, StrictModel


class SandboxHandle(StrictModel):
    id: str
    tenant_id: str
    run_id: str


class ExecutionRequest(StrictModel):
    argv: tuple[str, ...] = Field(min_length=1)
    timeout_seconds: int = Field(default=60, ge=1, le=600)


class ExecutionResult(StrictModel):
    exit_code: int
    stdout: str
    stderr: str


class SandboxProvider(ABC):
    @abstractmethod
    async def create(self, context: RunContext) -> SandboxHandle: ...

    @abstractmethod
    async def execute(
        self, context: RunContext, handle: SandboxHandle, command: ExecutionRequest,
    ) -> ExecutionResult: ...

    @abstractmethod
    async def destroy(self, context: RunContext, handle: SandboxHandle) -> None: ...
