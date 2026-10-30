import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from functools import lru_cache
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from agent_platform.application.interfaces.agent_task_runtime import AgentTaskRuntime
from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)
from agent_platform.application.services.user_memory_application_service import (
    UserMemoryApplicationService,
)
from agent_platform.bootstrap.container import Container
from agent_platform.bootstrap.settings import Settings, get_settings
from agent_platform.domain.services.agent_task_domain_service import AgentTaskDomainService
from agent_platform.infrastructure.cache.redis import get_redis
from agent_platform.infrastructure.checkpoint.postgres_checkpoint import (
    get_postgres_checkpoint,
)
from agent_platform.infrastructure.checkpoint.redis_checkpoint import (
    get_redis_checkpointer,
)
from agent_platform.infrastructure.harness.agents import (
    BaseAgent,
    CoderAgent,
    ResearcherAgent,
    ReviewerAgent,
    TaskPlanningAgent,
)
from agent_platform.infrastructure.harness.runtime.deepagents_task_runtime import (
    DeepAgentsTaskRuntime,
)
from agent_platform.infrastructure.harness.tools.builtins.ask_user import ask_user
from agent_platform.infrastructure.messaging.redis_job_queue import RedisJobQueue
from agent_platform.infrastructure.messaging.redis_task_events import RedisTaskEvents
from agent_platform.infrastructure.persistence.database import Database
from agent_platform.infrastructure.persistence.repositories.agent_task_repository import (
    PostgresAgentTaskRepository,
)
from agent_platform.infrastructure.persistence.repositories.user_memory_repository import (
    PostgresMemoryRepository,
)
from agent_platform.infrastructure.harness.tools.builtins.user_memory import (
    create_user_memory_tools,
)

def create_user_memory_application_service() -> UserMemoryApplicationService:
    """装配记忆服务，仓储从入口绑定的事务上下文取得 Session。"""
    from agent_platform.infrastructure.embeddings.bge import get_embeddings

    embeddings = get_embeddings()
    return UserMemoryApplicationService(
        repository=PostgresMemoryRepository(),
        embeddings=embeddings,
        embedding_model=embeddings.model_name,
    )


@lru_cache(maxsize=1)
def _build_runtime(
    checkpointer: BaseCheckpointSaver[Any],
) -> AgentTaskRuntime:
    # 服务不持有 Session，由 API 或 Worker 入口绑定会话工厂。
    memory_service = create_user_memory_application_service()
    memory_tools = create_user_memory_tools(memory_service)

    agents: dict[str, BaseAgent] = {
        TaskPlanningAgent.name: TaskPlanningAgent(
            tools=[
                ask_user,
                *memory_tools,
            ],
            checkpointer=checkpointer,
        ),
        ResearcherAgent.name: ResearcherAgent(
            checkpointer=checkpointer,
        ),
        CoderAgent.name: CoderAgent(
            checkpointer=checkpointer,
        ),
        ReviewerAgent.name: ReviewerAgent(
            checkpointer=checkpointer,
        ),
    }

    return DeepAgentsTaskRuntime(agents)


@lru_cache(maxsize=1)
def get_task_queue() -> RedisJobQueue:
    """取得当前进程的任务队列，Redis 必须已完成初始化。"""
    settings = get_settings()
    return RedisJobQueue(
        client=get_redis().client,
        stream_name=settings.task_queue_stream,
        group_name=settings.task_queue_group,
    )


@lru_cache(maxsize=1)
def get_task_events() -> RedisTaskEvents:
    """复用 Redis 客户端，事件流与任务消费队列分别存放。"""
    return RedisTaskEvents(get_redis().client)


@lru_cache(maxsize=1)
def get_agent_task_application_service(
    runtime: AgentTaskRuntime,
) -> AgentTaskApplicationService:
    """应用服务使用已装配好的执行接口，不重复构建运行器。"""
    return AgentTaskApplicationService(
        tasks=AgentTaskDomainService(
            PostgresAgentTaskRepository(),
        ),
        queue=get_task_queue(),
        runtime=runtime,
        events=get_task_events(),
    )


def build_container(
    *, settings: Settings, checkpointer: BaseCheckpointSaver[Any], database: Database
) -> Container:
    """容器保留共享资源，不逐个登记业务服务。"""
    return Container(settings=settings, runtime=_build_runtime(checkpointer), database=database)


@asynccontextmanager
async def open_container() -> AsyncIterator[Container]:
    settings = get_settings()

    async with AsyncExitStack() as stack:
        # 创建业务数据库引擎，并注册关闭操作
        redis = get_redis()

        stack.push_async_callback(redis.shutdown)
        await redis.init()
        stack.callback(get_task_queue.cache_clear)
        stack.callback(get_task_events.cache_clear)
        stack.callback(_build_runtime.cache_clear)
        stack.callback(get_agent_task_application_service.cache_clear)
        queue = get_task_queue()
        await queue.setup()

        database = Database(settings.database_url)
        stack.push_async_callback(database.close)
        checkpointer: BaseCheckpointSaver[Any]
        if settings.checkpoint_backend == "redis":
            saver = get_redis_checkpointer()
            stack.callback(get_redis_checkpointer.cache_clear)

            await saver.asetup()
            checkpointer = saver

        else:
            postgres = get_postgres_checkpoint()

            stack.push_async_callback(postgres.shutdown)
            await postgres.init()

            checkpointer = postgres.saver

        # 提前加载向量模型，完成后再接收请求或任务
        from agent_platform.infrastructure.embeddings.bge import get_embeddings

        await asyncio.to_thread(get_embeddings)

        yield build_container(
            settings=settings,
            checkpointer=checkpointer,
            database=database,
        )
