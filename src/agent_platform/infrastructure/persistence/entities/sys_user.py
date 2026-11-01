"""用户表映射，密码只存 Argon2 摘要。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agent_platform.infrastructure.persistence.entities.base import BaseTable


class UserRecord(BaseTable):
    __tablename__ = "sys_user"
    __table_args__ = (
        Index("idx_sys_user_tenant_id", "tenant_id", "id"),
        UniqueConstraint("username", name="uq_sys_user_username"),
        CheckConstraint("role IN ('admin', 'user')", name="ck_sys_user_role"),
        CheckConstraint("auth_revision >= 1", name="ck_sys_user_auth_revision"),
        CheckConstraint("length(trim(display_name)) > 0", name="ck_sys_user_display_name"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), Identity(), primary_key=True
    )  # 用户主键
    tenant_id: Mapped[int] = mapped_column(ForeignKey("sys_tenant.id"), nullable=False)  # 所属租户
    username: Mapped[str] = mapped_column(String(64))  # 全系统唯一的登录名
    display_name: Mapped[str] = mapped_column(String(80))  # 显示名称
    password_hash: Mapped[str] = mapped_column(String(512))  # 不可逆密码摘要
    role: Mapped[str] = mapped_column(String(16), default="user")  # 租户内角色
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # 是否可用
    auth_revision: Mapped[int] = mapped_column(Integer, default=1)  # 登录凭据修订号
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )  # 创建时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )  # 更新时间
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # 最近登录
