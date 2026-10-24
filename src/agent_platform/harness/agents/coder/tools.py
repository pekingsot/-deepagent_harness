from langchain_core.tools import BaseTool

from agent_platform.domain.common.models import RunContext


def build_tools(context: RunContext) -> list[BaseTool]:
    """Select this agent's authorized tools; implementations belong in harness/tools."""
    return []
