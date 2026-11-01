"""执行轮次快照的 ORM，历史轮次不受会话重命名影响。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agent_platform.infrastructure.persistence.entities.base import BaseTable


class AgentTaskExecutionRecord(BaseTable):
    __tablename__ = "agent_task_executions"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt", name="uq_agent_task_executions_round"),
        CheckConstraint("attempt >= 1", name="ck_agent_task_executions_attempt"),
        CheckConstraint("length(trim(title)) > 0", name="ck_agent_task_executions_title"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)  # 快照整数主键
    task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("agent_tasks.id", ondelete="CASCADE")
    )  # 所属会话
    attempt: Mapped[int] = mapped_column(nullable=False)  # 所属执行轮次
    title: Mapped[str] = mapped_column(String(120), nullable=False)  # 本轮标题
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # 本轮状态
    todos: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)  # 本轮步骤快照
    output: Mapped[str | None] = mapped_column(Text)  # 完整或部分执行结果
    error: Mapped[str | None] = mapped_column(Text)  # 失败原因
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 开始时间
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 更新时间
