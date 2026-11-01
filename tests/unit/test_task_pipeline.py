"""离线验证真实 HTTP 路由、领域服务、应用服务和 Worker 的连接。"""

import asyncio
import unittest

from test_running_task_cancellation import OfflineExecutionGuard
from contextlib import asynccontextmanager
from unittest.mock import create_autospec
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, HTTPException
from sqlalchemy_transactional.asyncio import current_session, sessionmaker_context

from agent_platform.application.dto.agent_task_dto import (
    AgentTaskExecutionResult,
    ResumeAgentTask,
    TaskJob,
)
from agent_platform.application.dto.authentication_dto import CurrentUser
from agent_platform.application.interfaces.agent_task_runtime import AgentTaskRuntime
from agent_platform.application.interfaces.job_queue import JobQueue
from agent_platform.application.interfaces.task_events import TaskEvents
from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)
from agent_platform.application.services.authentication_application_service import (
    AuthenticationApplicationService,
)
from agent_platform.bootstrap.lifespan import start_workers
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.domain.repositories.agent_task_repository import AgentTaskRepository
from agent_platform.domain.services.agent_task_domain_service import AgentTaskDomainService
from agent_platform.domain.types.common import NotFoundError, Principal, TaskContext
from agent_platform.domain.types.task_message import TaskMessage
from agent_platform.interface.api.dependencies import (
    get_authentication_service,
    get_task_application_service,
    get_tracing,
)
from agent_platform.interface.api.routes.v1.agent_tasks import router
from agent_platform.workers.agent_task_worker import AgentTaskWorker


class OfflineTracing:
    """HTTP 链路使用空追踪上下文，不装配 Redis 或外部 SDK。"""

    @asynccontextmanager
    async def api(self, *args, **kwargs):
        yield None


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
    async def recovery_candidates(self, *, after_id=None):
        return sorted(
            [t for t in self.tasks.values() if after_id is None or t.id > after_id],
            key=lambda t: t.id,
        )[:50]

    async def pending_deletions(self, *, after_id=None):
        return sorted(
            [
                t
                for t in self.tasks.values()
                if t.deletion_requested and (after_id is None or t.id > after_id)
            ],
            key=lambda t: t.id,
        )[:50]

    async def delete(self, principal, task_id):
        self.tasks[task_id].ensure_owned_by(principal)
        del self.tasks[task_id]
        self.history.pop(task_id, None)
        self.execution_records = {
            key: value for key, value in self.execution_records.items() if key[0] != task_id
        }

    def __init__(self) -> None:
        self.history = {}  # 离线测试的会话消息
        self.execution_records = {}  # 按会话和轮次保存执行快照
        self.tasks: dict[UUID, AgentTask] = {}  # 当前测试保存的任务

    async def save_execution(self, principal, task_id, execution):
        self.tasks[task_id].ensure_owned_by(principal)
        self.execution_records[(task_id, execution.attempt)] = execution

    async def executions(self, principal, task_id):
        self.tasks[task_id].ensure_owned_by(principal)
        return sorted(
            [value for (key, _), value in self.execution_records.items() if key == task_id],
            key=lambda value: value.attempt,
            reverse=True,
        )

    async def save(self, principal: Principal, task: AgentTask) -> None:
        current_session()
        task.ensure_owned_by(principal)
        self.tasks[task.id] = task

    async def get(
        self, principal: Principal, task_id: UUID, *, for_update: bool = False
    ) -> AgentTask | None:
        current_session()
        task = self.tasks.get(task_id)
        if task is not None:
            try:
                task.ensure_owned_by(principal)
            except NotFoundError:
                return None
        return task

    async def list_recent(self, principal, *, limit=50):
        return [task for task in self.tasks.values() if task.context.user_id == principal.user_id][
            :limit
        ]

    async def messages(self, principal, task_id):
        return list(self.history.get(task_id, []))

    async def add_message(self, principal, task_id, message):
        self.history.setdefault(task_id, []).append(message)

    async def set_message_state(self, principal, task_id, ids, state):
        self.history[task_id] = [
            TaskMessage.model_validate({**message.model_dump(), "state": state})
            if message.id in ids
            else message
            for message in self.history.get(task_id, [])
        ]


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
    async def execute(
        self,
        task: AgentTask,
        *,
        messages=(),
        restart_after_interruption=False,
        on_text=None,
        on_plan=None,
        on_activity=None,
        on_title=None,
    ) -> AgentTaskExecutionResult:
        return AgentTaskExecutionResult(status="completed", output="任务链路验证成功")

    async def get_state(self, task: AgentTask) -> AgentTaskExecutionResult:
        return AgentTaskExecutionResult(status="completed", output="任务链路验证成功")

    async def resume(
        self, task, command, *, on_text=None, on_plan=None, on_activity=None
    ) -> AgentTaskExecutionResult:
        raise AssertionError("本测试不应恢复任务")


class TaskPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.queue = OfflineQueue()  # 替代真实 Redis
        self.repository = OfflineRepository()  # 替代真实 PostgreSQL
        self.service = AgentTaskApplicationService(
            execution_guard=OfflineExecutionGuard(),
            tasks=AgentTaskDomainService(self.repository),
            queue=self.queue,
            runtime=OfflineRuntime(),
            events=create_autospec(TaskEvents, instance=True),
        )  # 真实应用服务和领域规则
        self.principal = Principal(tenant_id=1, user_id=2, project_id="test")  # 服务端测试身份
        self.revoked = False  # 模拟已撤销的登录会话
        self.authentication = create_autospec(AuthenticationApplicationService, instance=True)

        async def authenticate(token):
            if token != "offline-token" or self.revoked:
                raise HTTPException(status_code=401, detail="登录已失效")
            return CurrentUser(
                id=self.principal.user_id,
                tenant_id=self.principal.tenant_id,
                tenant_code="offline",
                tenant_name="测试公司",
                project_id=self.principal.project_id,
                username="tester",
                display_name="测试用户",
                role="user",
            )

        self.authentication.authenticate.side_effect = authenticate
        self.app = FastAPI()  # 使用真实生产路由和认证依赖
        self.app.include_router(router, prefix="/api/v1")
        self.app.dependency_overrides[get_task_application_service] = lambda: self.service
        self.app.dependency_overrides[get_tracing] = OfflineTracing

        @self.app.middleware("http")
        async def database_context(request, call_next):
            async with sessionmaker_context(OfflineSession):
                return await call_next(request)

        self.app.dependency_overrides[get_authentication_service] = lambda: self.authentication
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
            session_factory=OfflineSession,
            queue=self.queue,
            service=self.service,
            authentication=self.authentication,
        )
        async with start_workers(consume=worker.consume, concurrency=1):
            await asyncio.wait_for(self.queue.acknowledged.wait(), timeout=5)

        response = await self.client.get(f"/api/v1/tasks/{task_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "succeeded")
        self.assertEqual(response.json()["result"], "任务链路验证成功")

        self.principal = Principal(tenant_id=1, user_id=3, project_id="test")
        response = await self.client.get(f"/api/v1/tasks/{task_id}")
        self.assertEqual(response.status_code, 404)

    async def test_stop_and_correct_input_in_same_http_session(self) -> None:
        created = await self.client.post("/api/v1/tasks", json={"prompt": "错误输入"})
        task_id = created.json()["task_id"]
        stopped = await self.client.post(f"/api/v1/tasks/{task_id}/cancel")
        self.assertEqual(stopped.json()["status"], "cancelled")
        sent = await self.client.post(
            f"/api/v1/tasks/{task_id}/messages",
            json={"id": str(uuid4()), "content": "正确输入"},
        )
        self.assertEqual(sent.status_code, 202, sent.text)
        self.assertEqual(sent.json()["task_id"], task_id)
        self.assertEqual(sent.json()["status"], "queued")
        async with sessionmaker_context(OfflineSession):
            completed = await self.service.execute(self.principal, UUID(task_id))
        self.assertEqual(completed.status, "succeeded")
        self.assertEqual(len(self.repository.tasks), 1)

    async def test_execution_history_endpoint_preserves_round_title_and_checks_owner(self) -> None:
        created = await self.client.post("/api/v1/tasks", json={"prompt": "整个版本开发"})
        task_id = created.json()["task_id"]
        async with sessionmaker_context(OfflineSession):
            task, _ = await self.service._claim_task(self.principal, UUID(task_id))
            await self.service._finish_task(
                self.principal,
                task,
                AgentTaskExecutionResult(
                    status="completed",
                    title="编写地图策划",
                    output="策划已完成",
                ),
            )
            await self.service.rename(self.principal, UUID(task_id), "版本研发总会话")
        response = await self.client.get(f"/api/v1/tasks/{task_id}/executions")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()[0]["title"], "编写地图策划")
        self.assertEqual(response.json()[0]["output"], "策划已完成")
        self.principal = Principal(tenant_id=1, user_id=999, project_id="test")
        denied = await self.client.get(f"/api/v1/tasks/{task_id}/executions")
        self.assertEqual(denied.status_code, 404)

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

    async def test_revoked_session_cannot_submit(self) -> None:
        self.revoked = True
        response = await self.client.post("/api/v1/tasks", json={"prompt": "制定计划"})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.repository.tasks)

    async def test_blank_prompt_is_rejected(self) -> None:
        response = await self.client.post("/api/v1/tasks", json={"prompt": "   "})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(self.repository.tasks)
