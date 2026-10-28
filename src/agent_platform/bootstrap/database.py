import asyncio

from agent_platform.bootstrap.settings import get_settings
from agent_platform.infrastructure.checkpoint.posgres_checkpoint import (
    get_postgres_checkpoint,
)


async def main() -> None:
    get_settings()

    checkpoint = get_postgres_checkpoint()

    try:
        await checkpoint.init()
        await checkpoint.setup()
    finally:
        await checkpoint.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

# 首次部署或升级 checkpoint表结构时执行
# uv run python -m agent_platform.bootstrap.database
# 这个入口只处理 PostgreSQL checkpoint 的建表和迁移，不处理未来业务 ORM 表。
