"""Worker tasks must open MongoDB with pymongo's async client.

beanie 2.x rejects a motor database ("'MotorDatabase' object is not
callable"), and the report render and figure extraction tasks run outside
the API's own Beanie context, so a motor client there fails every job.
No e2e spec renders a report, so this is the only guard.
"""

from __future__ import annotations

import ast
from pathlib import Path

# The package of this checkout (not whatever ``depictio`` an editable install
# resolves to, which may sit above nested worktrees and their virtualenvs).
PACKAGE = Path(__file__).resolve().parents[3]


def _motor_imports(path: Path) -> list[int]:
    try:
        # Bytes, so a file's own coding declaration is honoured; a file that is
        # not Python source at all (a stray non-UTF-8 fixture) cannot hold an import.
        tree = ast.parse(path.read_bytes())
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return []
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "motor":
            lines.append(node.lineno)
        elif isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == "motor" for a in node.names
        ):
            lines.append(node.lineno)
    return lines


def test_no_runtime_code_imports_motor() -> None:
    offenders = [
        f"{path.relative_to(PACKAGE)}:{line}"
        for path in PACKAGE.rglob("*.py")
        if not any(
            part == "tests" or part.startswith(".") or part == "site-packages"
            for part in path.relative_to(PACKAGE).parts
        )
        for line in _motor_imports(path)
    ]
    assert offenders == []
