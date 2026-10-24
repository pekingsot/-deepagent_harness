from fastapi import APIRouter

from agent_platform.api.routes.v1 import agents, approvals, runs, sessions, skills

router = APIRouter(prefix="/api/v1")
for module in (agents, runs, sessions, approvals, skills):
    router.include_router(module.router)
