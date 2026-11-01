"""Persist execution identity and support keyset maintenance scans."""

import sqlalchemy as sa
from alembic import op

revision = "b72d19eaf305"
down_revision = "a918c32df004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_tasks", sa.Column("execution_id", sa.Uuid(), nullable=True))
    op.drop_index("idx_agent_tasks_recovery", table_name="agent_tasks")
    op.drop_index("idx_agent_tasks_deletion", table_name="agent_tasks")
    op.create_index(
        "idx_agent_tasks_recovery",
        "agent_tasks",
        ["id"],
        postgresql_where=sa.text("status IN ('running', 'cancelling')"),
    )
    op.create_index(
        "idx_agent_tasks_deletion",
        "agent_tasks",
        ["id"],
        postgresql_where=sa.text("deletion_requested = true"),
    )


def downgrade() -> None:
    op.drop_index("idx_agent_tasks_deletion", table_name="agent_tasks")
    op.drop_index("idx_agent_tasks_recovery", table_name="agent_tasks")
    op.create_index(
        "idx_agent_tasks_recovery",
        "agent_tasks",
        ["updated_at"],
        postgresql_where=sa.text("status IN ('running', 'cancelling')"),
    )
    op.create_index(
        "idx_agent_tasks_deletion",
        "agent_tasks",
        ["updated_at"],
        postgresql_where=sa.text("deletion_requested = true"),
    )
    op.drop_column("agent_tasks", "execution_id")
