"""数据库 ORM 映射，与领域聚合根和业务类型分开。"""

from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, Index, String, Text, func
from sqlalchemy.orm import  Mapped, mapped_column

from agent_platform.infrastructure.persistence.entities.base import BaseTable


class UserMemoryRecord(BaseTable):
    """用户在当前租户内的一条长期记忆"""

    __tablename__ = "user_memory"
    __table_args__ = (
        Index(
            "idx_tenant_user",
            "tenant_id",
            "user_id",
        ),
        CheckConstraint("length(trim(content)) > 0", name="ck_memories_content_not_blank"),
    )
    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    embedding: Mapped[list[float]] = mapped_column(
        VECTOR(1024),
        nullable=False,
    )

    embedding_model: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
