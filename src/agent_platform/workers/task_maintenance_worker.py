"""定期协调异常执行补偿和删除重试，生命周期入口只负责启停。"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy_transactional.asyncio import sessionmaker_context

from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)

logger = logging.getLogger(__name__)


class TaskMaintenanceWorker:
    def __init__(
        self,
        *,
        service: AgentTaskApplicationService,
        session_factory: async_sessionmaker[AsyncSession],
        interval: float = 15,
    ) -> None:
        self._service = service
        self._session_factory = session_factory
        self._interval = interval

    async def consume(self, stop_event: asyncio.Event) -> None:
        async with sessionmaker_context(self._session_factory):
            while not stop_event.is_set():
                for operation in (
                    self._service.recover_orphans,
                    self._service.cleanup_pending_deletions,
                ):
                    try:
                        await operation()
                    except Exception:
                        logger.exception("Task maintenance failed; will retry")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=self._interval)
                except TimeoutError:
                    pass
