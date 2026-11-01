from typing import Annotated, Literal

from pydantic import Field, JsonValue

from agent_platform.application.dto.trace_context import TraceContext
from agent_platform.domain.types.common import (
    Identifier,
    StrictModel,
    TaskContext,
)


class CreateAgentTask(StrictModel):
    agent: Identifier = "task_planning"  # 要调用的 Agent 注册名
    prompt: str = Field(min_length=1, max_length=32000)  # 用户提交的任务要求


class UserInputPayload(StrictModel):
    type: Literal["user_input"] = "user_input"  # 区分用户输入与工具审批
    question: str = Field(min_length=1)  # 需要用户回答的问题


class ToolApprovalPayload(StrictModel):
    type: Literal["tool_approval"] = "tool_approval"  # 工具审批中断
    tool_name: str  # 待审批的工具名称
    tool_call_id: str  # 本次工具调用编号
    args: dict[str, JsonValue]  # 本次工具调用的可序列化参数


type InterruptPayload = Annotated[
    UserInputPayload | ToolApprovalPayload,
    Field(discriminator="type"),
]


class TaskInterrupt(StrictModel):
    id: str  # 框架分配的中断编号，恢复时必须对应
    payload: InterruptPayload  # 用户提问或工具审批的具体内容


class TextReply(StrictModel):
    type: Literal["user_input"] = "user_input"  # 用户输入回复
    answer: str = Field(min_length=1)  # 用户填写的回答


class ApprovalReply(StrictModel):
    type: Literal["tool_approval"] = "tool_approval"  # 审批回复
    approved: bool  # 是否允许执行工具


type HumanReply = Annotated[
    TextReply | ApprovalReply,
    Field(discriminator="type"),
]


class ResumeAgentTask(StrictModel):
    answers: dict[str, HumanReply] = Field(min_length=1)  # 中断编号到人工回复的映射


class TaskJob(StrictModel):
    trace_context: TraceContext | None = None  # 发送端追踪上下文，旧消息允许为空
    context: TaskContext  # 服务端生成的任务身份和执行上下文
    resume: ResumeAgentTask | None = None  # 为空表示首次执行，否则携带人工回复


class TaskPlanItem(StrictModel):
    """提供给页面展示的任务计划项。"""

    content: str = Field(min_length=1)  # 具体要完成的工作
    status: Literal[
        "pending",
        "in_progress",
        "completed",
    ]  # 待执行、执行中、已完成


class TaskArtifact(StrictModel):
    """任务生成的文本交付物。"""

    path: str = Field(
        pattern=r"^/deliverables/.+",
    )  # 虚拟工作区中的交付物路径
    content: str  # 文件的文本内容，用于预览和下载


class AgentTaskExecutionResult(StrictModel):
    title: str | None = Field(
        default=None, min_length=1, max_length=120
    )  # 当前轮标题，与会话名称分开
    status: Literal["waiting", "completed"]  # 本轮暂停或完成
    interrupts: tuple[TaskInterrupt, ...] = ()  # 等待处理的人工中断
    output: str | None = None  # 本轮执行后的回答
    todos: tuple[TaskPlanItem, ...] = ()  # 当前任务计划
    artifacts: tuple[TaskArtifact, ...] = ()  # 当前保存的文本交付物


class InvalidHumanReplyError(ValueError):
    """人工回复不符合当前中断要求，尚未恢复模型执行。"""


class TaskActivity(StrictModel):
    """工具及子 Agent 的调用动态。"""

    event: Literal[
        "tool_requested",
        "tool_returned",
        "tool_failed",
    ]  # 请求调用、返回结果、返回错误
    tool_name: str  # 工具名称，子 Agent 委派工具为 task
    call_id: str  # 关联同一次工具调用的编号
    subagent: str | None = None  # 被委派的子 Agent 名称
    file_path: str | None = None  # 文件工具操作的虚拟路径
    elapsed_ms: int | None = Field(
        default=None,
        ge=0,
    )  # 从观察到调用请求至收到返回的毫秒数
