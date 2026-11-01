"""验证事务边界，使用确定的离线仓储与执行器。"""

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, create_autospec

from sqlalchemy_transactional.asyncio import current_session, sessionmaker_context
from sqlalchemy_transactional.common import SessionNotBoundError
from test_running_task_cancellation import OfflineExecutionGuard, OfflineQueue, OfflineRepository

from agent_platform.application.dto.agent_task_dto import (
    AgentTaskExecutionResult,
    CreateAgentTask,
    ResumeAgentTask,
    TextReply,
)
from agent_platform.application.interfaces.agent_task_runtime import AgentTaskRuntime
from agent_platform.application.interfaces.task_events import TaskEvents
from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)
from agent_platform.domain.aggregates.agent_task import AgentTaskStatus
from agent_platform.domain.services.agent_task_domain_service import AgentTaskDomainService
from agent_platform.domain.types.common import NotFoundError, Principal


class AgentTaskApplicationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transactions = []
        transactions = self.transactions

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            @asynccontextmanager
            async def begin(self):
                try:
                    yield
                except BaseException:
                    transactions.append("rollback")
                    raise
                else:
                    transactions.append("commit")

        await self.enterAsyncContext(sessionmaker_context(Session))
        self.repository = OfflineRepository()
        self.queue = OfflineQueue()
        self.runtime = create_autospec(AgentTaskRuntime, instance=True)
        self.runtime.execute.return_value = AgentTaskExecutionResult(
            status="completed", output="完成"
        )
        self.principal = Principal(tenant_id=1, user_id=2, project_id="test")
        self.service = AgentTaskApplicationService(
            tasks=AgentTaskDomainService(self.repository),
            queue=self.queue,
            runtime=self.runtime,
            events=create_autospec(TaskEvents, instance=True),
            execution_guard=OfflineExecutionGuard(),
        )
        self.task = await self.service.create(self.principal, CreateAgentTask(prompt="制定计划"))
        self.transactions.clear()

    async def test_create_commits_before_enqueue(self):
        async def enqueue(context, **kwargs):
            self.assertIn(context.task_id, self.repository.tasks)
            self.assertIn("commit", self.transactions)
            return "1-0"

        self.queue.enqueue = AsyncMock(side_effect=enqueue)
        await self.service.create(self.principal, CreateAgentTask(prompt="新任务"))
        self.queue.enqueue.assert_awaited_once()

    async def test_execute_releases_transaction_before_model_call(self):
        async def execute(task, **kwargs):
            with self.assertRaises(SessionNotBoundError):
                current_session()
            return AgentTaskExecutionResult(status="completed", output="完成")

        self.runtime.execute.side_effect = execute
        result = await self.service.execute(self.principal, self.task.id)
        self.assertEqual(result.status, AgentTaskStatus.SUCCEEDED)

    async def test_runtime_failure_is_saved(self):
        self.runtime.execute.side_effect = RuntimeError("model unavailable")
        result = await self.service.execute(self.principal, self.task.id)
        self.assertEqual(result.status, AgentTaskStatus.FAILED)
        self.assertTrue(result.error)

    async def test_claim_reads_and_writes_in_one_session(self):
        sessions = []
        original_get = self.repository.get
        original_save = self.repository.save

        async def get(*args, **kwargs):
            sessions.append(current_session())
            return await original_get(*args, **kwargs)

        async def save(*args, **kwargs):
            sessions.append(current_session())
            return await original_save(*args, **kwargs)

        self.repository.get = get
        self.repository.save = save
        await self.service._claim_task(self.principal, self.task.id)
        self.assertEqual(len(sessions), 2)
        self.assertIs(sessions[0], sessions[1])

    async def test_invalid_result_rolls_back_before_recording_failure(self):
        self.runtime.execute.return_value = AgentTaskExecutionResult(status="completed", output=" ")
        result = await self.service.execute(self.principal, self.task.id)
        self.assertEqual(result.status, AgentTaskStatus.FAILED)
        rollback = self.transactions.index("rollback")
        self.assertIn("commit", self.transactions[rollback + 1 :])

    async def test_missing_task_rolls_back(self):
        del self.repository.tasks[self.task.id]
        with self.assertRaises(NotFoundError):
            await self.service.get(self.principal, self.task.id)
        self.assertEqual(self.transactions, ["rollback"])

    async def test_cancel_running_task_waits_for_executor_confirmation(self):
        await self.service._claim_task(self.principal, self.task.id)
        task = await self.service.cancel(self.principal, self.task.id)
        self.assertEqual(task.status, AgentTaskStatus.CANCELLING)

    async def test_resume_has_new_execution_identity_without_new_attempt(self):
        running, _ = await self.service._claim_task(self.principal, self.task.id)
        self.repository.tasks[running.id] = running.wait_for_user()
        self.runtime.resume.return_value = AgentTaskExecutionResult(
            status="completed", output="恢复完成"
        )
        result = await self.service.resume(
            self.principal,
            running.id,
            ResumeAgentTask(answers={"interrupt": TextReply(answer="继续")}),
        )
        self.assertEqual(result.status, AgentTaskStatus.SUCCEEDED)
        self.assertEqual(result.attempt, running.attempt)
        self.assertNotEqual(result.execution_id, running.execution_id)
