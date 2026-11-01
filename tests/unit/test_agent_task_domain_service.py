"""验证任务领域规则，不依赖事务组件、数据库或 Agent 框架。"""

import unittest
from unittest.mock import create_autospec

from agent_platform.domain.aggregates.agent_task import AgentTask, AgentTaskStatus
from agent_platform.domain.repositories.agent_task_repository import AgentTaskRepository
from agent_platform.domain.services.agent_task_domain_service import AgentTaskDomainService
from agent_platform.domain.types.common import ConflictError, NotFoundError, Principal, TaskContext


class AgentTaskDomainServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.repository = create_autospec(AgentTaskRepository, instance=True)  # 离线仓储
        self.service = AgentTaskDomainService(self.repository)  # 被测领域服务
        self.principal = Principal(tenant_id=1, user_id=2, project_id="test")  # 测试身份
        self.task = AgentTask(
            context=TaskContext(tenant_id=1, user_id=2, project_id="test"), prompt="制定计划"
        )  # 测试任务

    async def test_create_assigns_owner_and_initial_state(self) -> None:
        task = await self.service.create(self.principal, agent="task_planning", prompt="制定计划")
        self.assertEqual(task.status, AgentTaskStatus.QUEUED)
        self.assertEqual(task.attempt, 0)
        self.assertEqual(task.context.user_id, self.principal.user_id)
        self.repository.save.assert_awaited_once_with(self.principal, task)

    async def test_start_rejects_already_running_task(self) -> None:
        self.repository.get.return_value = self.task.start()
        with self.assertRaises(ConflictError):
            await self.service.start(self.principal, self.task.id)
        self.repository.save.assert_not_awaited()

    async def test_cancel_rule_also_applies_when_domain_is_called_directly(self) -> None:
        self.repository.get.return_value = self.task.start()
        requested = await self.service.cancel(self.principal, self.task.id)
        self.assertEqual(requested.status, AgentTaskStatus.CANCELLING)
        self.assertEqual(self.task.start().cancel().status, AgentTaskStatus.CANCELLING)
        self.repository.save.assert_awaited_once_with(self.principal, requested)

    async def test_get_rejects_wrong_owner_even_if_repository_returns_task(self) -> None:
        self.repository.get.return_value = self.task
        outsider = Principal(tenant_id=1, user_id=3, project_id="test")
        with self.assertRaises(NotFoundError):
            await self.service.get(outsider, self.task.id)

    async def test_finish_selects_waiting_state(self) -> None:
        self.repository.get.return_value = self.task.start()
        task = await self.service.finish(
            self.principal,
            self.repository.get.return_value,
            waiting_for_user=True,
            output=None,
            question="请确认目标日期",
        )
        self.assertEqual(task.status, AgentTaskStatus.WAITING_HUMAN)
        self.repository.save.assert_awaited_once_with(self.principal, task)

    async def test_finish_rejects_empty_success_result(self) -> None:
        self.repository.get.return_value = self.task.start()
        for output in (None, "", "  "):
            with self.assertRaises(ValueError):
                await self.service.finish(
                    self.principal,
                    self.repository.get.return_value,
                    waiting_for_user=False,
                    output=output,
                )
        self.repository.save.assert_not_awaited()

    async def test_prepare_resume_checks_rule_without_saving(self) -> None:
        waiting = self.task.start().wait_for_user()
        self.repository.get.return_value = waiting
        task = await self.service.prepare_resume(self.principal, waiting.id)
        self.assertEqual(task.status, AgentTaskStatus.WAITING_HUMAN)
        self.repository.save.assert_not_awaited()

    async def test_resume_can_wait_again_without_new_attempt(self) -> None:
        self.repository.get.return_value = self.task.start()
        task = await self.service.finish_resume(
            self.principal,
            self.repository.get.return_value,
            waiting_for_user=True,
            output=None,
            question="还有其他要求吗？",
        )
        self.assertEqual(task.status, AgentTaskStatus.WAITING_HUMAN)
        self.assertEqual(task.attempt, 1)
