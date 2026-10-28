from abc import ABC, abstractmethod

from agent_platform.application.dto.runs import (
    ResumeRun,
    RuntimeResult,
)
from agent_platform.domain.runs.models import Run


class AgentRuntime(ABC):
    @abstractmethod
    async def execute(self, run: Run) -> RuntimeResult:
        raise NotImplementedError

    @abstractmethod
    async def get_state(self, run: Run) -> RuntimeResult:
        raise NotImplementedError

    @abstractmethod
    async def resume(
        self,
        run: Run,
        command: ResumeRun,
    ) -> RuntimeResult:
        raise NotImplementedError