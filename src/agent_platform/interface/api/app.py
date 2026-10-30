"""API scaffold: settings, dependency lifecycle, health, and versioned router wiring."""

import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable

import uvicorn
from fastapi import FastAPI, Request
from sqlalchemy_transactional.asyncio import sessionmaker_context
from starlette.responses import Response

from agent_platform.bootstrap.lifespan import lifespan
from agent_platform.bootstrap.settings import get_settings
from agent_platform.interface.api.routes.v1 import router as api_router
from agent_platform.interface.api.routes.v1.health import router as health_router


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def bind_database_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """绑定当前请求的会话工厂，供应用服务的事务装饰器使用。"""
        database = request.app.state.container.database

        async with sessionmaker_context(database.session_factory):
            return await call_next(request)

    app.include_router(health_router)
    app.include_router(api_router)

    return app


def main() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Windows 显式指定 SelectorEventLoop，支持 Psycopg 异步连接。
    # 其他系统继续使用 Uvicorn 默认的事件循环选择。
    loop = (
        "asyncio:SelectorEventLoop"
        if sys.platform == "win32"
        else "auto"
    )

    uvicorn.run(
        "agent_platform.interface.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        loop=loop,
        timeout_graceful_shutdown=10,  # 给 SSE 主动退出留出时间，超时仍取消未结束的请求
    )


if __name__ == "__main__":
    main()
