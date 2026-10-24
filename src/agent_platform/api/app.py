"""API scaffold: settings, dependency lifecycle, health, and versioned router wiring."""

import uvicorn
from fastapi import FastAPI

from agent_platform.api.routes.v1 import router as api_router
from agent_platform.api.routes.v1.health import router as health_router
from agent_platform.bootstrap.lifespan import lifespan
from agent_platform.bootstrap.settings import Settings


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(api_router)
    return app


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "agent_platform.api.app:create_app",
        factory=True, host=settings.host, port=settings.port,
    )


if __name__ == "__main__":
    main()
