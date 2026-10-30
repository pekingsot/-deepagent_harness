import os
from functools import lru_cache

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool


class PostgresCheckpoint:
    def __init__(self) -> None:
        self._pool: AsyncConnectionPool[AsyncConnection[DictRow]] | None = None
        self._saver: AsyncPostgresSaver | None = None

    async def init(self) -> None:
        if self._saver is not None:
            return
        url = os.environ["POSTGRES_URL"]
        conninfo_to_dict(url)
        pool = AsyncConnectionPool[AsyncConnection[DictRow]](
            conninfo=url,
            min_size=1,
            max_size=10,
            open=False,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
                "prepare_threshold": 0,
            },
        )
        try:
            await pool.open(wait=True)
            saver = AsyncPostgresSaver(pool)
        except BaseException:
            await pool.close()
            raise
        self._pool = pool
        self._saver = saver

    async def setup(self) -> None:
        """初始化表结构或执行库提供的迁移"""
        await self._saver.setup()

    @property
    def saver(self) -> AsyncPostgresSaver:
        if self._saver is None:
            raise RuntimeError("PostgreSQL checkpoint 商未初始化")
        return self._saver

    async def shutdown(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            self._saver = None


@lru_cache(maxsize=1)
def get_postgres_checkpoint() -> PostgresCheckpoint:
    return PostgresCheckpoint()
