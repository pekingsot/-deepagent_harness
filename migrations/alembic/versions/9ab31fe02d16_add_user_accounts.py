"""创建租户和用户表，全部使用整数主键。"""

import sqlalchemy as sa
from alembic import op

revision = "9ab31fe02d16"
down_revision = "7e42ab9013cd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sys_tenant",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("default_project_id", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_sys_tenant_name"),
    )
    op.create_table(
        "sys_user",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("sys_tenant.id"), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("auth_revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "username", name="uq_sys_user_tenant_username"),
        sa.CheckConstraint("role IN ('admin', 'user')", name="ck_sys_user_role"),
        sa.CheckConstraint("auth_revision >= 1", name="ck_sys_user_auth_revision"),
        sa.CheckConstraint("length(trim(display_name)) > 0", name="ck_sys_user_display_name"),
    )
    op.create_index("idx_sys_user_tenant_id", "sys_user", ["tenant_id", "id"])
    # 避开旧开发身份的编号，避免首个真实账号意外继承历史测试任务和记忆。
    for table, column in (("sys_tenant", "tenant_id"), ("sys_user", "user_id")):
        op.execute(
            sa.text(f"""
            SELECT setval(pg_get_serial_sequence('{table}', 'id'),
                GREATEST(
                    COALESCE((SELECT MAX({column}) FROM agent_tasks), 0),
                    COALESCE((SELECT MAX({column}) FROM user_memory), 0),
                    1
                ), true)
        """)
        )


def downgrade() -> None:
    op.drop_table("sys_user")
    op.drop_table("sys_tenant")
