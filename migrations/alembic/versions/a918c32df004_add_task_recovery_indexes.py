"""后台补偿和删除扫描的部分索引，避免扫描全部会话。"""

import sqlalchemy as sa
from alembic import op

revision = "a918c32df004"
down_revision = "f17a902bd631"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_agent_tasks_recovery", "agent_tasks", ["updated_at"],
        postgresql_where=sa.text("status IN ('running', 'cancelling')"),
    )
    op.create_index(
        "idx_agent_tasks_deletion", "agent_tasks", ["updated_at"],
        postgresql_where=sa.text("deletion_requested = true"),
    )


def downgrade() -> None:
    op.drop_index("idx_agent_tasks_deletion", table_name="agent_tasks")
    op.drop_index("idx_agent_tasks_recovery", table_name="agent_tasks")
