from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_main_is_a_thin_entrypoint() -> None:
    main_py = ROOT / "app" / "main.py"
    contents = main_py.read_text(encoding="utf-8").strip().splitlines()
    assert contents == ["from app.bootstrap import create_app", "", "app = create_app()"]


def test_gateway_service_is_a_thin_facade() -> None:
    gateway_py = ROOT / "app" / "services" / "gateway.py"
    contents = gateway_py.read_text(encoding="utf-8").strip().splitlines()
    assert contents == [
        "from app.services.chat_shared import ChatExecutionResult",
        "from app.services.chat_stream import execute_chat_stream",
        "from app.services.chat_sync import execute_chat",
        "",
        '__all__ = ["ChatExecutionResult", "execute_chat", "execute_chat_stream"]',
    ]


def test_routers_do_not_import_db_models_directly() -> None:
    for path in (ROOT / "app" / "routers").glob("*.py"):
        imports = _imports_for(path)
        assert "app.db.models" not in imports


def test_services_do_not_import_fastapi_routing() -> None:
    for path in (ROOT / "app" / "services").glob("*.py"):
        imports = _imports_for(path)
        assert "fastapi.routing" not in imports


def test_mypy_targets_full_project_surface() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["mypy"]["files"] == ["app", "tests", "scripts"]
