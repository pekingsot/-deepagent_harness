from abc import ABC, abstractmethod

from agent_platform.domain.runs.models import Run


class AgentRuntime(ABC):
    @abstractmethod
    async def execute(self, run: Run) -> str: ...
