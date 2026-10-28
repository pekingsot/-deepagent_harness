from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_platform.bootstrap.wiring import open_container


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with open_container() as container:
        app.state.container = container

        try:
            yield
        finally:
            del app.state.container