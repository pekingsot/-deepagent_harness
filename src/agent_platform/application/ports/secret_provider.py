from abc import ABC, abstractmethod

from pydantic import SecretStr

from agent_platform.domain.common.models import Principal


class SecretProvider(ABC):
    @abstractmethod
    async def get(self, principal: Principal, name: str) -> SecretStr:
        raise NotImplementedError
