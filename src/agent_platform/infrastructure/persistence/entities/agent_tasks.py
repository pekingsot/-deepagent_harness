from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from agent_platform.infrastructure.persistence.entities.base import BaseTable


class AgentTaskRecord(BaseTable):
    """任务业务数据映射，与领域聚合分开。"""

    __tablename__ = "agent_tasks"

    deletion_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )  # 删除意图；清理完成后随会话物理删除

    __table_args__ = (
        Index(
            "idx_agent_tasks_owner_created",
            "tenant_id",
            "project_id",
            "user_id",
            "created_at",
        ),
        CheckConstraint(
            "attempt >= 0",
            name="ck_agent_tasks_attempt_nonnegative",
        ),
        CheckConstraint(
            "length(trim(prompt)) > 0",
            name="ck_agent_tasks_prompt_not_blank",
        ),
        CheckConstraint(
            "status IN ("
            "'queued', 'running', 'cancelling', 'waiting_human', "
            "'succeeded', 'failed', 'cancelled'"
            ")",
            name="ck_agent_tasks_status",
        ),
    )

    execution_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )  # 任务编号，对应 AgentTask.id

    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )  # 所属租户编号

    project_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )  # 所属项目标识

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )  # 发起任务的用户编号

    thread_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
    )  # 会话线程编号

    trace_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
    )  # 任务关联的追踪编号

    agent: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )  # 执行任务的 Agent 注册名称

    title: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        server_default="新会话",
    )  # 会话名称，与首条输入分开保存

    prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )  # 用户提交的任务要求

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )  # 当前业务状态

    result: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )  # 任务成功后的最终结果

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )  # 任务失败原因

    attempt: Mapped[int] = mapped_column(
        nullable=False,
    )  # 已开始执行的次数

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )  # 任务创建时间

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )  # 最近一次业务状态变更时间
