"""Every code-mode figure shipped in the catalog and the project templates validates.

A code tile whose code the constrained-code validator rejects renders a red
"Code execution error" banner instead of its figure, and nothing else catches
it before a reader opens the tab.
"""

from __future__ import annotations

import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from depictio.api.v1.services.figure.code_mode import analyze_constrained_code

REPO = Path(__file__).resolve().parents[4]
ROOTS = [REPO / "depictio" / "catalog", REPO / "depictio" / "projects"]


def _code_blocks(node, where: str) -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        code = node.get("code_content") if node.get("mode") == "code" else None
        if code is None and isinstance(node.get("code"), str) and "fig" in node["code"]:
            code = node["code"]
        if isinstance(code, str) and code.strip():
            yield where, code
        for key, value in node.items():
            yield from _code_blocks(value, f"{where}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _code_blocks(value, f"{where}[{i}]")


def _shipped() -> list[tuple[str, str]]:
    found = []
    for root in ROOTS:
        for path in sorted(root.rglob("*.yaml")):
            try:
                doc = yaml.safe_load(path.read_text())
            except yaml.YAMLError:
                continue
            found.extend(_code_blocks(doc, str(path.relative_to(REPO))))
    return found


SHIPPED = _shipped()


def test_some_code_is_shipped():
    assert SHIPPED


@pytest.mark.parametrize(("where", "code"), SHIPPED, ids=[w for w, _ in SHIPPED])
def test_code_passes_the_validator(where: str, code: str):
    result = analyze_constrained_code(textwrap.dedent(code))
    assert result["is_valid"], f"{where}: {result.get('error_message')}"
