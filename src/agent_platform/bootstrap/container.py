"""Composition root. Bind ABC ports to infrastructure adapters here.

Keep tenant-specific dependencies inside a request/run scope.
No database connections, model clients, or worker loops are created on import.
"""
from agent_platform.application.ports.runtime import AgentRuntime
from agent_platform.bootstrap.settings import Settings
from agent_platform.infrastructure.persistence.database import Database


class Container:
    def __init__(self, *, settings: Settings, runtime: AgentRuntime, database: Database) -> None:
        self.settings = settings
        self.runtime = runtime
        self.database = database
