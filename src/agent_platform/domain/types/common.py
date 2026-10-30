from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

type Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, validate_default=True)



class Principal(StrictModel):
    """身份主体"""
    tenant_id: Annotated[int, Field(gt=0, le=9223372036854775807)]  # 可信租户编号
    user_id: Annotated[int, Field(gt=0, le=9223372036854775807)]  # 可信用户编号
    project_id: Identifier  # 当前业务项目标识


class TaskContext(Principal):
    """任务的一系列参数"""
    task_id: UUID = Field(default_factory=uuid4)  # 当前任务编号，恢复任务时必须复用
    thread_id: UUID = Field(default_factory=uuid4)  # 会话线程编号
    trace_id: UUID = Field(default_factory=uuid4)  # 当前调用的追踪编号


class NotFoundError(Exception):
    """Unknown and inaccessible resources have the same response."""


class ConflictError(Exception):
    """Illegal transition or concurrent modification."""
