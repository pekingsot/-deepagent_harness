from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from agent_platform.infrastructure.persistence.entities.base import BaseTable


class AgentTaskMessageRecord(BaseTable):
    """任务会话中的消息记录。"""

    __tablename__ = "agent_task_messages"

    __table_args__ = (
        Index(
            "idx_agent_task_messages_task_position",
            "task_id",
            "position",
        ),
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_agent_task_messages_role",
        ),
        CheckConstraint(
            "state IN ('pending', 'processing', 'applied', 'failed', 'cancelled')",
            name="ck_agent_task_messages_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )  # 消息唯一编号

    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_tasks.id"),
        nullable=False,
    )  # 所属任务会话编号

    position: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        nullable=False,
    )  # 数据库生成的递增顺序，用于按顺序展示消息

    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )  # 消息发送方：user 或 assistant

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )  # 消息正文

    state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )  # 待处理、处理中、已处理、失败或取消

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )  # 消息创建时间
