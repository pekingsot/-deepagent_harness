"""会话删除的离线验证，不连接数据库、Redis 或模型。"""

import asyncio
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, create_autospec
from uuid import uuid4

from sqlalchemy_transactional.asyncio import sessionmaker_context
from test_running_task_cancellation import (
    BlockingRuntime,
    OfflineExecutionGuard,
    OfflineQueue,
    OfflineRepository,
    OfflineSession,
)

from agent_platform.application.dto.agent_task_dto import CreateAgentTask, TaskJob
from agent_platform.application.interfaces.task_events import TaskEvents
from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)
from agent_platform.domain.aggregates.agent_task import AgentTaskStatus
from agent_platform.domain.services.agent_task_domain_service import AgentTaskDomainService
from agent_platform.domain.types.common import ConflictError, NotFoundError, Principal
from agent_platform.workers.agent_task_worker import AgentTaskWorker


class TaskDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repository = OfflineRepository()
        self.cleaner = AsyncMock()
        self.events = create_autospec(TaskEvents, instance=True)
        self.runtime = BlockingRuntime()
        self.queue = OfflineQueue()
        self.principal = Principal(tenant_id=2, user_id=3, project_id="default")
        self.service = AgentTaskApplicationService(
            execution_guard=OfflineExecutionGuard(),
            tasks=AgentTaskDomainService(self.repository),
            queue=self.queue,
            runtime=self.runtime,
            events=self.events,
            cleaner=self.cleaner,
        )
        await self.enterAsyncContext(sessionmaker_context(OfflineSession))

    async def create(self):
        return await self.service.create(self.principal, CreateAgentTask(prompt="测试删除"))

    async def test_orphan_running_and_cancelling_are_repaired_but_live_execution_is_not(self):
        class Guard:
            busy = False

            @asynccontextmanager
            async def acquire(self, task_id):
                yield not self.busy

        guard = Guard()
        self.service._execution_guard = guard
        for cancelling in (False, True):
            task = await self.create()
            task, _ = await self.service._claim_task(self.principal, task.id)
            if cancelling:
                task = task.cancel()
            task = task.model_copy(update={"updated_at": datetime.now(UTC) - timedelta(minutes=5)})
            self.repository.tasks[task.id] = task
            guard.busy = True
            self.assertEqual(
                (await self.service.open_task(self.principal, task.id)).status, task.status
            )
            guard.busy = False
            repaired = await self.service.open_task(self.principal, task.id)
            self.assertEqual(
                repaired.status,
                AgentTaskStatus.CANCELLED if cancelling else AgentTaskStatus.FAILED,
            )

    async def test_accept_delete_returns_before_cleanup_and_retries_in_background(self):
        task = await self.create()
        await self.service.request_deletion(self.principal, task.id)
        self.cleaner.cleanup.assert_not_awaited()
        self.assertTrue(self.repository.tasks[task.id].deletion_requested)
        self.cleaner.cleanup.side_effect = RuntimeError("暂时无法清理")
        await self.service.cleanup_pending_deletions()
        self.assertIn(task.id, self.repository.tasks)
        self.cleaner.cleanup.side_effect = None
        await self.service.cleanup_pending_deletions()
        self.assertNotIn(task.id, self.repository.tasks)

    async def test_delete_failure_preserves_intent_and_retry_succeeds(self):
        task = await self.create()
        other = await self.create()
        self.cleaner.cleanup.side_effect = RuntimeError("Redis 暂不可用")
        with self.assertRaises(RuntimeError):
            await self.service.delete(self.principal, task.id)
        self.assertTrue(self.repository.tasks[task.id].deletion_requested)
        with self.assertRaises(ConflictError):
            await self.service.send_message(self.principal, task.id, uuid4(), "新要求")
        self.cleaner.cleanup.side_effect = None
        await self.service.delete(self.principal, task.id)
        self.assertNotIn(task.id, self.repository.tasks)
        self.assertNotIn(task.id, self.repository.history)
        self.assertIn(other.id, self.repository.tasks)

    async def test_wrong_tenant_never_cleans_data(self):
        task = await self.create()
        outsider = Principal(tenant_id=3, user_id=3, project_id="default")
        with self.assertRaises(NotFoundError):
            await self.service.delete(outsider, task.id)
        self.cleaner.cleanup.assert_not_awaited()

    async def test_running_delete_waits_for_runtime_exit(self):
        task = await self.create()
        worker = AgentTaskWorker(
            session_factory=OfflineSession,
            queue=self.queue,
            service=self.service,
            authentication=AsyncMock(),
        )
        execution = asyncio.create_task(worker._execute_job(TaskJob(context=task.context)))
        try:
            await asyncio.wait_for(self.runtime.started.wait(), timeout=2)
            await self.service.delete(self.principal, task.id)
            await execution
            self.assertTrue(self.runtime.closed.is_set())
            self.assertNotIn(task.id, self.repository.tasks)
            self.events.publish.reset_mock()
            await self.service._publish(task, "completed", {"text": "迟到"})
            self.events.publish.assert_not_awaited()
            await self.service._enqueue(task.context)
        finally:
            if not execution.done():
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)

    async def test_cannot_purge_before_cancellation_confirmed(self):
        task = await self.create()
        await self.service._claim_task(self.principal, task.id)
        await self.service._request_deletion(self.principal, task.id)
        with self.assertRaises(ConflictError):
            await self.service._purge_task(self.principal, task.id)
        self.cleaner.cleanup.assert_not_awaited()
