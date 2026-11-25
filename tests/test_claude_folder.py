"""claude/ (claude/README.md): the app doesn't depend on it, its tools are described and tested,
and no script lands anywhere else."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from claude import __main__ as cli

ROOT = Path(__file__).resolve().parents[1]
APP = ("src", "api", "analysis", "orchestration", "deploy", "docs")
TOOLS = sorted((ROOT / "claude/tools").glob("[a-z]*.py"))


def python_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split("\n")  # fmt: skip
    return [Path(p) for p in out if p and (ROOT / p).exists() and not p.startswith("issues/")]


def imported(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse((ROOT / path).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names.add(node.module)
    return names


def test_the_app_never_imports_claude():
    used = [str(p) for p in python_files() if p.parts[0] in APP
            and any(n.split(".")[0] == "claude" for n in imported(p))]  # fmt: skip
    assert not used


def test_the_containers_do_not_hold_claude():
    for name in ("Dockerfile", "Dockerfile.report", ".dockerignore"):
        assert "claude" not in (ROOT / name).read_text(encoding="utf-8")


def test_scripts_are_where_they_belong():
    """A new place for Python files is added here on purpose (claude/README.md says where)."""
    known = ("src/stock_analysis", "api", "analysis", "orchestration", "tests", "claude/tools")
    files = {"claude/__init__.py", "claude/__main__.py", "claude/client.py", "docs/pipeline_uml.py",
             "deploy/airflow/metadata_db.py"}  # fmt: skip
    lost = [p.as_posix() for p in python_files() if p.as_posix() not in files
            and not p.as_posix().startswith(tuple(f"{k}/" for k in known))]  # fmt: skip
    assert not lost, f"see claude/README.md, 'Where a new script goes': {lost}"


@pytest.mark.parametrize("path", TOOLS, ids=lambda p: p.stem)
def test_every_tool_is_described_runnable_and_tested(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert len(cli.summary(path)) > 30, "the docstring's first paragraph says what the tool does"
    assert f"python -m claude {path.stem}" in ast.get_docstring(tree), "Usage in the docstring"
    assert "main" in {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    tested = set()
    for p in (ROOT / "tests").glob("test_*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module == "claude.tools":
                tested |= {a.name for a in node.names}
    assert path.stem in tested, "no test imports it"


def test_the_client_needs_nothing_but_the_api():
    """The nightly session runs it without a database or the app's settings."""
    third = {n.split(".")[0] for n in imported(Path("claude/client.py"))} - sys.stdlib_module_names
    assert third == {"httpx", "dotenv"}


def test_list_and_unknown_tool(capsys):
    assert cli.main([]) == 0
    listed = capsys.readouterr().out
    for name in cli.tools():
        assert f"\n{name}\n" in listed
    assert cli.main(["nothing"]) == 2
    assert "absolute" in capsys.readouterr().err
    with pytest.raises(SystemExit, match="Name the companies"):
        cli.main(["absolute"])
