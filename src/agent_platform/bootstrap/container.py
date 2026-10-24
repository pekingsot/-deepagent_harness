"""Composition root. Bind ABC ports to infrastructure adapters here.

Keep tenant-specific dependencies inside a request/run scope.
No database connections, model clients, or worker loops are created on import.
"""

from agent_platform.bootstrap.settings import Settings


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
