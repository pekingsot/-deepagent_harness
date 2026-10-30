from fastapi import APIRouter

from agent_platform.interface.api.routes.v1 import agent_tasks, agents, approvals, sessions, skills

router = APIRouter(prefix="/api/v1")
for module in (agents, agent_tasks, sessions, approvals, skills):
    router.include_router(module.router)
