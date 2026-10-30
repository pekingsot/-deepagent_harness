from agent_platform.domain.types.common import StrictModel, TaskContext


class Sandbox(StrictModel):
    id: str
    context: TaskContext
    provider: str
