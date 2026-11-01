"""连接级执行锁及断线监测；回写另以 execution_id 隔离旧执行。"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agent_platform.application.interfaces.task_execution_guard import (
    ExecutionOwnershipLost,
    TaskExecutionGuard,
)


class PostgresTaskExecutionGuard(TaskExecutionGuard):
    def __init__(self, engine: AsyncEngine, *, probe_interval: float = 2.0) -> None:
        self._engine = engine
        self._probe_interval = probe_interval

    @asynccontextmanager
    async def acquire(self, task_id: UUID) -> AsyncIterator[bool]:
        key = task_id.int % (2**63)
        async with self._engine.connect() as connection:
            owned = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": key},
                )
            )
            await connection.commit()
            if not owned:
                yield False
                return

            owner = asyncio.current_task()
            lost = False

            async def monitor() -> None:
                nonlocal lost
                while True:
                    await asyncio.sleep(self._probe_interval)
                    try:
                        async with asyncio.timeout(2):
                            # 禁止自动重连后冒充仍持有旧连接的锁。
                            if connection.invalidated:
                                raise ExecutionOwnershipLost("执行锁连接失效")
                            await connection.execute(text("SELECT 1"))
                            await connection.commit()
                    except Exception:
                        lost = True
                        if owner is not None:
                            owner.cancel()
                        return

            watcher = asyncio.create_task(monitor(), name=f"execution-lock-{task_id}")
            try:
                try:
                    yield True
                except asyncio.CancelledError:
                    if not lost:
                        raise
                except Exception as exc:
                    if lost:
                        raise ExecutionOwnershipLost("执行锁丢失，停止提交结果") from exc
                    raise
                if lost:
                    raise ExecutionOwnershipLost("执行锁连接丢失，已停止执行")
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
                if lost or connection.invalidated:
                    await connection.invalidate()
                else:
                    try:
                        async with asyncio.timeout(2):
                            await connection.execute(
                                text("SELECT pg_advisory_unlock(:key)"),
                                {"key": key},
                            )
                            await connection.commit()
                    except BaseException:
                        await connection.invalidate()
                        raise
