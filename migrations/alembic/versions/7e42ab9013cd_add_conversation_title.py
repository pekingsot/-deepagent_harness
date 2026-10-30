"""增加会话名称，并回填旧任务中原本保留的输入与回答。"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "7e42ab9013cd"
down_revision = "622b123e76fc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_tasks",
        sa.Column("title", sa.String(120), server_default="新会话", nullable=False),
    )
    connection = op.get_bind()
    connection.execute(sa.text(
        "UPDATE agent_tasks SET title = COALESCE(NULLIF(left(trim(prompt), 60), ''), '新会话')"
    ))
    # 旧实现只保留首条输入和最后回答；不能据此恢复其他中间消息。
    rows = connection.execute(sa.text(
        "SELECT id, prompt, result, status, created_at, updated_at FROM agent_tasks ORDER BY created_at"
    )).mappings()
    for task in rows:
        has_user = connection.scalar(sa.text(
            "SELECT EXISTS (SELECT 1 FROM agent_task_messages WHERE task_id = :id AND role = 'user')"
        ), {"id": task["id"]})
        if not has_user:
            state = (
                "applied" if task["status"] == "succeeded"
                else "processing" if task["status"] in {"running", "waiting_human"}
                else "pending" if task["status"] == "queued" else "failed"
            )
            connection.execute(sa.text(
                "INSERT INTO agent_task_messages (id, task_id, role, content, state, created_at) "
                "VALUES (:id, :task_id, 'user', :content, :state, :created_at)"
            ), {"id": uuid4(), "task_id": task["id"], "content": task["prompt"],
                "state": state, "created_at": task["created_at"]})
        has_answer = connection.scalar(sa.text(
            "SELECT EXISTS (SELECT 1 FROM agent_task_messages "
            "WHERE task_id = :id AND role = 'assistant' AND content = :content)"
        ), {"id": task["id"], "content": task["result"]})
        if task["result"] and not has_answer:
            connection.execute(sa.text(
                "INSERT INTO agent_task_messages (id, task_id, role, content, state, created_at) "
                "VALUES (:id, :task_id, 'assistant', :content, 'applied', :created_at)"
            ), {"id": uuid4(), "task_id": task["id"], "content": task["result"],
                "created_at": task["updated_at"]})
    # 修正旧版成功或失败任务中遗留的未完成消息状态。
    connection.execute(sa.text(
        "UPDATE agent_task_messages AS m "
        "SET state = CASE WHEN t.status = 'succeeded' THEN 'applied' ELSE 'failed' END "
        "FROM agent_tasks AS t WHERE m.task_id = t.id AND m.role = 'user' "
        "AND m.state IN ('pending', 'processing') "
        "AND t.status IN ('succeeded', 'failed', 'cancelled')"
    ))


def downgrade() -> None:
    # 保留已回填的消息，避免撤销标题字段时删除用户历史。
    op.drop_column("agent_tasks", "title")
