from abc import ABC, abstractmethod

from agent_platform.domain.common.models import Principal
from agent_platform.domain.runs.models import CreateRun, Run


class CreateRunUseCase(ABC):
    @abstractmethod
    async def execute(self, principal: Principal, command: CreateRun) -> Run:
        raise NotImplementedError
