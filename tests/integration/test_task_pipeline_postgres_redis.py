"""显式启用的 PostgreSQL、Redis 联调；执行器使用确定性替身，不调用外部模型。"""

import asyncio
import os
import sys
import unittest
from unittest.mock import create_autospec
from uuid import uuid4

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import delete
from sqlalchemy_transactional.asyncio import sessionmaker_context

from agent_platform.application.dto.agent_task_dto import AgentTaskExecutionResult
from agent_platform.application.interfaces.agent_task_runtime import AgentTaskRuntime
from agent_platform.application.interfaces.task_events import TaskEvents
from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)
from agent_platform.bootstrap.lifespan import start_workers
from agent_platform.bootstrap.settings import get_settings
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.domain.services.agent_task_domain_service import AgentTaskDomainService
from agent_platform.domain.types.common import Principal
from agent_platform.infrastructure.messaging.redis_job_queue import RedisJobQueue
from agent_platform.infrastructure.persistence.database import Database
from agent_platform.infrastructure.persistence.entities.agent_tasks import AgentTaskRecord
from agent_platform.infrastructure.persistence.repositories.agent_task_repository import (
    PostgresAgentTaskRepository,
)
from agent_platform.interface.api.dependencies import get_principal, get_task_application_service
from agent_platform.interface.api.routes.v1.agent_tasks import router
from agent_platform.workers.agent_task_worker import AgentTaskWorker


class IntegrationRuntime(AgentTaskRuntime):
    async def execute(self, task: AgentTask, *, on_text=None) -> AgentTaskExecutionResult:
        return AgentTaskExecutionResult(status="completed", output="PostgreSQL 和 Redis 链路通过")

    async def get_state(self, task: AgentTask) -> AgentTaskExecutionResult:
        raise AssertionError("本测试不读取 checkpoint")

    async def resume(self, task, command, *, on_text=None) -> AgentTaskExecutionResult:
        raise AssertionError("本测试不执行人工恢复")


class IntegrationQueue(RedisJobQueue):
    def __init__(self, *, done: asyncio.Event, **kwargs) -> None:
        super().__init__(**kwargs)
        self._done = done  # 标记真实 Redis 消息已确认

    async def acknowledge(self, message_id: str) -> None:
        await super().acknowledge(message_id)
        self._done.set()


@unittest.skipUnless(
    os.environ.get("HARNESS_RUN_PIPELINE_INTEGRATION") == "1",
    "需要显式设置 HARNESS_RUN_PIPELINE_INTEGRATION=1",
)
class PostgresRedisPipelineTests(unittest.TestCase):
    def test_real_database_and_stream(self) -> None:
        loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
        asyncio.run(self._check_pipeline(), loop_factory=loop_factory)

    async def _check_pipeline(self) -> None:
        settings = get_settings()
        database = Database(settings.database_url)
        redis = Redis.from_url(
            os.environ["REDIS_URL"],
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
        )
        unique = uuid4().hex
        stream = f"agent_platform:pipeline_test:{unique}"
        principal = Principal(tenant_id=1, user_id=1, project_id=f"smoke-{unique}")
        prompt = f"任务链路联调 {unique}"
        done = asyncio.Event()
        queue = IntegrationQueue(client=redis, stream_name=stream, group_name="smoke", done=done)
        service = AgentTaskApplicationService(
            tasks=AgentTaskDomainService(PostgresAgentTaskRepository()),
            queue=queue,
            runtime=IntegrationRuntime(),
            events=create_autospec(TaskEvents, instance=True),
        )
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_principal] = lambda: principal
        app.dependency_overrides[get_task_application_service] = lambda: service

        @app.middleware("http")
        async def database_context(request, call_next):
            async with sessionmaker_context(database.session_factory):
                return await call_next(request)

        stream_ready = False  # 只有队列实际创建后才清理
        task_attempted = False  # 只有发送过请求后才清理数据库
        try:
            async with asyncio.timeout(30):
                await queue.setup()
                stream_ready = True
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    task_attempted = True
                    response = await client.post("/api/v1/tasks", json={"prompt": prompt})
                    self.assertEqual(response.status_code, 202, response.text)
                    task_id = response.json()["task_id"]
                    worker = AgentTaskWorker(
                        session_factory=database.session_factory, queue=queue, service=service
                    )
                    async with start_workers(consume=worker.consume, concurrency=1):
                        await asyncio.wait_for(done.wait(), timeout=10)
                    response = await client.get(f"/api/v1/tasks/{task_id}")
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["status"], "succeeded")
                    self.assertEqual(response.json()["result"], "PostgreSQL 和 Redis 链路通过")
        finally:
            # 只清理本次唯一项目和提示词对应的测试记录，不触碰既有任务
            try:
                if task_attempted:
                    async with asyncio.timeout(5):
                        async with database.session_factory.begin() as session:
                            await session.execute(
                                delete(AgentTaskRecord).where(
                                    AgentTaskRecord.tenant_id == principal.tenant_id,
                                    AgentTaskRecord.user_id == principal.user_id,
                                    AgentTaskRecord.project_id == principal.project_id,
                                    AgentTaskRecord.prompt == prompt,
                                )
                            )
            finally:
                try:
                    if stream_ready:
                        async with asyncio.timeout(5):
                            await redis.delete(stream)
                finally:
                    await redis.aclose()
                    await database.close()
