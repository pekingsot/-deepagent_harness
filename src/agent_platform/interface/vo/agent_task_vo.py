"""任务接口的请求和响应，不暴露内部执行上下文。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agent_platform.application.dto.agent_task_dto import CreateAgentTask
from agent_platform.domain.aggregates.agent_task import AgentTask, AgentTaskStatus
from agent_platform.domain.types.common import Identifier


class CreateAgentTaskRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    agent: Identifier = "task_planning"  # Agent 注册名称
    prompt: str = Field(min_length=1, max_length=32000, pattern=r"\S")  # 用户任务内容

    def to_command(self) -> CreateAgentTask:
        """转换为应用命令，身份只能由服务端提供。"""
        return CreateAgentTask(agent=self.agent, prompt=self.prompt)


class AgentTaskResponse(BaseModel):
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
            title=task.title,
            prompt=task.prompt,
            attempt=task.attempt,
            status=task.status,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class SendTaskMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID  # 客户端生成的消息编号，用于识别重复提交
    content: str = Field(
        strict=True, min_length=1, max_length=32000, pattern=r"\S",
    )  # 同一会话中的新输入


class RenameTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        strict=True, min_length=1, max_length=120, pattern=r"\S",
    )  # 新的会话名称
