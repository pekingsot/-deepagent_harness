from abc import ABC, abstractmethod
from uuid import UUID

from pydantic import Field

from agent_platform.domain.types.common import StrictModel, TaskContext


class SandboxHandle(StrictModel):
    id: str  # 沙箱提供者分配的资源标识
    tenant_id: int = Field(gt=0, le=9223372036854775807)  # 与当前身份一致的租户编号
    task_id: UUID  # 分配该沙箱的任务编号


class ExecutionRequest(StrictModel):
    argv: tuple[str, ...] = Field(min_length=1)
    timeout_seconds: int = Field(default=60, ge=1, le=600)


class ExecutionResult(StrictModel):
    exit_code: int
    stdout: str
    stderr: str


class SandboxProvider(ABC):
    @abstractmethod
    async def create(self, context: TaskContext) -> SandboxHandle: ...

    @abstractmethod
    async def execute(
        self,
        context: TaskContext,
        handle: SandboxHandle,
        command: ExecutionRequest,
    ) -> ExecutionResult: ...

    @abstractmethod
    async def destroy(self, context: TaskContext, handle: SandboxHandle) -> None: ...
