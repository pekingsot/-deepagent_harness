"""Canonical run context; defined in Domain to keep dependencies pointing inward."""

from agent_platform.domain.common.models import RunContext


def checkpoint_thread(context: RunContext) -> str:
    return ":".join(
        (
            context.tenant_id,
            context.project_id,
            context.user_id,
            str(context.thread_id),
            str(context.run_id)
        )
    )
