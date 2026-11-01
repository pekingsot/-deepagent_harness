from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent_platform.application.dto.authentication_dto import CurrentUser
from agent_platform.application.interfaces.task_events import TaskEvents
from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)
from agent_platform.application.services.authentication_application_service import (
    AuthenticationApplicationService,
)
from agent_platform.application.services.user_application_service import UserApplicationService
from agent_platform.application.services.user_memory_application_service import (
    UserMemoryApplicationService,
)
from agent_platform.bootstrap.container import Container
from agent_platform.domain.types.common import Principal
from agent_platform.infrastructure.observability.langfuse import LangfuseTracing


def get_container(request: Request) -> Container:
    container = request.app.state.container
    if not isinstance(container, Container):
        raise RuntimeError("Container not initialized")
    return container


bearer = HTTPBearer(auto_error=False)


def get_authentication_service() -> AuthenticationApplicationService:
    """认证服务由装配层创建，业务层不接触请求对象。"""
    from agent_platform.bootstrap.authentication import get_authentication_application_service

    return get_authentication_application_service()


def get_user_service() -> UserApplicationService:
    """取得用户管理应用服务。"""
    from agent_platform.bootstrap.authentication import get_user_application_service

    return get_user_application_service()


def get_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401, detail="请先登录", headers={"WWW-Authenticate": "Bearer"}
        )
    return credentials.credentials


type CurrentToken = Annotated[str, Depends(get_token)]
type CurrentAuthenticationService = Annotated[
    AuthenticationApplicationService, Depends(get_authentication_service)
]
type CurrentUserService = Annotated[UserApplicationService, Depends(get_user_service)]


async def get_current_user(
    token: CurrentToken, service: CurrentAuthenticationService
) -> CurrentUser:
    return await service.authenticate(token)


type CurrentUserIdentity = Annotated[CurrentUser, Depends(get_current_user)]


async def get_principal(user: CurrentUserIdentity) -> Principal:
    """只能从已认证的服务端账号生成业务身份。"""
    return user.principal()


def get_user_memory_application_service() -> UserMemoryApplicationService:
    """按需装配记忆服务，会话工厂已经由 API 中间件绑定。"""
    from agent_platform.bootstrap.wiring import create_user_memory_application_service

    return create_user_memory_application_service()


type CurrentContainer = Annotated[Container, Depends(get_container)]
type CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
type CurrentUserMemoryApplicationService = Annotated[
    UserMemoryApplicationService, Depends(get_user_memory_application_service)
]


def get_task_application_service(
    container: CurrentContainer,
) -> AgentTaskApplicationService:
    """在接口边界取得已装配的运行器，再交给装配工厂。"""
    from agent_platform.bootstrap.wiring import (
        get_agent_task_application_service,
    )

    return get_agent_task_application_service()


type CurrentTaskApplicationService = Annotated[
    AgentTaskApplicationService, Depends(get_task_application_service)
]


def get_task_event_store() -> TaskEvents:
    """事件存储的具体实现由装配层决定。"""
    from agent_platform.bootstrap.wiring import get_task_events

    return get_task_events()


type CurrentTaskEvents = Annotated[TaskEvents, Depends(get_task_event_store)]


def get_tracing() -> LangfuseTracing:
    """接口通过装配入口取得追踪能力，不自行创建 SDK。"""
    from agent_platform.bootstrap.wiring import get_tracing as assembled_tracing

    return assembled_tracing()


CurrentTracing = Annotated[LangfuseTracing, Depends(get_tracing)]
