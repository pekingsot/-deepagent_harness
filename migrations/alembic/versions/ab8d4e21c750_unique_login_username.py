"""登录不再填写公司代码，用户名调整为全系统唯一。"""

import sqlalchemy as sa
from alembic import op

revision = "ab8d4e21c750"
down_revision = "9ab31fe02d16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 防止检查重名与建立约束之间有并发写入，不修改任何已有账号。
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE sys_user IN SHARE ROW EXCLUSIVE MODE"))
    duplicate = connection.execute(
        sa.text("SELECT 1 FROM sys_user GROUP BY username HAVING COUNT(*) > 1 LIMIT 1")
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "存在跨公司重复的登录名，请先人工确认并修改重名账号，再重新执行迁移；"
            "本次不会自动改名、删除用户或转移数据。"
        )
    op.create_unique_constraint("uq_sys_user_username", "sys_user", ["username"])
    op.drop_constraint("uq_sys_user_tenant_username", "sys_user", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_sys_user_tenant_username", "sys_user", ["tenant_id", "username"]
    )
    op.drop_constraint("uq_sys_user_username", "sys_user", type_="unique")
