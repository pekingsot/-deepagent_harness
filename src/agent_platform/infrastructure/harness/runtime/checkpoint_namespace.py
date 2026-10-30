"""根据可信执行身份生成 Checkpoint 命名空间。"""

from agent_platform.domain.types.common import TaskContext


def checkpoint_thread(context: TaskContext) -> str:
    """隔离租户、项目、用户和任务；恢复时复用相同的上下文。"""
    return ":".join(
        (
            str(context.tenant_id),
            context.project_id,
            str(context.user_id),
            str(context.thread_id),
            str(context.task_id),
        )
    )
