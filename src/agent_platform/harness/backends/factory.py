from abc import ABC, abstractmethod
from pathlib import Path

from deepagents.backends.protocol import BackendProtocol

from agent_platform.domain.common.models import RunContext


class BackendFactory(ABC):
    @abstractmethod
    def create(self, context: RunContext, skills_directory: Path) -> BackendProtocol:
        """Enforce tenant scope; expose only explicitly authorized agent skills."""
        raise NotImplementedError
