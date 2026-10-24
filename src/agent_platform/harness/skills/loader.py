from abc import ABC, abstractmethod
from pathlib import Path

from agent_platform.domain.common.models import Identifier, RunContext, StrictModel


class SkillMetadata(StrictModel):
    name: Identifier
    description: str


class SkillLoader(ABC):
    @abstractmethod
    def load(self, context: RunContext, directory: Path) -> tuple[SkillMetadata, ...]:
        """Validate metadata, path containment and tenant authorization."""
        raise NotImplementedError
