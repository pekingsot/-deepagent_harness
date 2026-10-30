"""Agent 任务聚合根：维护任务身份、生命周期和状态一致性。"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from agent_platform.domain.types.common import (
    ConflictError,
    Identifier,
    NotFoundError,
    Principal,
    StrictModel,
    TaskContext,
)


class AgentTaskStatus(StrEnum):
    QUEUED = "queued"  # 已创建，等待执行
    RUNNING = "running"  # 正在执行
    WAITING_HUMAN = "waiting_human"  # 等待用户输入或审批
    SUCCEEDED = "succeeded"  # 已成功完成
    FAILED = "failed"  # 执行失败
    CANCELLED = "cancelled"  # 已取消


_TRANSITIONS: dict[AgentTaskStatus, frozenset[AgentTaskStatus]] = {
    AgentTaskStatus.QUEUED: frozenset({AgentTaskStatus.RUNNING, AgentTaskStatus.CANCELLED}),
    AgentTaskStatus.RUNNING: frozenset(
        {
            AgentTaskStatus.WAITING_HUMAN,
            AgentTaskStatus.SUCCEEDED,
            AgentTaskStatus.FAILED,
        }
    ),
    AgentTaskStatus.WAITING_HUMAN: frozenset(
        {
            AgentTaskStatus.RUNNING,
            AgentTaskStatus.CANCELLED,
        }
    ),
    # 上一轮成功后，允许同一会话进入下一轮。
    AgentTaskStatus.SUCCEEDED: frozenset({
        AgentTaskStatus.QUEUED,
    }),
    AgentTaskStatus.FAILED: frozenset(),
    AgentTaskStatus.CANCELLED: frozenset(),
}


class AgentTask(StrictModel):
    """一个用户任务对应一个聚合；业务方法返回新的不可变任务对象。"""

    context: TaskContext  # 任务编号、可信归属及当前执行上下文
    title: str = Field(default="新会话", min_length=1, max_length=120, pattern=r"\S")  # 会话名称
    agent: Identifier = "task_planning"  # 执行该任务的 Agent 注册名
    prompt: str = Field(min_length=1, max_length=32000)  # 用户提交的任务要求
    status: AgentTaskStatus = AgentTaskStatus.QUEUED  # 当前任务状态
    result: str | None = None  # 成功完成后的最终结果
    error: str | None = None  # 失败原因，只在失败状态保存
    attempt: int = Field(default=0, ge=0)  # 已开始的执行次数，人工恢复不另算一次
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 创建时间
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 最近状态变更时间

    @property
    def id(self) -> UUID:
        """任务聚合的唯一身份，与执行上下文中的任务编号保持一致。"""
        return self.context.task_id

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        """任务要求不能只有空白字符。"""
        if not value.strip():
            raise ValueError("任务要求不能为空白")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        """从仓储重建聚合时，也检查结果、错误与状态是否一致。"""
        if self.status == AgentTaskStatus.FAILED and not (self.error and self.error.strip()):
            raise ValueError("失败任务必须提供错误原因")
        if self.error is not None and self.status != AgentTaskStatus.FAILED:
            raise ValueError("只有失败任务可以保存错误原因")
        if self.result is not None and self.status != AgentTaskStatus.SUCCEEDED:
            raise ValueError("只有成功任务可以保存最终结果")
        if self.status == AgentTaskStatus.SUCCEEDED and not (self.result and self.result.strip()):
            raise ValueError("成功任务必须提供最终结果")
        return self

    def ensure_accepts_messages(self) -> None:
        """判断当前会话是否允许追加普通消息。"""
        if self.status == AgentTaskStatus.WAITING_HUMAN:
            raise ConflictError(
                "当前正在等待人工回复，请先回答待处理的问题"
            )

        if self.status in {
            AgentTaskStatus.FAILED,
            AgentTaskStatus.CANCELLED,
        }:
            raise ConflictError(
                "失败或取消的会话暂不支持直接续问"
            )

    def queue_next(self) -> Self:
        """上一轮成功后，将同一会话重新安排为待执行。"""
        return self._transition(AgentTaskStatus.QUEUED)

    def start(self) -> Self:
        """开始排队中的任务，增加一次执行计数。"""
        if self.status != AgentTaskStatus.QUEUED:
            raise ConflictError("只有排队中的任务可以开始执行")
        return self._transition(AgentTaskStatus.RUNNING, attempt=self.attempt + 1)

    def wait_for_user(self) -> Self:
        """执行中的任务等待人工输入或审批。"""
        return self._transition(AgentTaskStatus.WAITING_HUMAN)

    def resume(self) -> Self:
        """恢复等待人工的同一个任务，不重复增加执行次数。"""
        self.ensure_can_resume()
        return self._transition(AgentTaskStatus.RUNNING)

    def ensure_can_resume(self) -> None:
        """恢复执行前先校验业务条件，不提前改变任务状态。"""
        if self.status != AgentTaskStatus.WAITING_HUMAN:
            raise ConflictError("只有等待人工的任务可以恢复")

    def ensure_owned_by(self, principal: Principal) -> None:
        """当前任务只允许所属租户、项目和用户操作。"""
        if (
            self.context.tenant_id != principal.tenant_id
            or self.context.project_id != principal.project_id
            or self.context.user_id != principal.user_id
        ):
            raise NotFoundError("任务不存在或无权访问")

    def complete(self, result: str) -> Self:
        """提交执行结果并完成任务。"""
        return self._transition(AgentTaskStatus.SUCCEEDED, result=result)

    def fail(self, reason: str) -> Self:
        """记录执行失败及其原因。"""
        return self._transition(AgentTaskStatus.FAILED, error=reason)

    def cancel(self) -> Self:
        """取消排队或等待人工的任务，运行中的任务尚无停止能力。"""
        return self._transition(AgentTaskStatus.CANCELLED)

    def _transition(
        self,
        target: AgentTaskStatus,
        *,
        result: str | None = None,
        error: str | None = None,
        attempt: int | None = None,
    ) -> Self:
        """统一检查状态迁移；外部用例通过业务方法表达意图。"""
        if target not in _TRANSITIONS[self.status]:
            raise ConflictError(f"不允许从 {self.status} 转换为 {target}")

        data = self.model_dump()
        data.update(
            status=target,
            result=result,
            error=error,
            attempt=self.attempt if attempt is None else attempt,
            updated_at=datetime.now(UTC),
        )
        # return type(self).model_validate(data)
        return self.model_validate(data)
        # return AgentTask.model_validate(data)

    def rename(self, title: str) -> Self:
        """更新展示名称，不改变会话身份或模型上下文。"""
        title = title.strip()
        if not title:
            raise ValueError("会话名称不能为空白")
        data = self.model_dump()
        data.update(title=title, updated_at=datetime.now(UTC))
        return type(self).model_validate(data)
