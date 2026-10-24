from abc import ABC, abstractmethod

from agent_platform.domain.common.models import RunContext


class CheckpointNamespace(ABC):
    @abstractmethod
    def thread_key(self, context: RunContext) -> str:
        """Return a server-computed tenant/project/user/thread namespace."""
        raise NotImplementedError
