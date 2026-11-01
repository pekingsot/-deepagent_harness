"""租户表映射，主键使用整数自增。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Identity,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agent_platform.infrastructure.persistence.entities.base import BaseTable


class TenantRecord(BaseTable):
    __tablename__ = "sys_tenant"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="ck_sys_tenant_name"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), Identity(), primary_key=True
    )  # 租户主键
    code: Mapped[str] = mapped_column(String(64), unique=True)  # 唯一公司代码
    name: Mapped[str] = mapped_column(String(80))  # 公司名称
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # 是否启用
    default_project_id: Mapped[str] = mapped_column(String(64), default="default")  # 默认项目
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )  # 创建时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )  # 更新时间
