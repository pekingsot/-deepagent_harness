from abc import ABC, abstractmethod
from uuid import UUID

from agent_platform.application.dto.runs import (
    CreateRun,
    ResumeRun,
    RuntimeResult,
)
from agent_platform.domain.common.models import Principal
from agent_platform.domain.runs.models import Run


class RunService(ABC):
    @abstractmethod
    async def create(
        self,
        principal: Principal,
        command: CreateRun,
    ) -> Run:
        raise NotImplementedError

    @abstractmethod
    async def execute(
        self,
        principal: Principal,
        run_id: UUID,
    ) -> Run:
        raise NotImplementedError

    @abstractmethod
    async def get(
        self,
        principal: Principal,
        run_id: UUID,
    ) -> Run:
        raise NotImplementedError

    @abstractmethod
    async def get_execution_state(
        self,
        principal: Principal,
        run_id: UUID,
    ) -> RuntimeResult:
        raise NotImplementedError

    @abstractmethod
    async def resume(
        self,
        principal: Principal,
        run_id: UUID,
        command: ResumeRun,
    ) -> Run:
        raise NotImplementedError

    @abstractmethod
    async def cancel(
        self,
        principal: Principal,
        run_id: UUID,
    ) -> Run:
        raise NotImplementedError