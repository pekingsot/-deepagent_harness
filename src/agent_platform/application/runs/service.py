from abc import ABC, abstractmethod
from uuid import UUID

from agent_platform.domain.common.models import Principal
from agent_platform.domain.runs.models import CreateRun, Run


class RunService(ABC):
    @abstractmethod
    async def create(self, principal: Principal, command: CreateRun) -> Run:
        raise NotImplementedError

    @abstractmethod
    async def get(self, principal: Principal, run_id: UUID) -> Run:
        raise NotImplementedError

    @abstractmethod
    async def cancel(self, principal: Principal, run_id: UUID) -> Run:
        raise NotImplementedError

    @abstractmethod
    async def resume(self, principal: Principal, run_id: UUID) -> Run:
        raise NotImplementedError
