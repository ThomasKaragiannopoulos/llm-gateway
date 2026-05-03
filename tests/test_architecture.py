from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports_for(path: Path) -> set[str]:
    tree = _module(path)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_main_is_only_bootstrap_assignment() -> None:
    tree = _module(ROOT / "app" / "main.py")
    imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)]

    assert len(imports) == 1
    assert imports[0].module == "app.bootstrap"
    assert any(alias.name == "create_app" for alias in imports[0].names)
    assert len(assignments) == 1
    assert isinstance(assignments[0].value, ast.Call)
    assert getattr(assignments[0].value.func, "id", None) == "create_app"


def test_routers_do_not_import_db_models_or_sessions() -> None:
    for path in (ROOT / "app" / "routers").glob("*.py"):
        imports = _imports_for(path)
        assert "app.db.models" not in imports
        assert "app.db.session" not in imports


def test_services_do_not_import_fastapi() -> None:
    for path in (ROOT / "app" / "services").glob("*.py"):
        imports = _imports_for(path)
        assert all(not name.startswith("fastapi") for name in imports)


def test_middleware_uses_policy_service_instead_of_repositories() -> None:
    imports = _imports_for(ROOT / "app" / "middleware.py")
    assert "app.db.repositories" not in imports
    assert "app.db.session" not in imports
    assert "app.services.policy" in imports


def test_gateway_service_is_only_a_facade() -> None:
    gateway_py = ROOT / "app" / "services" / "gateway.py"
    contents = gateway_py.read_text(encoding="utf-8").strip().splitlines()
    assert contents == [
        "from app.services.chat_shared import ChatExecutionResult",
        "from app.services.chat_stream import execute_chat_stream",
        "from app.services.chat_sync import execute_chat",
        "",
        '__all__ = ["ChatExecutionResult", "execute_chat", "execute_chat_stream"]',
    ]


def test_mypy_targets_full_project_surface() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["mypy"]["files"] == ["app", "tests", "scripts"]
