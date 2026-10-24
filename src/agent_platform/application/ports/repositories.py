from abc import ABC, abstractmethod
from uuid import UUID

from agent_platform.domain.common.models import Principal
from agent_platform.domain.runs.models import Run


class RunRepository(ABC):
    @abstractmethod
    async def save(self, principal: Principal, run: Run) -> None:
        """Persist a run after verifying its tenant/project/user ownership."""
        raise NotImplementedError

    @abstractmethod
    async def get(self, principal: Principal, run_id: UUID) -> Run | None:
        """Every query must include the trusted tenant boundary."""
        raise NotImplementedError
