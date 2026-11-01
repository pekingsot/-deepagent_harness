from fastapi import APIRouter

from agent_platform.interface.api.routes.v1 import (
    agent_tasks,
    agents,
    approvals,
    authentication,
    sessions,
    skills,
    user_memories,
    users,
)

router = APIRouter(prefix="/api/v1")
for module in (
    agents,
    agent_tasks,
    sessions,
    approvals,
    skills,
    authentication,
    users,
    user_memories,
):
    router.include_router(module.router)
