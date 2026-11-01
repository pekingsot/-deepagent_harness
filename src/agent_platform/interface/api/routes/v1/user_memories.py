"""个人长期记忆接口，只调用应用服务，不直接访问数据库或向量模型。"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Response

from agent_platform.application.dto.user_memory_dto import UserMemoryPage
from agent_platform.interface.api.dependencies import (
    CurrentPrincipal,
    CurrentUserMemoryApplicationService,
)
from agent_platform.interface.vo.user_memory_vo import UpdateUserMemoryRequest

router = APIRouter(prefix="/user-memories", tags=["user-memories"])


@router.get("", response_model=UserMemoryPage)
async def list_memories(
    principal: CurrentPrincipal,
    service: CurrentUserMemoryApplicationService,
    cursor: Annotated[int | None, Query(gt=0, le=9223372036854775807)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> UserMemoryPage:
    """分页读取当前登录用户的记忆，不接收前端传入的租户或用户身份。"""
    return await service.list_recent(principal, cursor=cursor, limit=limit)


@router.patch("/{memory_id}", status_code=204)
async def update_memory(
    memory_id: Annotated[int, Path(gt=0, le=9223372036854775807)],
    command: UpdateUserMemoryRequest,
    principal: CurrentPrincipal,
    service: CurrentUserMemoryApplicationService,
) -> Response:
    """应用服务重新生成向量，再原子替换内容与向量。"""
    updated = await service.update(principal, memory_id, command.content)
    if not updated:
        raise HTTPException(status_code=404, detail="记忆不存在或无权访问")
    return Response(status_code=204)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: Annotated[int, Path(gt=0, le=9223372036854775807)],
    principal: CurrentPrincipal,
    service: CurrentUserMemoryApplicationService,
) -> Response:
    """不存在和无权访问统一返回 404，避免泄露他人记录是否存在。"""
    deleted = await service.delete(principal, memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="记忆不存在或无权访问")
    return Response(status_code=204)
