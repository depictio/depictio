"""Worker tasks must open MongoDB with pymongo's async client.

beanie 2.x rejects a motor database ("'MotorDatabase' object is not
callable"), and the report render and figure extraction tasks run outside
the API's own Beanie context, so a motor client there fails every job.
No e2e spec renders a report, so this is the only guard.
"""

from __future__ import annotations

import ast
from pathlib import Path

import depictio

PACKAGE = Path(depictio.__file__).parent


def _motor_imports(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
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
        if "tests" not in path.relative_to(PACKAGE).parts
        for line in _motor_imports(path)
    ]
    assert offenders == []
