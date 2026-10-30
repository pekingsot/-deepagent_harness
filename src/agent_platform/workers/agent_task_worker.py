"""消费任务队列，调用应用服务执行任务。"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy_transactional.asyncio import sessionmaker_context

from agent_platform.application.interfaces.job_queue import JobQueue
from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)
from agent_platform.domain.types.common import ConflictError, NotFoundError

logger = logging.getLogger(__name__)


class AgentTaskWorker:
    def __init__(
            self,
            *,
            session_factory: async_sessionmaker[AsyncSession],
            queue: JobQueue,
            service: AgentTaskApplicationService,
    ) -> None:
        self._session_factory = session_factory  # 消费者上下文使用的会话工厂
        self._queue = queue  # 任务队列接口
        self._service = service  # 任务应用服务接口

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

                logger.info(
                    "开始处理任务，task_id=%s，message_id=%s",
                    context.task_id,
                    message_id,
                )

                try:
                    if job.resume is None:
                        await self._service.execute(principal=context, task_id=context.task_id)
                    else:
                        await self._service.resume(
                            principal=context, task_id=context.task_id, command=job.resume
                        )

                    # 应用服务完成执行并保存业务状态后，再确认队列消息
                    await self._queue.acknowledge(message_id)

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


async def _run() -> None:
    """独立 Worker 进程入口，与 API 使用同一套消费代码。"""
    from agent_platform.bootstrap.lifespan import start_workers
    from agent_platform.bootstrap.wiring import (
        get_agent_task_application_service,
        get_task_queue,
        open_container,
    )

    async with open_container() as container:
        worker = AgentTaskWorker(
            session_factory=container.database.session_factory,
            queue=get_task_queue(),
            service=get_agent_task_application_service(runtime=container.runtime),
        )
        async with start_workers(consume=worker.consume, concurrency=1):
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
