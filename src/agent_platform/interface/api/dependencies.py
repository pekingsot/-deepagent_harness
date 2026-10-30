from hmac import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent_platform.application.interfaces.task_events import TaskEvents

from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)
from agent_platform.application.services.user_memory_application_service import (
    UserMemoryApplicationService,
)
from agent_platform.bootstrap.container import Container
from agent_platform.bootstrap.settings import get_settings
from agent_platform.domain.types.common import Principal


def get_container(request: Request) -> Container:
    container = request.app.state.container
    if not isinstance(container, Container):
        raise RuntimeError("Container not initialized")
    return container


bearer = HTTPBearer(auto_error=False)


def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    """仅开发环境接受显式配置的联调身份，正式环境等待认证适配器。"""
    settings = get_settings()
    if (
        settings.environment != "development"
        or settings.development_token is None
        or settings.development_principal is None
    ):
        raise HTTPException(status_code=501, detail="尚未配置认证适配器或开发联调身份")
    expected = settings.development_token.get_secret_value()
    if (
        not expected
        or credentials is None
        or not compare_digest(credentials.credentials.encode("utf-8"), expected.encode("utf-8"))
    ):
        raise HTTPException(
            status_code=401,
            detail="缺少或无效的访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return settings.development_principal


def get_user_memory_application_service(
    container: Annotated[Container, Depends(get_container)],
) -> UserMemoryApplicationService:
    """只有接口实际依赖记忆服务时才组装，不向应用层传递 Request 或 Container。"""
    from agent_platform.bootstrap.wiring import create_user_memory_application_service

    return create_user_memory_application_service(container.database)


type CurrentContainer = Annotated[Container, Depends(get_container)]
type CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
type CurrentUserMemoryApplicationService = Annotated[
    UserMemoryApplicationService, Depends(get_user_memory_application_service)
]


def get_task_application_service() -> AgentTaskApplicationService:
    """通过无参工厂取得服务，路由不参与依赖装配。"""
    from agent_platform.bootstrap.wiring import get_agent_task_application_service

    return get_agent_task_application_service()


type CurrentTaskApplicationService = Annotated[
    AgentTaskApplicationService, Depends(get_task_application_service)
]


def get_task_event_store() -> TaskEvents:
    """事件存储的具体实现由装配层决定。"""
    from agent_platform.bootstrap.wiring import get_task_events

    return get_task_events()


type CurrentTaskEvents = Annotated[TaskEvents, Depends(get_task_event_store)]
