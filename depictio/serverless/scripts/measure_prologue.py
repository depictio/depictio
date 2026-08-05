"""Coverage report for the code-mode prologue transpiler (RFC §7, phase 6).

Walks every seed dashboard (``depictio/projects/**/.db_seeds/*.json``), pulls
out the ``mode == "code"`` figure components and runs
:func:`depictio.serverless.prologue.classify` over each one, printing the
free / prologue / frozen split plus a one-line reason for every frozen figure.

Read-only — it never writes a seed.

    DEPICTIO_CONTEXT=cli ./venv/bin/python -m depictio.serverless.scripts.measure_prologue
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

from depictio.serverless.prologue import transpile_with_reason

REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECTS = REPO_ROOT / "depictio" / "projects"


def code_mode_figures() -> Iterator[tuple[Path, dict[str, Any]]]:
    """Every code-mode figure component in the committed seeds, in path order."""
    for seed in sorted(PROJECTS.glob("**/.db_seeds/*.json")):
        try:
            doc = json.loads(seed.read_text())
        except json.JSONDecodeError:
            continue
        for component in doc.get("stored_metadata") or []:
            if component.get("component_type") != "figure":
                continue
            if component.get("mode") != "code":
                continue
            yield seed, component


def main() -> None:
    counts: Counter[str] = Counter()
    op_counts: Counter[str] = Counter()
    frozen: list[tuple[str, str, str]] = []
    rows: list[tuple[str, str, str, str]] = []

    for seed, component in code_mode_figures():
        label = f"{seed.relative_to(REPO_ROOT).as_posix()}::{component.get('index')}"
        code = component.get("code_content") or ""
        ops, reason = transpile_with_reason(code)
        if ops is None:
            verdict = "frozen"
            detail = reason or "unrecognised"
            frozen.append((label, str(component.get("title") or ""), detail))
        elif not ops:
            verdict = "free"
            detail = "binds to the base table"
        else:
            verdict = "prologue"
            detail = " -> ".join(op.op for op in ops)
            op_counts.update(op.op for op in ops)
        counts[verdict] += 1
        rows.append((verdict, label, str(component.get("visu_type") or ""), detail))

    total = sum(counts.values())
    print(f"code-mode figures in seeds: {total}\n")
    for verdict, label, visu, detail in rows:
        print(f"{verdict:9s} {visu:10s} {label}")
        print(f"{'':20s}{detail}")

    print("\n--- classification ---")
    for verdict in ("free", "prologue", "frozen"):
        share = f"{100 * counts[verdict] / total:.0f}%" if total else "-"
        print(f"{verdict:9s} {counts[verdict]:3d}  ({share})")
    live = counts["free"] + counts["prologue"]
    print(f"{'live':9s} {live:3d}  ({100 * live / total:.0f}%)" if total else "live 0")

    if op_counts:
        print("\n--- ops emitted ---")
        for op, n in op_counts.most_common():
            print(f"  {op:9s} {n}")

    if frozen:
        print("\n--- frozen reasons ---")
        for label, title, detail in frozen:
            print(f"  {label}\n    {title!r}: {detail}")


if __name__ == "__main__":
    main()
