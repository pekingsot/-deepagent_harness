"""PostgreSQL 数据库连接和会话管理。"""

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """管理数据库引擎、连接池和会话工厂。"""

    def __init__(self, database_url: str) -> None:
        # 统一接收 PostgreSQL URL，由 SQLAlchemy 入口指定驱动
        url = make_url(database_url).set(drivername="postgresql+psycopg")
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
        )

        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )

    async def close(self) -> None:
        """关闭引擎并释放连接池资源。"""
        await self.engine.dispose()
