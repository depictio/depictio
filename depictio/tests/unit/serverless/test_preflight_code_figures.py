"""The preflight's verdict on code-mode figures is the build's.

A live run preflighted the reference dashboards and promised live tiles the
build then froze with "code-mode figure not transpilable" (iris 2, penguins 2,
viralrecon 5 + their overview highlights, ampliseq "Phylum composition per
group"). Two things have to hold for that to stop: the data-free plan reads the
code with the build's own transpilability decision (``_code_figure_plan``), and
the preflight endpoint assumes the build's Python-runtime mode (``off``) unless
told otherwise — under ``auto`` those same tiles really are live, through the
runtime.

The snippets are read from the dashboard YAMLs themselves, so a seed edit that
makes one transpilable shows up here as a changed verdict, not as a stale copy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from depictio.models.models.serverless import ComponentTier, TierReason
from depictio.serverless import producer_a

PROJECTS = Path(__file__).resolve().parents[3] / "projects"

# (dashboard YAML, figure title, the build's refusal from the live run)
CASES = [
    (
        "init/penguins/dashboards/species_analysis.yaml",
        "Island × Species Distribution",
        "pandas .groupby() differs on null keys and ordering",
    ),
    (
        "init/penguins/dashboards/island_season.yaml",
        "Island, species and sex — who is where",
        "fig line mixes several prologue frames",
    ),
    (
        "nf-core/ampliseq/2.18.0/dashboards/base.yaml",
        "Phylum composition per group",
        "fig line mixes several prologue frames",
    ),
    (
        "nf-core/viralrecon/3.0.0/dashboards/base.yaml",
        "Median depth against genome covered at 10x",
        "fig line does not use the final prologue frame 'top'",
    ),
    (
        "nf-core/viralrecon/3.0.0/dashboards/base.yaml",
        "Median depth per amplicon",
        "unsupported method '.with_columns()'",
    ),
    (
        "nf-core/viralrecon/3.0.0/dashboards/base.yaml",
        "Nextclade QC score per consensus genome",
        "unsupported method '.head()'",
    ),
    (
        "nf-core/viralrecon/3.0.0/dashboards/base.yaml",
        "Samples per clade",
        "expected a method call on the dataframe",
    ),
]


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _figure(rel: str, title: str) -> dict[str, Any]:
    doc = yaml.safe_load((PROJECTS / rel).read_text(encoding="utf-8"))
    for node in _walk(doc):
        if node.get("component_type") == "figure" and node.get("title") == title:
            assert node.get("mode") == "code", f"{title} is no longer a code-mode figure"
            return {
                "index": node.get("tag") or title,
                "component_type": "figure",
                "mode": "code",
                "code_content": node.get("code_content"),
            }
    raise AssertionError(f"figure {title!r} not found in {rel}")


@pytest.mark.parametrize(("rel", "title", "refusal"), CASES, ids=[c[1] for c in CASES])
def test_the_plan_freezes_what_the_build_freezes(rel: str, title: str, refusal: str):
    comp = _figure(rel, title)

    plan = producer_a.classify_stored_component(comp)
    _, call, build_refusal = producer_a._code_figure_plan(comp)

    assert call is None  # the build never offers it to the binder
    assert plan.tier is ComponentTier.FROZEN
    assert plan.reason is TierReason.CODE_MODE
    assert plan.provisional is False  # a final verdict, not "upgraded if it binds"
    assert plan.detail and plan.detail.startswith(
        f"code-mode figure not transpilable: {build_refusal}"
    )
    assert build_refusal and refusal in build_refusal


def test_only_the_python_runtime_makes_them_live(monkeypatch: pytest.MonkeyPatch):
    """The other half: without the runtime they are not Python candidates at
    all, so nothing upgrades them, and with it (``auto``) they are — which is
    why the preflight must assume the build's mode, not ``auto``."""
    items = [(None, _figure(rel, title), title) for rel, title, _ in CASES]

    assert producer_a.mark_python_candidates(items, "off") == {}
    candidates = producer_a.mark_python_candidates(items, "auto")
    assert set(candidates) == {title for _, title, _ in CASES}
    for _, comp, _ in items:
        comp.pop(producer_a.PYTHON_JOB_KEY, None)
