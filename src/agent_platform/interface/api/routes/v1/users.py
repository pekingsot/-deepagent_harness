"""租户管理员用户管理接口，身份由服务端登录会话确定。"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from agent_platform.application.dto.authentication_dto import UserPage, UserSummary
from agent_platform.interface.api.dependencies import CurrentPrincipal, CurrentUserService
from agent_platform.interface.vo.user_vo import (
    CreateUserRequest,
    ResetPasswordRequest,
    UpdateUserRequest,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserPage)
async def list_users(
    principal: CurrentPrincipal,
    service: CurrentUserService,
    after_id: Annotated[int, Query(ge=0, le=9223372036854775807)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> UserPage:
    return await service.list_users(principal, after_id=after_id, limit=limit)


@router.post("", response_model=UserSummary, status_code=201)
async def create_user(
    command: CreateUserRequest, principal: CurrentPrincipal, service: CurrentUserService
) -> UserSummary:
    return await service.create(principal, command)


@router.patch("/{user_id}", response_model=UserSummary)
async def update_user(
    user_id: Annotated[int, Path(gt=0, le=9223372036854775807)],
    command: UpdateUserRequest,
    principal: CurrentPrincipal,
    service: CurrentUserService,
) -> UserSummary:
    return await service.update(principal, user_id, command)


@router.post("/{user_id}/reset-password", status_code=204)
async def reset_password(
    user_id: Annotated[int, Path(gt=0, le=9223372036854775807)],
    command: ResetPasswordRequest,
    principal: CurrentPrincipal,
    service: CurrentUserService,
) -> Response:
    await service.reset_password(principal, user_id, command.password.get_secret_value())
    return Response(status_code=204)
