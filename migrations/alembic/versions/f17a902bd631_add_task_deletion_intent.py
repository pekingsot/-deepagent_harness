"""永久删除期间阻止会话重新执行。"""

import sqlalchemy as sa
from alembic import op

revision = "f17a902bd631"
down_revision = "e62a8f31c904"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_tasks",
        sa.Column("deletion_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("agent_tasks", "deletion_requested")
