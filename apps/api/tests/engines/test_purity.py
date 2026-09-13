"""Spec §6: engines/ imports only schemas/. This test is the boundary."""
import ast
import pathlib

ENGINES = pathlib.Path(__file__).parents[2] / "jury" / "engines"
ALLOWED_INTERNAL = ("jury.schemas", "jury.engines")
BANNED_MODULES = (
    "httpx", "requests", "psycopg", "sqlalchemy", "litellm", "openai",
    "redis", "boto3", "fastapi", "langgraph", "jury.db", "jury.llm",
    "jury.retrieval", "jury.chairs", "jury.graph", "jury.api", "jury.settings",
)


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_every_engine_module_is_pure():
    files = sorted(ENGINES.rglob("*.py"))
    assert files, "no engine modules found"
    for path in files:
        for mod in _imports(path):
            for banned in BANNED_MODULES:
                assert not (mod == banned or mod.startswith(banned + ".")), \
                    f"{path.name} imports {mod}; engines must stay pure (spec §6)"


def test_engines_import_no_internal_module_other_than_schemas():
    for path in sorted(ENGINES.rglob("*.py")):
        for mod in _imports(path):
            if mod.startswith("jury."):
                assert mod.startswith(ALLOWED_INTERNAL), f"{path.name} imports {mod}"


def test_no_engine_reads_the_environment():
    """A pure function does not consult os.environ."""
    for path in sorted(ENGINES.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        assert "os.environ" not in src and "getenv" not in src, path.name
