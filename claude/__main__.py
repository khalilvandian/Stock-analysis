"""Claude's tools: `uv run python -m claude` lists them, `... claude NAME ...` runs one."""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def tools() -> dict[str, Path]:
    found = {p.stem: p for p in sorted((HERE / "tools").glob("[a-z]*.py"))}
    return {"app": HERE / "client.py", **found}


def summary(path: Path) -> str:
    text = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    return " ".join(text.split("\n\n")[0].split())


def main(argv: list[str]) -> int:
    known = tools()
    if not argv or argv[0] in ("-h", "--help", "list"):
        print("uv run python -m claude NAME ...\n")
        for name, path in known.items():
            print(f"{name}\n    {summary(path)}")
        return 0
    if argv[0] not in known:
        print(f"No tool {argv[0]}. There are: {', '.join(known)}", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):  # a Windows console may not be UTF-8
        sys.stdout.reconfigure(encoding="utf-8")
    path = known[argv[0]].relative_to(HERE.parent).with_suffix("")
    return importlib.import_module(".".join(path.parts)).main(argv[1:]) or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
