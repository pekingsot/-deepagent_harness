"""检查目录、领域依赖和 Agent 资源，不连接外部服务。"""

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
                assert all(
                    not module.startswith(
                        ("fastapi", "sqlalchemy", "deepagents", "langchain", "langgraph")
                    )
                    for module in modules
                ), f"Domain dependency violation: {path}"
    for agent in ("task_planning", "researcher", "coder", "reviewer"):
        base = root / "src/agent_platform/infrastructure/harness/agents" / agent
        for file in ("agent.py", "system_prompt.md"):
            assert (base / file).is_file(), f"Missing {agent}/{file}"
        assert list((base / "skills").glob("*/SKILL.md"))
    for file in (
        "application/services/user_memory_application_service.py",
        "application/services/agent_task_application_service.py",
        "domain/aggregates/agent_task.py",
        "domain/services/agent_task_domain_service.py",
        "domain/types/common.py",
        "domain/types/memory_match.py",
        "domain/repositories/user_memory_repository.py",
        "domain/repositories/agent_task_repository.py",
        "infrastructure/persistence/repositories/user_memory_repository.py",
        "interface/api/app.py",
    ):
        assert (root / "src/agent_platform" / file).is_file(), f"Missing {file}"
    for entrypoint in config["project"]["scripts"].values():
        module = entrypoint.split(":", 1)[0]
        assert (root / "src" / Path(*module.split("."))).with_suffix(".py").is_file()
    print(f"目录和 {count} 个 Python 源文件检查通过。")


if __name__ == "__main__":
    main()
