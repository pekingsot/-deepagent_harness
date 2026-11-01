import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """按配置随 API 启动消费者，先停消费者再释放共享资源。"""
    from contextlib import AsyncExitStack

    from agent_platform.bootstrap.authentication import get_authentication_application_service
    from agent_platform.bootstrap.wiring import (
        get_agent_task_application_service,
        get_task_queue,
        get_tracing,
        open_container,
    )
    from agent_platform.workers.agent_task_worker import AgentTaskWorker
    from agent_platform.workers.task_maintenance_worker import TaskMaintenanceWorker

    async with open_container() as container:
        app.state.container = container
        try:
            async with AsyncExitStack() as stack:
                if container.settings.worker_enabled:
                    if container.settings.worker_concurrency != 1:
                        raise ValueError("当前联调阶段请设置 HARNESS_WORKER_CONCURRENCY=1")
                    worker = AgentTaskWorker(
                        session_factory=container.database.session_factory,
                        queue=get_task_queue(),
                        tracing=get_tracing(),
                        authentication=get_authentication_application_service(),
                        service=get_agent_task_application_service(),
                    )
                    await stack.enter_async_context(
                        start_workers(consume=worker.consume, concurrency=1)
                    )
                maintenance = TaskMaintenanceWorker(
                    service=get_agent_task_application_service(),
                    session_factory=container.database.session_factory,
                )
                await stack.enter_async_context(
                    start_workers(consume=maintenance.consume, concurrency=1)
                )
                yield
        finally:
            del app.state.container


@asynccontextmanager
async def start_workers(
    *,
    consume: Callable[[asyncio.Event], Coroutine[None, None, None]],
    concurrency: int,
    shutdown_timeout: float = 30.0,
) -> AsyncIterator[None]:
    """管理当前进程中任务消费者的启动和关闭。"""
    if concurrency < 1:
        raise ValueError("消费者数量必须大于零")

    if shutdown_timeout <= 0:
        raise ValueError("关闭等待时间必须大于零")

    stop_event = asyncio.Event()  # 通知消费者停止领取新任务

    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(
                consume(stop_event),
                name=f"agent-task-consumer-{index + 1}",
            )
            for index in range(concurrency)
        ]

        try:
            yield
        finally:
            # 先通知消费者停止领取消息，等待正在执行的任务
            stop_event.set()

            _, pending = await asyncio.wait(
                tasks,
                timeout=shutdown_timeout,
            )

            # 超过等待时间后，取消尚未退出的消费者
            for task in pending:
                task.cancel()
