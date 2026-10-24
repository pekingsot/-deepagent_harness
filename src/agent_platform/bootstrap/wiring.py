"""Composition entry point for future adapter bindings."""

from agent_platform.bootstrap.container import Container
from agent_platform.bootstrap.settings import Settings


def build_container(settings: Settings | None = None) -> Container:
    return Container(settings or Settings())
