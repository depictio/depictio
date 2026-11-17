"""Offline guard: every code-mode figure shipped in a dashboard YAML must run in the sandbox.

``dashboard validate --offline`` checks the shape of a dashboard, and the live render
checker only sees what a stack happens to serve, so a code figure that the server's
sandbox rejects used to reach the browser as a red "Code execution error" tile. Two
families of rejection are decided by the code alone, with no data needed:

* the structural rules of ``analyze_constrained_code`` (for instance "Preprocessing
  creates variables, but fig line doesn't use any dataframe"), and
* the RestrictedPython policy of ``SimpleCodeExecutor``: a construct the compiler
  rewrites into a guard call (``print`` becomes ``_print_(...)``) that the executor
  does not provide fails at run time with ``name '_print_' is not defined``, whatever
  the data. (``x += 1`` used to fail this way; the executor now provides
  ``_inplacevar_``.)

This test collects every ``code_content`` in every dashboard YAML (and the
``.db_seeds`` JSON fresh deployments load) under ``depictio/projects``, runs both checks, then executes the code against a small
synthetic frame (one column per string literal in the code) and fails on the errors
that do not depend on the data: an undefined name, a denied attribute, a refused write.
A data-dependent error on the synthetic frame (wrong dtype, missing value) is not a
finding here; the live checker (``scripts/check_deployment.py``) covers those.
"""

from __future__ import annotations

import ast
import json
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import plotly.express as px
import polars as pl
import pytest
import yaml
from RestrictedPython import compile_restricted

from depictio.api.v1.services.figure.code_executor import SimpleCodeExecutor
from depictio.api.v1.services.figure.code_mode import analyze_constrained_code
from depictio.api.v1.services.figure.groups import code_group_globals

PROJECTS_DIR = Path(__file__).resolve().parents[2] / "projects"

# Substrings of an execution message that no data can cause: the sandbox itself
# refused the code, or the code names something that does not exist.
_POLICY_MARKERS = (
    "is not defined",
    "not allowed in a code figure",
    "cannot write to a",
    "is not a valid Plotly figure",
)


@dataclass(frozen=True)
class CodeFigure:
    path: str
    tab: str
    tag: str
    code: str

    @property
    def id(self) -> str:
        return f"{self.path}::{self.tab}::{self.tag}"


def _walk(node: Any, tab: str, found: list[tuple[str, dict]]) -> None:
    """Collect every mapping with a ``code_content`` string, with its enclosing tab title."""
    if isinstance(node, dict):
        # A tab is a mapping that holds its components (YAML) or stored metadata
        # (seed JSON); remember its title.
        if node.get("title") and any(
            isinstance(node.get(k), list) for k in ("components", "stored_metadata")
        ):
            tab = str(node["title"])
        if isinstance(node.get("code_content"), str) and node["code_content"].strip():
            found.append((tab, node))
        for value in node.values():
            _walk(value, tab, found)
    elif isinstance(node, list):
        for item in node:
            _walk(item, tab, found)


# Deliberately broken dashboards used to exercise the error paths of the validator.
_INTENTIONALLY_BROKEN = ("test/validation_tests/",)


def _load_documents(path: Path) -> list[Any]:
    try:
        if path.suffix == ".json":
            return [json.loads(path.read_text())]
        return list(yaml.safe_load_all(path.read_text()))
    except (yaml.YAMLError, ValueError):
        return []


def collect_code_figures() -> Iterator[CodeFigure]:
    """Every code figure in a dashboard YAML, plus the ``.db_seeds`` JSON fresh deployments load."""
    paths = sorted(
        [*PROJECTS_DIR.rglob("*.yaml"), *PROJECTS_DIR.rglob(".db_seeds/*.json")],
    )
    for path in paths:
        rel = str(path.relative_to(PROJECTS_DIR))
        if rel.startswith(_INTENTIONALLY_BROKEN):
            continue
        if "code_content" not in path.read_text():
            continue
        found: list[tuple[str, dict]] = []
        for doc in _load_documents(path):
            _walk(doc, path.stem, found)
        seen: dict[str, int] = {}
        for tab, comp in found:
            tag = str(comp.get("tag") or comp.get("index") or comp.get("title") or "?")
            seen[tag] = seen.get(tag, 0) + 1
            if seen[tag] > 1:
                tag = f"{tag}#{seen[tag]}"
            yield CodeFigure(rel, tab, tag, comp["code_content"])


CODE_FIGURES = list(collect_code_figures())


def _guard_names(code_obj: types.CodeType) -> set[str]:
    """RestrictedPython guard names (``_inplacevar_``, ``_print_``...) the bytecode calls."""
    names = {n for n in code_obj.co_names if n.startswith("_") and n.endswith("_") and len(n) > 2}
    for const in code_obj.co_consts:
        if isinstance(const, types.CodeType):
            names |= _guard_names(const)
    return names


def static_problems(code: str, executor: SimpleCodeExecutor) -> list[str]:
    """Problems decided by the code alone: structure, restricted compile, guard policy."""
    analysis = analyze_constrained_code(code)
    if not analysis["is_valid"]:
        return [f"Code validation failed: {analysis['error_message']}"]
    is_valid, message = executor._validate_no_df_assignment(code)
    if not is_valid:
        return [message]

    problems: list[str] = []
    provided = set(executor.safe_globals)
    for label, source in (
        ("preprocessing", analysis["preprocessing_code"]),
        ("figure", analysis["figure_code"]),
    ):
        if not source:
            continue
        try:
            compiled = compile_restricted(source, filename=f"<{label}>", mode="exec")
        except SyntaxError as exc:
            problems.append(f"{label} does not compile: {exc.msg} (line {exc.lineno})")
            continue
        if compiled is None:
            problems.append(f"{label} does not compile under RestrictedPython")
            continue
        for name in sorted(_guard_names(compiled) - provided):
            hint = (
                " (augmented assignment such as `x += 1` is unsupported; write `x = x + 1`)"
                if name == "_inplacevar_"
                else ""
            )
            problems.append(
                f"{label} needs the guard {name}, which the sandbox does not define{hint}"
            )
    return problems


def _string_literals(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if value and len(value) <= 60 and "\n" not in value and value not in out:
                out.append(value)
    return out


def _synthetic_frames(code: str) -> list[pl.DataFrame]:
    """Two small frames with a column per string literal: all numeric, all text."""
    names = _string_literals(code) or ["x"]
    n = 6
    numeric = pl.DataFrame({name: [float(i + 1) for i in range(n)] for name in names})
    text = pl.DataFrame({name: [chr(ord("a") + i % 3) for i in range(n)] for name in names})
    return [numeric, text]


def runtime_problems(code: str, executor: SimpleCodeExecutor) -> list[str]:
    """Execute against synthetic frames; keep only the errors no data can explain."""
    problems: list[str] = []
    for frame in _synthetic_frames(code):
        ok, _fig, message = executor.execute_code(code, frame, code_group_globals())
        if ok:
            return []
        if any(marker in message for marker in _POLICY_MARKERS):
            problems.append(message.strip().splitlines()[0])
    return list(dict.fromkeys(problems))


def check_code_figure(code: str) -> list[str]:
    """Every data-independent problem with one code figure; empty when it is fine."""
    executor = SimpleCodeExecutor()
    problems = static_problems(code, executor)
    if problems:
        return problems
    return runtime_problems(code, executor)


# --------------------------------------------------------------------------- #
# The guard itself
# --------------------------------------------------------------------------- #


def test_templates_ship_code_figures():
    """The collector must find the shipped code figures, or the guard below checks nothing."""
    assert len(CODE_FIGURES) > 50


@pytest.mark.parametrize("figure", CODE_FIGURES, ids=[f.id for f in CODE_FIGURES])
def test_shipped_code_figure_runs_in_sandbox(figure: CodeFigure):
    problems = check_code_figure(figure.code)
    assert not problems, f"{figure.id}: " + "; ".join(problems)


# --------------------------------------------------------------------------- #
# The checks catch what the user saw in the browser
# --------------------------------------------------------------------------- #


def test_augmented_assignment_is_accepted():
    code = (
        "total = 0\nfor v in df['x'].to_list():\n    total += v\nfig = px.bar(df, x='x', y='x')\n"
    )
    assert check_code_figure(code) == []


def test_augmented_assignment_does_not_mutate_shared_palettes():
    palette = list(px.colors.qualitative.Plotly)
    code = (
        "scale = px.colors.qualitative.Plotly\nscale += ['#000000']\n"
        "fig = px.bar(df, x='x', y='x', color_discrete_sequence=scale)\n"
    )
    assert check_code_figure(code) == []
    assert px.colors.qualitative.Plotly == palette


def test_preprocessing_not_used_by_the_figure_is_rejected():
    code = "counts = df.group_by('x').len()\nfig = px.bar(pl.DataFrame({'a': [1]}), x='a')\n"
    problems = check_code_figure(code)
    assert any("doesn't use any dataframe" in p for p in problems), problems


def test_reassigning_df_is_rejected():
    problems = check_code_figure("df = df.head(2)\nfig = px.bar(df, x='x', y='x')\n")
    assert any("Cannot reassign" in p for p in problems), problems


def test_undefined_name_is_rejected():
    problems = check_code_figure("fig = px.bar(df, x='x', y='x', color_discrete_map=palette)\n")
    assert any("is not defined" in p for p in problems), problems


def test_sound_figure_passes():
    code = (
        "d = df.group_by('x').agg(pl.col('y').sum())\n"
        "fig = px.bar(d.to_pandas(), x='x', y='y')\n"
        "fig.update_layout(title='ok')\n"
    )
    assert check_code_figure(code) == []
