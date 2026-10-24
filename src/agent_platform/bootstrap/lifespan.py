from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_platform.bootstrap.wiring import build_container


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.container = build_container()
    try:
        yield
    finally:
        # Release clients/pools here once adapters are bound.
        del app.state.container
