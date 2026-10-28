from typing import Annotated, Literal

from pydantic import Field, JsonValue

from agent_platform.domain.common.models import (
    Identifier,
    StrictModel,
)


class CreateRun(StrictModel):
    agent: Identifier = "orchestrator"
    prompt: str = Field(min_length=1, max_length=32000)


class UserInputPayload(StrictModel):
    type: Literal["user_input"] = "user_input"
    question: str = Field(min_length=1)


class ToolApprovalPayload(StrictModel):
    type: Literal["tool_approval"] = "tool_approval"
    tool_name: str
    tool_call_id: str
    args: dict[str, JsonValue]


type InterruptPayload = Annotated[
    UserInputPayload | ToolApprovalPayload,
    Field(discriminator="type"),
]


class RuntimeInterrupt(StrictModel):
    id: str
    payload: InterruptPayload


class TextReply(StrictModel):
    type: Literal["user_input"] = "user_input"
    answer: str = Field(min_length=1)


class ApprovalReply(StrictModel):
    type: Literal["tool_approval"] = "tool_approval"
    approved: bool


type HumanReply = Annotated[
    TextReply | ApprovalReply,
    Field(discriminator="type"),
]


class ResumeRun(StrictModel):
    answers: dict[str, HumanReply] = Field(min_length=1)


class RuntimeResult(StrictModel):
    status: Literal["waiting", "completed"]
    interrupts: tuple[RuntimeInterrupt, ...] = ()
    output: str | None = None