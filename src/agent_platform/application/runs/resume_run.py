from abc import ABC, abstractmethod
from uuid import UUID

from agent_platform.domain.common.models import Principal
from agent_platform.domain.runs.models import Run


class ResumeRunUseCase(ABC):
    @abstractmethod
    async def execute(self, principal: Principal, run_id: UUID) -> Run:
        raise NotImplementedError
