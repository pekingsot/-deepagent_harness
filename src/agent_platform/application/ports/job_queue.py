from abc import ABC, abstractmethod

from agent_platform.domain.common.models import RunContext


class JobQueue(ABC):
    @abstractmethod
    async def enqueue(self, context: RunContext) -> str:
        raise NotImplementedError

    @abstractmethod
    async def cancel(self, context: RunContext, job_id: str) -> None:
        raise NotImplementedError
