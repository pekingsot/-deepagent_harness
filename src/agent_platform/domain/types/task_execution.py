"""会话各轮执行的计划与结果快照，不依赖 Agent 框架。"""

from datetime import UTC, datetime

from pydantic import Field

from agent_platform.domain.aggregates.agent_task import AgentTaskStatus
from agent_platform.domain.types.common import StrictModel


class TaskExecutionStep(StrictModel):
    content: str = Field(min_length=1)  # 本轮计划中的具体工作
    status: str = Field(pattern="^(pending|in_progress|completed)$")  # 步骤进度


class TaskExecution(StrictModel):
    attempt: int = Field(ge=1)  # 所属轮次，人工恢复不新增轮次
    title: str = Field(min_length=1, max_length=120, pattern=r"\S")  # 本轮执行标题
    status: AgentTaskStatus  # 此轮状态，不随下一轮排队覆盖
    todos: tuple[TaskExecutionStep, ...] = ()  # 此轮最后保存的步骤
    output: str | None = None  # 此轮完整结果或停止、失败前的部分结果
    error: str | None = None  # 此轮失败原因
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 轮次开始时间
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 快照更新时间
