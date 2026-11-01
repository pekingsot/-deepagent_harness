"""按执行轮次保存标题、步骤和结果，不改变会话标题。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e62a8f31c904"
down_revision = "d40c6e2189ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_task_executions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("todos", postgresql.JSONB(), nullable=False),
        sa.Column("output", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "attempt", name="uq_agent_task_executions_round"),
        sa.CheckConstraint("attempt >= 1", name="ck_agent_task_executions_attempt"),
        sa.CheckConstraint("length(trim(title)) > 0", name="ck_agent_task_executions_title"),
    )


def downgrade() -> None:
    op.drop_table("agent_task_executions")
