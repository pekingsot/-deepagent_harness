"""登录接口；浏览器通过 Next.js 服务端代理获取 HttpOnly 会话。"""

from fastapi import APIRouter, Request, Response

from agent_platform.application.dto.authentication_dto import CurrentUser
from agent_platform.interface.api.dependencies import (
    CurrentAuthenticationService,
    CurrentToken,
    CurrentUserIdentity,
)
from agent_platform.interface.vo.user_vo import ChangePasswordRequest, LoginRequest, LoginResponse

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=LoginResponse)
async def login(
    command: LoginRequest, request: Request, service: CurrentAuthenticationService
) -> LoginResponse:
    # 只读取服务器看到的来源地址，不信任浏览器可随意填写的转发头。
    client = request.client.host if request.client else "unknown"
    token, user = await service.login(command, client)
    return LoginResponse(access_token=token, expires_in=service.session_ttl, user=user)


@router.get("/me", response_model=CurrentUser)
async def me(user: CurrentUserIdentity) -> CurrentUser:
    return user


@router.post("/logout", status_code=204)
async def logout(token: CurrentToken, service: CurrentAuthenticationService) -> Response:
    # 允许撤销已失效的会话，退出操作幂等。
    await service.logout(token)
    return Response(status_code=204)


@router.put("/password", status_code=204)
async def change_password(
    command: ChangePasswordRequest, user: CurrentUserIdentity, service: CurrentAuthenticationService
) -> Response:
    await service.change_password(user.principal(), command)
    return Response(status_code=204)
