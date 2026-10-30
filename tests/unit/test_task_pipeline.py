"""离线验证真实 HTTP 路由、领域服务、应用服务和 Worker 的连接。"""

import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import create_autospec, patch
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy_transactional.asyncio import current_session, sessionmaker_context

from agent_platform.application.dto.agent_task_dto import AgentTaskExecutionResult, ResumeAgentTask, TaskJob
from agent_platform.application.interfaces.agent_task_runtime import AgentTaskRuntime
from agent_platform.application.interfaces.task_events import TaskEvents
from agent_platform.application.interfaces.job_queue import JobQueue
from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)
from agent_platform.bootstrap.lifespan import start_workers
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.domain.repositories.agent_task_repository import AgentTaskRepository
from agent_platform.domain.services.agent_task_domain_service import AgentTaskDomainService
from agent_platform.domain.types.common import NotFoundError, Principal, TaskContext
from agent_platform.interface.api.dependencies import get_task_application_service
from agent_platform.interface.api.routes.v1.agent_tasks import router
from agent_platform.workers.agent_task_worker import AgentTaskWorker


class OfflineSession:
    """只承载事务上下文，不连接数据库。"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    @asynccontextmanager
    async def begin(self):
        yield


class OfflineRepository(AgentTaskRepository):
    def __init__(self) -> None:
        self.tasks: dict[UUID, AgentTask] = {}  # 当前测试保存的任务

    async def save(self, principal: Principal, task: AgentTask) -> None:
        current_session()
        task.ensure_owned_by(principal)
        self.tasks[task.id] = task

    async def get(self, principal: Principal, task_id: UUID) -> AgentTask | None:
        current_session()
        task = self.tasks.get(task_id)
        if task is not None:
            try:
                task.ensure_owned_by(principal)
            except NotFoundError:
                return None
        return task


class OfflineQueue(JobQueue):
    def __init__(self) -> None:
        self.messages: asyncio.Queue[tuple[str, TaskJob]] = asyncio.Queue()  # 测试消息
        self.acknowledged = asyncio.Event()  # 确认 Worker 完成消费

    async def enqueue(self, context: TaskContext, *, resume: ResumeAgentTask | None = None) -> str:
        message_id = uuid4().hex
        await self.messages.put((message_id, TaskJob(context=context, resume=resume)))
        return message_id

    async def receive(self, *, timeout_seconds: int = 1) -> tuple[str, TaskJob] | None:
        try:
            return await asyncio.wait_for(self.messages.get(), timeout_seconds)
        except TimeoutError:
            return None

    async def acknowledge(self, message_id: str) -> None:
        self.acknowledged.set()


class OfflineRuntime(AgentTaskRuntime):
    async def execute(self, task: AgentTask, *, on_text=None) -> AgentTaskExecutionResult:
        return AgentTaskExecutionResult(status="completed", output="任务链路验证成功")

    async def get_state(self, task: AgentTask) -> AgentTaskExecutionResult:
        return AgentTaskExecutionResult(status="completed", output="任务链路验证成功")

    async def resume(self, task, command, *, on_text=None) -> AgentTaskExecutionResult:
        raise AssertionError("本测试不应恢复任务")


class TaskPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.queue = OfflineQueue()  # 替代真实 Redis
        self.repository = OfflineRepository()  # 替代真实 PostgreSQL
        self.service = AgentTaskApplicationService(
            tasks=AgentTaskDomainService(self.repository),
            queue=self.queue,
            runtime=OfflineRuntime(),
            events=create_autospec(TaskEvents, instance=True),
        )  # 真实应用服务和领域规则
        self.principal = Principal(tenant_id=1, user_id=2, project_id="test")  # 服务端测试身份
        self.settings = SimpleNamespace(
            environment="development",
            development_token=SecretStr("offline-token"),
            development_principal=self.principal,
        )  # 仅测试使用的认证配置
        self.app = FastAPI()  # 使用真实生产路由和认证依赖
        self.app.include_router(router, prefix="/api/v1")
        self.app.dependency_overrides[get_task_application_service] = lambda: self.service

        @self.app.middleware("http")
        async def database_context(request, call_next):
            async with sessionmaker_context(OfflineSession):
                return await call_next(request)

        self.patch_settings = patch(
            "agent_platform.interface.api.dependencies.get_settings", return_value=self.settings
        )  # 隔离真实配置与密钥
        self.patch_settings.start()
        self.addCleanup(self.patch_settings.stop)
        self.client = await self.enterAsyncContext(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://test",
                headers={"Authorization": "Bearer offline-token"},
            )
        )

    async def test_submit_consume_and_query_result(self) -> None:
        response = await self.client.post("/api/v1/tasks", json={"prompt": "制定开发计划"})
        self.assertEqual(response.status_code, 202, response.text)
        task_id = response.json()["task_id"]
        self.assertEqual(response.json()["status"], "queued")
        self.assertNotIn("context", response.json())
        self.assertIn(UUID(task_id), self.repository.tasks)

        worker = AgentTaskWorker(
            session_factory=OfflineSession, queue=self.queue, service=self.service
        )
        async with start_workers(consume=worker.consume, concurrency=1):
            await asyncio.wait_for(self.queue.acknowledged.wait(), timeout=5)

        response = await self.client.get(f"/api/v1/tasks/{task_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "succeeded")
        self.assertEqual(response.json()["result"], "任务链路验证成功")

        self.settings.development_principal = Principal(tenant_id=1, user_id=3, project_id="test")
        response = await self.client.get(f"/api/v1/tasks/{task_id}")
        self.assertEqual(response.status_code, 404)

    async def test_invalid_token_does_not_create_task(self) -> None:
        response = await self.client.post(
            "/api/v1/tasks",
            json={"prompt": "制定计划"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.repository.tasks)

    async def test_client_cannot_supply_identity(self) -> None:
        response = await self.client.post(
            "/api/v1/tasks", json={"prompt": "制定计划", "user_id": 999}
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(self.repository.tasks)

    async def test_development_identity_cannot_be_used_in_production(self) -> None:
        self.settings.environment = "production"
        response = await self.client.post("/api/v1/tasks", json={"prompt": "制定计划"})
        self.assertEqual(response.status_code, 501)
        self.assertFalse(self.repository.tasks)

    async def test_blank_prompt_is_rejected(self) -> None:
        response = await self.client.post("/api/v1/tasks", json={"prompt": "   "})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(self.repository.tasks)
