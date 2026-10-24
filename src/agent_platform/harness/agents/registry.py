from agent_platform.harness.agents.contracts import AgentDefinition


class AgentRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, AgentDefinition] = {}

    def register(self, definition: AgentDefinition) -> None:
        if not isinstance(definition, AgentDefinition):
            raise TypeError("Definitions must inherit AgentDefinition")
        if definition.name in self._definitions:
            raise ValueError(f"Duplicate agent: {definition.name}")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> AgentDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise ValueError(f"Unknown agent: {name}") from exc

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._definitions)

    def validate(self) -> None:
        def visit(name: str, path: frozenset[str]) -> None:
            if name in path:
                raise ValueError(f"Cyclic subagent graph: {name}")
            for child in self.get(name).children:
                visit(child, path | {name})
        for name in self.names:
            visit(name, frozenset())
