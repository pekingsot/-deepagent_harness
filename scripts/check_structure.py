"""Standard-library structure checks; no external services required."""

import ast
import tomllib
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["requires-python"] == ">=3.12,<3.13"
    count = 0
    for path in (root / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count += 1
        if "domain" in path.relative_to(root).parts:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    continue
                assert all(not module.startswith(
                    ("fastapi", "sqlalchemy", "deepagents", "langchain", "langgraph")
                ) for module in modules), f"Domain dependency violation: {path}"
    for agent in ("orchestrator", "researcher", "coder", "reviewer"):
        base = root / "src/agent_platform/harness/agents" / agent
        for file in ("definition.py", "system_prompt.md", "tools.py", "middleware.py", "backend.py"):
            assert (base / file).is_file(), f"Missing {agent}/{file}"
        assert list((base / "skills").glob("*/SKILL.md"))
    print(f"Scaffold structure and {count} Python source files checked.")


if __name__ == "__main__":
    main()
