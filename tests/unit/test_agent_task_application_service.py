"""离线验证任务编排和事务边界，不连接数据库、Redis 或模型。"""

import unittest
from contextlib import asynccontextmanager
from unittest.mock import create_autospec

from sqlalchemy_transactional.asyncio import current_session, sessionmaker_context
from sqlalchemy_transactional.common import SessionNotBoundError

from agent_platform.application.dto.agent_task_dto import (
    AgentTaskExecutionResult,
    CreateAgentTask,
    ResumeAgentTask,
    TextReply,
)
from agent_platform.application.interfaces.agent_task_runtime import AgentTaskRuntime
from agent_platform.application.interfaces.task_events import TaskEvents
from agent_platform.application.interfaces.job_queue import JobQueue
from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)
from agent_platform.domain.aggregates.agent_task import AgentTask, AgentTaskStatus
from agent_platform.domain.repositories.agent_task_repository import AgentTaskRepository
from agent_platform.domain.services.agent_task_domain_service import AgentTaskDomainService
from agent_platform.domain.types.common import ConflictError, NotFoundError, Principal, TaskContext


class RecordingSession:
    """只记录事务退出结果，不执行数据库操作。"""

    def __init__(self, events: list[str]) -> None:
        self.events = events  # 当前测试的事务与业务调用记录

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    @asynccontextmanager
    async def begin(self):
        try:
            yield
        except BaseException:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")


class AgentTaskApplicationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.events = []  # 事务与业务操作的执行顺序
        self.repository = create_autospec(AgentTaskRepository, instance=True)  # 离线仓储
        self.queue = create_autospec(JobQueue, instance=True)  # 离线队列
        self.runtime = create_autospec(AgentTaskRuntime, instance=True)  # 离线执行器
        self.principal = Principal(tenant_id=1, user_id=2, project_id="test")  # 测试身份
        self.task = AgentTask(
            context=TaskContext(tenant_id=1, user_id=2, project_id="test"),
            prompt="制定开发计划",
        )  # 待执行任务
        self.service = AgentTaskApplicationService(
            tasks=AgentTaskDomainService(self.repository), queue=self.queue, runtime=self.runtime,
            events=create_autospec(TaskEvents, instance=True),
        )  # 被测应用服务
        await self.enterAsyncContext(sessionmaker_context(lambda: RecordingSession(self.events)))

    async def test_create_commits_before_enqueue(self) -> None:
        async def save(principal, task):
            current_session()
            self.events.append("save")

        async def enqueue(context):
            with self.assertRaises(SessionNotBoundError):
                current_session()
            self.events.append("enqueue")
            return "message-1"

        self.repository.save.side_effect = save
        self.queue.enqueue.side_effect = enqueue
        task = await self.service.create(self.principal, CreateAgentTask(prompt="制定计划"))
        self.assertEqual(self.events, ["save", "commit", "enqueue"])
        self.assertEqual(task.status, AgentTaskStatus.QUEUED)
        self.queue.enqueue.assert_awaited_once_with(task.context)

    async def test_execute_releases_transaction_before_model_call(self) -> None:
        self.repository.get.return_value = self.task

        async def execute(task, *, on_text=None):
            with self.assertRaises(SessionNotBoundError):
                current_session()
            return AgentTaskExecutionResult(status="completed", output="计划完成")

        self.runtime.execute.side_effect = execute
        result = await self.service.execute(self.principal, self.task.id)
        self.assertEqual(result.status, AgentTaskStatus.SUCCEEDED)
        self.assertEqual(result.result, "计划完成")
        saved = [call.args[1].status for call in self.repository.save.await_args_list]
        self.assertEqual(saved, [AgentTaskStatus.RUNNING, AgentTaskStatus.SUCCEEDED])

    async def test_runtime_failure_is_saved(self) -> None:
        self.repository.get.return_value = self.task
        self.runtime.execute.side_effect = RuntimeError("模型服务不可用")
        result = await self.service.execute(self.principal, self.task.id)
        self.assertEqual(result.status, AgentTaskStatus.FAILED)
        self.assertEqual(result.error, "Agent 执行失败，请联系管理员查看日志")

    async def test_start_reads_and_writes_with_same_session(self) -> None:
        sessions = []  # 领取阶段和结束阶段实际使用的会话

        async def get(principal, task_id):
            sessions.append(current_session())
            return self.task

        async def save(principal, task):
            sessions.append(current_session())

        self.repository.get.side_effect = get
        self.repository.save.side_effect = save
        self.runtime.execute.return_value = AgentTaskExecutionResult(
            status="completed", output="计划完成"
        )
        await self.service.execute(self.principal, self.task.id)
        self.assertEqual(len(sessions), 3)
        self.assertIs(sessions[0], sessions[1])
        self.assertIsNot(sessions[1], sessions[2])

    async def test_invalid_result_is_recorded_after_result_transaction_rolls_back(self) -> None:
        self.repository.get.return_value = self.task
        self.runtime.execute.return_value = AgentTaskExecutionResult(status="completed", output=" ")
        result = await self.service.execute(self.principal, self.task.id)
        self.assertEqual(result.status, AgentTaskStatus.FAILED)
        self.assertEqual(self.events, ["commit", "rollback", "commit"])

    async def test_missing_task_rolls_back(self) -> None:
        self.repository.get.return_value = None
        with self.assertRaises(NotFoundError):
            await self.service.get(self.principal, self.task.id)
        self.assertEqual(self.events, ["rollback"])

    async def test_cancel_does_not_claim_to_stop_running_task(self) -> None:
        self.repository.get.return_value = self.task.start()
        with self.assertRaises(ConflictError):
            await self.service.cancel(self.principal, self.task.id)
        self.repository.save.assert_not_awaited()

    async def test_resume_saves_result(self) -> None:
        self.repository.get.return_value = self.task.start().wait_for_user()
        self.runtime.resume.return_value = AgentTaskExecutionResult(
            status="completed", output="恢复完成"
        )
        command = ResumeAgentTask(answers={"interrupt-1": TextReply(answer="继续")})
        result = await self.service.resume(self.principal, self.task.id, command)
        self.assertEqual(result.status, AgentTaskStatus.SUCCEEDED)
        self.assertEqual(result.attempt, 1)
