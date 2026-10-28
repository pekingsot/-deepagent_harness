"""测试 PostgreSQL 异步连接。"""

import asyncio
import selectors

from sqlalchemy import text

from agent_platform.bootstrap.settings import get_settings
from agent_platform.infrastructure.persistence.database import Database


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)

    try:
        async with database.session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            value = result.scalar_one()

            print(f"数据库连接成功，查询结果：{value}")
    finally:
        await database.close()


if __name__ == "__main__":
    # Windows 下使用 Psycopg 支持的事件循环
    asyncio.run(
        main(),
        loop_factory=lambda: asyncio.SelectorEventLoop(
            selectors.SelectSelector()
        ),
    )