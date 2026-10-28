from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any
import asyncio

from agent_platform.infrastructure.embeddings.bge import get_embeddings
from langgraph.checkpoint.base import BaseCheckpointSaver
from agent_platform.infrastructure.persistence.database import Database

from agent_platform.bootstrap.container import Container
from agent_platform.bootstrap.settings import Settings, get_settings
from agent_platform.harness.agents import (
    CoderAgent,
    OrchestratorAgent,
    ResearcherAgent,
    ReviewerAgent, BaseAgent,
)
from agent_platform.harness.runtime.deepagents_adapter import (
    DeepAgentsRuntime,
)
from agent_platform.harness.tools.builtins.ask_user import ask_user
from agent_platform.infrastructure.cache.redis import get_redis
from agent_platform.infrastructure.checkpoint.posgres_checkpoint import (
    get_postgres_checkpoint,
)
from agent_platform.infrastructure.checkpoint.redis_checkpoint import (
    get_redis_checkpointer,
)


def build_container(
        *,
        settings: Settings,
        checkpointer: BaseCheckpointSaver[Any],
        database: Database
) -> Container:
    agents: dict[str, BaseAgent] = {
        OrchestratorAgent.name: OrchestratorAgent(
            tools=[ask_user],
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

    return Container(
        settings=settings,
        runtime=DeepAgentsRuntime(agents),
        database=database,
    )


@asynccontextmanager
async def open_container() -> AsyncIterator[Container]:
    settings = get_settings()

    async with AsyncExitStack() as stack:
        # 创建业务数据库引擎，并注册关闭操作
        database = Database(settings.database_url)
        stack.push_async_callback(database.close)

        checkpointer: BaseCheckpointSaver[Any]

        if settings.checkpoint_backend == "redis":
            redis = get_redis()

            stack.push_async_callback(redis.shutdown)
            await redis.init()

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
        await asyncio.to_thread(get_embeddings)

        yield build_container(
            settings=settings,
            checkpointer=checkpointer,
            database=database,
        )
