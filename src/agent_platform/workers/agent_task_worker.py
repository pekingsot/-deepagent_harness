"""消费任务队列，调用应用服务执行任务。"""

import asyncio
import logging
from contextlib import nullcontext

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy_transactional.asyncio import sessionmaker_context

from agent_platform.application.dto.agent_task_dto import TaskJob
from agent_platform.application.dto.authentication_dto import AuthenticationError
from agent_platform.application.interfaces.job_queue import JobQueue
from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)
from agent_platform.application.services.authentication_application_service import (
    AuthenticationApplicationService,
)
from agent_platform.domain.aggregates.agent_task import AgentTaskStatus
from agent_platform.domain.types.common import ConflictError, NotFoundError
from agent_platform.infrastructure.observability.langfuse import LangfuseTracing

logger = logging.getLogger(__name__)


class AgentTaskWorker:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        queue: JobQueue,
        service: AgentTaskApplicationService,
        authentication: AuthenticationApplicationService,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        self._tracing = tracing  # 当前进程共享的追踪资源
        self._session_factory = session_factory  # 消费者上下文使用的会话工厂
        self._queue = queue  # 任务队列接口
        self._service = service  # 任务应用服务接口
        self._authentication = authentication  # 执行前复核账号状态

    async def consume(self, stop_event: asyncio.Event) -> None:
        """持续领取任务，收到停止信号后不再领取新任务。"""
        async with sessionmaker_context(self._session_factory):
            while not stop_event.is_set():
                message = await self._queue.receive(
                    timeout_seconds=1,
                )

                if message is None:
                    continue

                message_id, job = message
                context = job.context

                scope = (
                    self._tracing.observation(
                        "worker.consume",
                        parent=job.trace_context,
                        metadata={"task_id": str(context.task_id), "queue_message_id": message_id},
                    )
                    if self._tracing
                    else nullcontext()
                )
                with scope:
                    logger.info(
                        "开始处理任务，task_id=%s，message_id=%s",
                        context.task_id,
                        message_id,
                    )

                    try:
                        await self._authentication.require_active_principal(context)
                        await self._execute_job(job)

                        # 应用服务完成执行并保存业务状态后，再确认队列消息
                        await self._queue.acknowledge(message_id)

                    except AuthenticationError:
                        # 停用账号后不再执行排队任务，保留任务记录。
                        try:
                            await self._service.cancel(context, context.task_id)
                        except (ConflictError, NotFoundError):
                            pass
                        await self._queue.acknowledge(message_id)
                        logger.info("账号不可用，已拒绝任务：task_id=%s", context.task_id)

                    except (ConflictError, NotFoundError, ValueError):
                        # 已取消任务、重复指令及无效回复不应阻塞后续任务。
                        logger.warning("任务指令已拒绝，task_id=%s", context.task_id, exc_info=True)
                        await self._queue.acknowledge(message_id)

                    except asyncio.CancelledError:
                        # 关闭超时导致取消时，不确认未处理完成的消息
                        logger.warning(
                            "任务消费被取消，消息未确认，task_id=%s",
                            context.task_id,
                        )
                        raise

                    except Exception:
                        # 暂时向上抛出，让启动管理感知故障，不能静默丢失消息
                        logger.exception(
                            "任务处理异常，消息未确认，task_id=%s",
                            context.task_id,
                        )
                        raise

                    logger.info(
                        "任务消息处理完成，task_id=%s",
                        context.task_id,
                    )

    async def _execute_job(self, job: TaskJob) -> None:
        """执行和检查取消分属不同协程，只停止执行，不停止消费者。"""
        context = job.context
        invocation = (
            self._service.execute(principal=context, task_id=context.task_id)
            if job.resume is None
            else self._service.resume(
                principal=context,
                task_id=context.task_id,
                command=job.resume,
            )
        )
        execution = asyncio.create_task(invocation, name=f"agent-task-{context.task_id}")
        try:
            while not execution.done():
                done, _ = await asyncio.wait({execution}, timeout=0.5)
                if done:
                    break
                # 每次查询独立短事务，API 与 Worker 不必在同一进程。
                current = await self._service.execution_state(context, context.task_id)
                if current.status == AgentTaskStatus.CANCELLING:
                    execution.cancel()
                    stopped = None  # 应用服务可能已保存部分回答并确认取消
                    try:
                        stopped = await execution
                    except asyncio.CancelledError:
                        consumer = asyncio.current_task()
                        if consumer is not None and consumer.cancelling():
                            raise
                    # 必须等执行真正退出，才可以确认取消并 ACK。
                    if stopped is None or stopped.status != AgentTaskStatus.CANCELLED:
                        await self._service.complete_cancellation(
                            context,
                            context.task_id,
                            attempt=current.attempt,
                            execution_id=current.execution_id,
                        )
                    return
            await execution
        finally:
            # 服务关闭或检查失败时回收执行协程，不能遗留模型请求。
            if not execution.done():
                execution.cancel()
                try:
                    await execution
                except asyncio.CancelledError:
                    pass


async def _run() -> None:
    """独立 Worker 进程入口，与 API 使用同一套消费代码。"""
    from contextlib import AsyncExitStack

    from agent_platform.bootstrap.authentication import get_authentication_application_service
    from agent_platform.bootstrap.lifespan import start_workers
    from agent_platform.bootstrap.wiring import (
        get_agent_task_application_service,
        get_task_queue,
        get_tracing,
        open_container,
    )
    from agent_platform.workers.task_maintenance_worker import TaskMaintenanceWorker

    async with open_container() as container:
        worker = AgentTaskWorker(
            session_factory=container.database.session_factory,
            queue=get_task_queue(),
            tracing=get_tracing(),
            service=get_agent_task_application_service(),
            authentication=get_authentication_application_service(),
        )
        maintenance = TaskMaintenanceWorker(
            service=get_agent_task_application_service(),
            session_factory=container.database.session_factory,
        )
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(start_workers(consume=worker.consume, concurrency=1))
            await stack.enter_async_context(
                start_workers(consume=maintenance.consume, concurrency=1)
            )
            await asyncio.Event().wait()


def main() -> None:
    """运行独立消费者，Ctrl+C 时释放资源。"""
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    try:
        asyncio.run(_run(), loop_factory=loop_factory)
    except KeyboardInterrupt:
        logger.info("任务消费者已停止")


if __name__ == "__main__":
    main()
