"""支持运行中取消与独立的消息取消状态。"""

from alembic import op

revision = "d40c6e2189ab"
down_revision = "ab8d4e21c750"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_tasks") as batch:
        batch.drop_constraint("ck_agent_tasks_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_tasks_status",
            "status IN ('queued', 'running', 'cancelling', 'waiting_human', "
            "'succeeded', 'failed', 'cancelled')",
        )
    with op.batch_alter_table("agent_task_messages") as batch:
        batch.drop_constraint("ck_agent_task_messages_state", type_="check")
        batch.create_check_constraint(
            "ck_agent_task_messages_state",
            "state IN ('pending', 'processing', 'applied', 'failed', 'cancelled')",
        )


def downgrade() -> None:
    # 降级前需停掉消费者；旧版没有停止中和消息取消的独立状态。
    op.execute("UPDATE agent_tasks SET status = 'cancelled' WHERE status = 'cancelling'")
    op.execute("UPDATE agent_task_messages SET state = 'failed' WHERE state = 'cancelled'")
    with op.batch_alter_table("agent_tasks") as batch:
        batch.drop_constraint("ck_agent_tasks_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_tasks_status",
            "status IN ('queued', 'running', 'waiting_human', 'succeeded', 'failed', 'cancelled')",
        )
    with op.batch_alter_table("agent_task_messages") as batch:
        batch.drop_constraint("ck_agent_task_messages_state", type_="check")
        batch.create_check_constraint(
            "ck_agent_task_messages_state",
            "state IN ('pending', 'processing', 'applied', 'failed')",
        )
