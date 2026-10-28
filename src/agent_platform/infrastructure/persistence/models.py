"""Use SQLAlchemy's current typed declarative API for future ORM models."""
from datetime import datetime
from sqlalchemy import (
    Index, String, CheckConstraint, DateTime, Text, func,BigInteger, Identity
)
from pgvector.sqlalchemy import VECTOR

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    """所有orm模型共用的基类"""
    pass


class Memory(Base):
    """用户在当前租户内的一条长期记忆"""
    __tablename__ = "memories"
    __table_args__ = (
        Index(
            "idx_tenant_user",
            "tenant_id",
            "user_id",
        ),
        CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_memories_content_not_blank"
        )

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
