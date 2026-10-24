from agent_platform.domain.common.models import RunContext
from agent_platform.harness.agents.contracts import ContextMiddleware


def build_middleware(context: RunContext) -> list[ContextMiddleware]:
    """Select this agent's middleware; implementations belong in harness/middleware."""
    return []
