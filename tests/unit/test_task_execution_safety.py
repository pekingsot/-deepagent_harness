"""执行权、迟到回写、分页公平性和删除事务边界的回归场景。"""

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from sqlalchemy_transactional.asyncio import current_session, sessionmaker_context
from sqlalchemy_transactional.common import SessionNotBoundError
from test_running_task_cancellation import (
    OfflineExecutionGuard,
    OfflineQueue,
    OfflineRepository,
    OfflineSession,
)

from agent_platform.application.dto.agent_task_dto import (
    AgentTaskExecutionResult,
    CreateAgentTask,
    ResumeAgentTask,
    TextReply,
)
from agent_platform.application.interfaces.task_execution_guard import ExecutionOwnershipLost
from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)
from agent_platform.domain.aggregates.agent_task import AgentTask, AgentTaskStatus
from agent_platform.domain.services.agent_task_domain_service import AgentTaskDomainService
from agent_platform.domain.types.common import ConflictError, Principal, TaskContext
from agent_platform.infrastructure.persistence.task_execution_guard import (
    PostgresTaskExecutionGuard,
)


class TaskExecutionSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await self.enterAsyncContext(sessionmaker_context(OfflineSession))
        self.repository = OfflineRepository()
        self.events = AsyncMock()
        self.cleaner = AsyncMock()
        self.principal = Principal(tenant_id=1, user_id=2, project_id="test")
        self.domain = AgentTaskDomainService(self.repository)
        self.service = AgentTaskApplicationService(
            tasks=self.domain,
            queue=OfflineQueue(),
            runtime=AsyncMock(),
            events=self.events,
            cleaner=self.cleaner,
            execution_guard=OfflineExecutionGuard(),
        )

    async def test_old_resume_cannot_write_into_new_resume_of_same_attempt(self):
        task = await self.service.create(self.principal, CreateAgentTask(prompt="test"))
        old, _ = await self.service._claim_task(self.principal, task.id)
        current = old.wait_for_user().resume()
        self.repository.tasks[task.id] = current
        result = AgentTaskExecutionResult(status="completed", output="late")
        with self.assertRaises(ConflictError):
            await self.service._finish_task(self.principal, old, result)
        with self.assertRaises(ConflictError):
            await self.service._fail_task(self.principal, old, "late error")
        with self.assertRaises(ConflictError):
            await self.service._finish_resume(
                self.principal,
                old,
                ResumeAgentTask(answers={"interrupt": TextReply(answer="late answer")}),
                result,
            )
        self.repository.tasks[task.id] = current.cancel()
        with self.assertRaises(ConflictError):
            await self.service.complete_cancellation(
                self.principal,
                task.id,
                attempt=old.attempt,
                execution_id=old.execution_id,
            )

    async def test_text_fragments_do_not_open_business_transactions(self):
        task = AgentTask(context=TaskContext(**self.principal.model_dump()), prompt="test").start()
        with patch.object(self.domain, "get", new=AsyncMock(side_effect=AssertionError("DB read"))):
            for _ in range(100):
                await self.service._publish(task, "text_delta", {"text": "x"})
        self.assertEqual(self.events.publish.await_count, 100)

    async def test_external_cleanup_runs_without_transaction_and_retry_retains_intent(self):
        task = await self.service.create(self.principal, CreateAgentTask(prompt="test"))
        await self.service.request_deletion(self.principal, task.id)

        async def cleanup(task):
            with self.assertRaises(SessionNotBoundError):
                current_session()
            raise RuntimeError("storage unavailable")

        self.cleaner.cleanup.side_effect = cleanup
        await self.service.cleanup_pending_deletions()
        self.assertTrue(self.repository.tasks[task.id].deletion_requested)
        self.cleaner.cleanup.side_effect = None
        await self.service.cleanup_pending_deletions()
        self.assertNotIn(task.id, self.repository.tasks)

    async def test_get_is_readonly_and_open_task_explicitly_repairs(self):
        task = await self.service.create(self.principal, CreateAgentTask(prompt="test"))
        running, _ = await self.service._claim_task(self.principal, task.id)
        old = running.model_copy(update={"updated_at": datetime.now(UTC) - timedelta(minutes=5)})
        self.repository.tasks[old.id] = old
        self.assertEqual(
            (await self.service.get(self.principal, old.id)).status, AgentTaskStatus.RUNNING
        )
        self.assertEqual(
            (await self.service.open_task(self.principal, old.id)).status, AgentTaskStatus.FAILED
        )

    async def test_maintenance_advances_past_first_fifty_live_tasks(self):
        visited = []
        for value in range(1, 52):
            task = AgentTask(
                context=TaskContext(**self.principal.model_dump(), task_id=UUID(int=value)),
                prompt="test",
            ).start()
            self.repository.tasks[task.id] = task

        async def reconcile(task):
            visited.append(task.id)

        with patch.object(self.service, "reconcile", side_effect=reconcile):
            await self.service.recover_orphans()
            await self.service.recover_orphans()
        self.assertEqual(visited, [UUID(int=value) for value in range(1, 52)])


class ExecutionConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_lost_connection_cancels_owner_and_rejects_result(self):
        connection = AsyncMock()
        connection.invalidated = False
        connection.scalar.return_value = True
        connection.execute.side_effect = OSError("connection lost")
        engine = MagicMock()
        engine.connect.return_value.__aenter__ = AsyncMock(return_value=connection)
        engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
        guard = PostgresTaskExecutionGuard(engine, probe_interval=0.001)
        stopped = asyncio.Event()

        async def run():
            async with guard.acquire(uuid4()) as owned:
                self.assertTrue(owned)
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

        with self.assertRaises(ExecutionOwnershipLost):
            await asyncio.wait_for(asyncio.create_task(run()), timeout=2)
        self.assertTrue(stopped.is_set())
        connection.invalidate.assert_awaited_once()
