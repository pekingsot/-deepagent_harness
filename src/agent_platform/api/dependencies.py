from typing import Annotated

from fastapi import Depends, HTTPException, Request

from agent_platform.bootstrap.container import Container
from agent_platform.domain.common.models import Principal


def get_container(request: Request) -> Container:
    container = request.app.state.container
    if not isinstance(container, Container):
        raise RuntimeError("Container not initialized")
    return container


def get_principal() -> Principal:
    # Fail closed until an authentication adapter is bound.
    raise HTTPException(status_code=501, detail="Authentication adapter is not configured")


type CurrentContainer = Annotated[Container, Depends(get_container)]
type CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
