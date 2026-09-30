"""Lint the shipped nf-core dashboards against the wave 3 family conventions.

Each rule is its own test, parametrized per template (``<pipeline>/<version>``).
Every rule is strict for every shipped template, including new ones.

Rules (see .claude/agents/nfcore-template-builder.md, "Wave 3 conventions"):

a. a pinned table is not shown again in a tab (same DC, same ``use``);
b. a card ``top_n`` secondary only under an aggregation with a per-group meaning
   (not percentile / skewness / kurtosis / mode);
c. ``threshold_warn`` lies on the failing side of ``threshold_value``;
d. a text tile body is at most 3 sentences;
e. no ``forbidden_terms`` (from the sibling megatest.yaml) in any dashboard text;
f. (warn only) no average / median of a percentage or fraction column unless the
   card is scoped by a ``filter_expr`` (review P10);
g. a record card's ``linked_component`` names a component that emits a selection,
   on the card's ``id_col`` when both read the same data collection;
h. (warn only) a record card declares a ``linked_component``.

Run ``pytest depictio/tests/models/test_template_conventions.py -rxX`` to see
which templates still fail which rule, or call ``collect_violations()``.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from depictio.models.components.advanced_viz.component import AdvancedVizLiteComponent
from depictio.models.components.advanced_viz.record_link import (
    linked_component_of,
    linked_component_problems,
    viz_kind_of,
)

NF_CORE_DIR = Path(__file__).resolve().parents[2] / "projects" / "nf-core"

# Superseded templates kept for existing projects; not linted.
SKIPPED_TEMPLATES = frozenset({"ampliseq/2.14.0", "ampliseq/2.16.0"})

Component = dict[str, Any]
Violation = str


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _template_ids() -> list[str]:
    ids = {
        f"{p.parents[2].name}/{p.parents[1].name}"
        for p in NF_CORE_DIR.glob("*/*/dashboards/*.yaml")
    }
    return sorted(ids - SKIPPED_TEMPLATES)


def _dashboard_files(template_id: str) -> list[Path]:
    return sorted((NF_CORE_DIR / template_id / "dashboards").glob("*.yaml"))


def _tabs(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    main = dashboard.get("main_dashboard") or {}
    return [main, *(dashboard.get("tabs") or [])]


def _iter_tabs(template_id: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """``(label, tab)`` for every tab of every dashboard file of the template."""
    for path in _dashboard_files(template_id):
        dashboard = yaml.safe_load(path.read_text()) or {}
        for tab in _tabs(dashboard):
            yield f"{path.name}:{tab.get('title') or tab.get('main_tab_name') or '?'}", tab


def _components(tab: dict[str, Any], component_type: str | None = None) -> list[Component]:
    return [
        c
        for c in tab.get("components") or []
        if component_type is None or c.get("component_type") == component_type
    ]


def _pinned_section_names(tab: dict[str, Any]) -> set[str]:
    return {s["name"] for s in tab.get("grid_sections") or [] if s.get("pin") and s.get("name")}


def _label(c: Component) -> str:
    return str(c.get("tag") or c.get("index") or c.get("title") or "?")


# ---------------------------------------------------------------------------
# Rules: each returns the list of violations of one template
# ---------------------------------------------------------------------------


def check_pinned_table_not_repeated(template_id: str) -> list[Violation]:
    tabs = list(_iter_tabs(template_id))
    pinned: dict[tuple[str, str], str] = {}
    for label, tab in tabs:
        pinned_names = _pinned_section_names(tab)
        for c in _components(tab, "table"):
            if c.get("section") in pinned_names:
                key = (str(c.get("data_collection_tag")), str(c.get("use") or ""))
                pinned.setdefault(key, f"{label} {_label(c)}")
    out: list[Violation] = []
    for label, tab in tabs:
        pinned_names = _pinned_section_names(tab)
        for c in _components(tab, "table"):
            if c.get("section") in pinned_names:
                continue
            key = (str(c.get("data_collection_tag")), str(c.get("use") or ""))
            if key in pinned:
                out.append(f"{label} {_label(c)} repeats pinned table {pinned[key]}")
    return out


# Aggregations whose top_n breakdown means something (card_breakdown.py): count and
# sum carry shares; the others show the per-group value in the card's unit, no %.
TOP_N_AGGREGATIONS = frozenset(
    {
        "sum",
        "count",
        "nunique",
        "max",
        "min",
        "average",
        "mean",
        "median",
        "range",
        "variance",
        "std_dev",
    }
)


def check_top_n_only_under_sum(template_id: str) -> list[Violation]:
    return [
        f"{label} {_label(c)}: top_n under {c.get('aggregation')}"
        for label, tab in _iter_tabs(template_id)
        for c in _components(tab, "card")
        if c.get("secondary_layout") == "top_n" and c.get("aggregation") not in TOP_N_AGGREGATIONS
    ]


def check_threshold_warn_side(template_id: str) -> list[Violation]:
    out: list[Violation] = []
    for label, tab in _iter_tabs(template_id):
        for c in _components(tab, "card"):
            warn, value = c.get("threshold_warn"), c.get("threshold_value")
            if warn is None or value is None:
                continue
            direction = c.get("threshold_direction") or "min"
            # min: at-least passes, so the warn band sits below the cut-off.
            ok = warn < value if direction == "min" else warn > value
            if not ok:
                out.append(
                    f"{label} {_label(c)}: threshold_warn {warn} on the passing side of "
                    f"{direction} {value}"
                )
    return out


# A sentence ends at . ! ? followed by whitespace and a capital, digit, quote,
# bracket or markdown marker; abbreviations like "e.g." and decimals do not.
_SENTENCE_END_RE = re.compile(
    r"(?<!\be\.g)(?<!\bi\.e)(?<!\bvs)(?<!\betc)[.!?]\s+(?=[A-Z0-9`*_(\[\"'])"
)
MAX_INTRO_SENTENCES = 3


def count_sentences(text: str) -> int:
    body = " ".join(str(text).split())
    if not body:
        return 0
    return len(_SENTENCE_END_RE.findall(body)) + 1


def check_text_intro_length(template_id: str) -> list[Violation]:
    out: list[Violation] = []
    for label, tab in _iter_tabs(template_id):
        for c in _components(tab, "text"):
            n = count_sentences(c.get("body") or "")
            if n > MAX_INTRO_SENTENCES:
                out.append(f"{label} {_label(c)}: {n} sentences")
    return out


def _forbidden_terms(template_id: str) -> list[str]:
    megatest = NF_CORE_DIR / template_id / "megatest.yaml"
    if not megatest.is_file():
        return []
    data = yaml.safe_load(megatest.read_text()) or {}
    return [str(t) for t in data.get("forbidden_terms") or [] if str(t).strip()]


def _dashboard_texts(template_id: str) -> Iterator[tuple[str, str]]:
    """``(where, text)`` for every reader-facing string of the template's dashboards."""
    for label, tab in _iter_tabs(template_id):
        for key in ("title", "subtitle", "main_tab_name"):
            if tab.get(key):
                yield f"{label} tab.{key}", str(tab[key])
        for section in [*(tab.get("grid_sections") or []), *(tab.get("filter_sections") or [])]:
            for key in ("name", "description"):
                if section.get(key):
                    yield f"{label} section.{key}", str(section[key])
        for c in _components(tab):
            for key in ("title", "description", "body"):
                if c.get(key):
                    yield f"{label} {_label(c)}.{key}", str(c[key])


def check_forbidden_terms(template_id: str) -> list[Violation]:
    terms = _forbidden_terms(template_id)
    if not terms:
        return []
    patterns = [(t, re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.IGNORECASE)) for t in terms]
    return [
        f"{where}: '{term}'"
        for where, text in _dashboard_texts(template_id)
        for term, pattern in patterns
        if pattern.search(text)
    ]


PERCENT_COLUMN_RE = re.compile(r"(_pct|percent|_frac)$", re.IGNORECASE)
MEAN_AGGREGATIONS = frozenset({"average", "mean", "median"})


def check_no_mean_of_percentages(template_id: str) -> list[Violation]:
    return [
        f"{label} {_label(c)}: {c.get('aggregation')} of {c.get('column_name')}"
        for label, tab in _iter_tabs(template_id)
        for c in _components(tab, "card")
        if c.get("aggregation") in MEAN_AGGREGATIONS
        and PERCENT_COLUMN_RE.search(str(c.get("column_name") or ""))
        and not c.get("filter_expr")
    ]


def _resolved_viz_config(c: Component) -> dict[str, Any] | None:
    """The config a ``use:`` render expands to, which the YAML does not spell out."""
    if c.get("component_type") != "advanced_viz" or not c.get("use"):
        return None
    try:
        return AdvancedVizLiteComponent.model_validate(c).config.model_dump()
    except Exception:
        return None


def check_record_card_linked_source(template_id: str) -> list[Violation]:
    return [
        f"{label} {problem}"
        for label, tab in _iter_tabs(template_id)
        for problem in linked_component_problems(_components(tab), _resolved_viz_config)
    ]


def check_record_card_linked(template_id: str) -> list[Violation]:
    return [
        f"{label} {_label(c)}: record card without linked_component"
        for label, tab in _iter_tabs(template_id)
        for c in _components(tab, "advanced_viz")
        if (viz_kind_of(c) or (_resolved_viz_config(c) or {}).get("viz_kind")) == "record_card"
        and not linked_component_of(c)
    ]


RULES: dict[str, Callable[[str], list[Violation]]] = {
    "pinned_table_not_repeated": check_pinned_table_not_repeated,
    "top_n_only_under_sum": check_top_n_only_under_sum,
    "threshold_warn_side": check_threshold_warn_side,
    "text_intro_length": check_text_intro_length,
    "forbidden_terms": check_forbidden_terms,
    "no_mean_of_percentages": check_no_mean_of_percentages,
    "record_card_linked_source": check_record_card_linked_source,
    "record_card_linked": check_record_card_linked,
}


def collect_violations() -> dict[str, dict[str, list[Violation]]]:
    """``{rule: {template_id: [violations]}}`` over every linted template."""
    return {
        rule: {tid: v for tid in _template_ids() if (v := check(tid))}
        for rule, check in RULES.items()
    }


TEMPLATE_IDS = _template_ids()


def _assert_clean(violations: list[Violation]) -> None:
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_pinned_table_not_repeated_in_a_tab(template_id: str) -> None:
    _assert_clean(check_pinned_table_not_repeated(template_id))


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_card_top_n_only_under_sum_or_count(template_id: str) -> None:
    _assert_clean(check_top_n_only_under_sum(template_id))


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_threshold_warn_on_failing_side(template_id: str) -> None:
    _assert_clean(check_threshold_warn_side(template_id))


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_text_intro_at_most_three_sentences(template_id: str) -> None:
    _assert_clean(check_text_intro_length(template_id))


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_no_forbidden_terms_in_dashboard_text(template_id: str) -> None:
    _assert_clean(check_forbidden_terms(template_id))


@pytest.mark.parametrize("template_id", [pytest.param(t, id=t) for t in _template_ids()])
def test_no_mean_of_percentages_warn_only(template_id: str) -> None:
    """P10, warn level: reported, never failing."""
    for violation in check_no_mean_of_percentages(template_id):
        warnings.warn(f"{template_id} {violation}", UserWarning, stacklevel=1)


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_record_card_linked_source_emits_selection(template_id: str) -> None:
    _assert_clean(check_record_card_linked_source(template_id))


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_record_card_linked_warn_only(template_id: str) -> None:
    """Warn level: a card following ``any`` selection still works, just less precisely."""
    for violation in check_record_card_linked(template_id):
        warnings.warn(f"{template_id} {violation}", UserWarning, stacklevel=1)


# ---------------------------------------------------------------------------
# The rules themselves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("One sentence.", 1),
        ("One. Two. Three.", 3),
        ("Pick a sample, e.g. the first one. Then read the tail.", 2),
        ("A value of 0.05 marks it. Lower is better.", 2),
        ("First.\nSecond on a new line. `code` third.", 3),
    ],
)
def test_count_sentences(text: str, expected: int) -> None:
    assert count_sentences(text) == expected


def test_rules_catch_synthetic_violations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tdir = tmp_path / "demo" / "1.0.0"
    (tdir / "dashboards").mkdir(parents=True)
    (tdir / "megatest.yaml").write_text("forbidden_terms: [NA12878, TP53]\n")
    dashboard = {
        "main_dashboard": {
            "title": "Demo",
            "subtitle": "Germline calls of na12878.",
            "grid_sections": [{"name": "Sample sheet", "pin": "top", "persistent": True}],
            "components": [
                {
                    "component_type": "table",
                    "tag": "pinned",
                    "section": "Sample sheet",
                    "data_collection_tag": "samples",
                },
                {
                    "component_type": "card",
                    "tag": "meanpct",
                    "aggregation": "average",
                    "column_name": "mapped_pct",
                },
                {
                    "component_type": "card",
                    "tag": "topn",
                    "aggregation": "percentile",
                    "secondary_layout": "top_n",
                    "column_name": "mapped_pct",
                    "threshold_value": 80,
                    "threshold_direction": "min",
                    "threshold_warn": 90,
                },
                {"component_type": "text", "tag": "intro", "body": "A. B. C. D. TP53x is fine."},
            ],
        },
        "tabs": [
            {
                "title": "QC",
                "components": [
                    {
                        "component_type": "table",
                        "tag": "again",
                        "section": "Tables",
                        "data_collection_tag": "samples",
                    },
                    {
                        "component_type": "card",
                        "tag": "ok",
                        "aggregation": "sum",
                        "secondary_layout": "top_n",
                        "column_name": "reads",
                        "threshold_value": 0.1,
                        "threshold_direction": "max",
                        "threshold_warn": 0.2,
                    },
                    {
                        "component_type": "card",
                        "tag": "scoped",
                        "aggregation": "median",
                        "column_name": "cpg_percent",
                        "filter_expr": "col('context') == 'CpG'",
                    },
                ],
            },
        ],
    }
    (tdir / "dashboards" / "base.yaml").write_text(yaml.safe_dump(dashboard))
    monkeypatch.setitem(globals(), "NF_CORE_DIR", tmp_path)

    tid = "demo/1.0.0"
    assert _template_ids() == [tid]
    assert len(check_pinned_table_not_repeated(tid)) == 1
    [top_n] = check_top_n_only_under_sum(tid)
    assert " topn: top_n under percentile" in top_n
    assert len(check_threshold_warn_side(tid)) == 1
    assert len(check_text_intro_length(tid)) == 1
    # Word boundary: "TP53x" is not "TP53"; case-insensitive: "na12878." is.
    assert check_forbidden_terms(tid) == ["base.yaml:Demo tab.subtitle: 'NA12878'"]
    assert len(check_no_mean_of_percentages(tid)) == 1


def test_record_card_rules_catch_synthetic_violations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tdir = tmp_path / "demo" / "1.0.0"
    (tdir / "dashboards").mkdir(parents=True)

    def card(tag: str, linked: str | None, id_col: str = "sample") -> Component:
        config: dict[str, Any] = {"viz_kind": "record_card", "id_col": id_col}
        if linked:
            config["linked_component"] = linked
        return {
            "component_type": "advanced_viz",
            "tag": tag,
            "data_collection_tag": "samples",
            "viz_kind": "record_card",
            "config": config,
        }

    table = {
        "component_type": "table",
        "tag": "selecting-table",
        "data_collection_tag": "samples",
        "row_selection_enabled": True,
        "row_selection_column": "sample",
    }
    inert_table = {
        "component_type": "table",
        "tag": "inert-table",
        "data_collection_tag": "samples",
    }
    scatter = {
        "component_type": "advanced_viz",
        "tag": "lasso",
        "data_collection_tag": "samples",
        "viz_kind": "scatter_xy",
        "config": {"viz_kind": "scatter_xy", "selection_enabled": True, "label_col": "run"},
    }
    dashboard = {
        "main_dashboard": {
            "title": "Demo",
            "components": [
                table,
                inert_table,
                scatter,
                card("ok", "selecting-table"),
                card("inert", "inert-table"),
                card("wrong-col", "lasso"),
                card("unlinked", None),
            ],
        }
    }
    (tdir / "dashboards" / "base.yaml").write_text(yaml.safe_dump(dashboard))
    monkeypatch.setitem(globals(), "NF_CORE_DIR", tmp_path)

    tid = "demo/1.0.0"
    problems = check_record_card_linked_source(tid)
    assert len(problems) == 2
    assert any("[inert] linked_component 'inert-table' emits no selection" in p for p in problems)
    assert any("selects on 'run' but the card matches on id_col 'sample'" in p for p in problems)
    assert check_record_card_linked(tid) == [
        "base.yaml:Demo unlinked: record card without linked_component"
    ]
