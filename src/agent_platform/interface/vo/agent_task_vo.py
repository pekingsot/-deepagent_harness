"""任务接口的请求和响应，不暴露内部执行上下文。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agent_platform.application.dto.agent_task_dto import CreateAgentTask, TaskPlanItem
from agent_platform.domain.aggregates.agent_task import AgentTask, AgentTaskStatus
from agent_platform.domain.types.common import Identifier
from agent_platform.domain.types.task_execution import TaskExecution


class CreateAgentTaskRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    agent: Identifier = "task_planning"  # Agent 注册名称
    prompt: str = Field(min_length=1, max_length=32000, pattern=r"\S")  # 用户任务内容

    def to_command(self) -> CreateAgentTask:
        """转换为应用命令，身份只能由服务端提供。"""
        return CreateAgentTask(agent=self.agent, prompt=self.prompt)


class AgentTaskResponse(BaseModel):
    deletion_requested: bool = False  # 删除进行中，客户端禁止继续输入但允许重试清理
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID  # 任务编号
    title: str  # 可修改的会话名称
    prompt: str  # 第一条用户输入
    attempt: int  # 当前执行轮次
    status: AgentTaskStatus  # 当前状态
    result: str | None  # 最终结果
    error: str | None  # 失败原因
    created_at: datetime  # 创建时间
    updated_at: datetime  # 最近更新时间

    @classmethod
    def from_task(cls, task: AgentTask) -> "AgentTaskResponse":
        """转换为供前端展示的业务结果。"""
        return cls(
            task_id=task.id,
            deletion_requested=task.deletion_requested,
            title=task.title,
            prompt=task.prompt,
            attempt=task.attempt,
            status=task.status,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class TaskExecutionResponse(BaseModel):
    """某一执行轮次的展示快照，与会话摘要分开。"""

    attempt: int  # 所属轮次
    title: str  # 本轮执行标题
    status: AgentTaskStatus  # 本轮状态
    todos: tuple[TaskPlanItem, ...]  # 本轮步骤
    output: str | None  # 完整或部分结果
    error: str | None  # 此轮失败原因
    created_at: datetime  # 本轮开始时间
    updated_at: datetime  # 快照更新时间

    @classmethod
    def from_execution(cls, execution: TaskExecution) -> "TaskExecutionResponse":
        return cls.model_validate(execution.model_dump())


class SendTaskMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID  # 客户端生成的消息编号，用于识别重复提交
    content: str = Field(
        strict=True,
        min_length=1,
        max_length=32000,
        pattern=r"\S",
    )  # 同一会话中的新输入


class RenameTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        strict=True,
        min_length=1,
        max_length=120,
        pattern=r"\S",
    )  # 新的会话名称
