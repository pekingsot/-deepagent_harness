"""约束依赖方向，避免目录调整后重新出现跨层调用。"""

import ast
import tomllib
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "agent_platform"


@pytest.mark.parametrize(
    ("layer", "forbidden"),
    [
        ("domain", {"application", "infrastructure", "bootstrap", "interface", "workers"}),
        ("application", {"infrastructure", "bootstrap", "interface", "workers"}),
        ("infrastructure", {"bootstrap", "interface", "workers"}),
    ],
)
def test_dependencies_point_inward(layer: str, forbidden: set[str]) -> None:
    violations = []
    for path in (SOURCE_ROOT / layer).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                parts = module.split(".")
                if len(parts) > 1 and parts[0] == "agent_platform" and parts[1] in forbidden:
                    violations.append(f"{path.relative_to(SOURCE_ROOT)}:{node.lineno}: {module}")

    assert not violations, "发现反向依赖：\n" + "\n".join(violations)


def test_internal_imports_resolve_after_moves() -> None:
    """静态检查内部模块路径，不触发真实数据库或模型初始化。"""
    project = SOURCE_ROOT.parents[1]
    missing = []
    for folder in ("src", "tests", "scripts", "apps", "migrations"):
        for path in (project / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                if not node.module.startswith("agent_platform."):
                    continue
                relative = node.module.split(".")[1:]
                module_path = SOURCE_ROOT.joinpath(*relative)
                if not module_path.with_suffix(".py").exists() and not module_path.is_dir():
                    missing.append(f"{path.relative_to(project)}:{node.lineno}: {node.module}")

    assert not missing, "存在失效的内部导入：\n" + "\n".join(missing)


def test_console_entrypoints_resolve_after_moves() -> None:
    """API 和 Worker 的安装入口与当前目录保持一致。"""
    project = SOURCE_ROOT.parents[1]
    config = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    for entrypoint in config["project"]["scripts"].values():
        module = entrypoint.split(":", 1)[0]
        path = project / "src" / Path(*module.split("."))
        assert path.with_suffix(".py").is_file(), entrypoint
