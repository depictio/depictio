"""Lint the shipped nf-core dashboards against the wave 3 family conventions.

Each rule is its own test, parametrized per template (``<pipeline>/<version>``).
Every rule is strict for every shipped template, including new ones.

Rules (see .claude/agents/nfcore-template-builder.md, "Wave 3 conventions"):

a. a pinned table is not shown again in a tab (same DC, same ``use``);
b. a card ``top_n`` secondary only under an aggregation with a per-group meaning
   (not percentile / skewness / kurtosis / mode);
c. ``threshold_warn`` lies on the failing side of ``threshold_value``;
d. a text tile body is at most 3 sentences of prose (headings, list items,
   table rows and ``:::`` blocks are layout, not sentences);
e. no ``forbidden_terms`` (from the sibling megatest.yaml) in any dashboard text;
f. (warn only) no average / median of a percentage or fraction column unless the
   card is scoped by a ``filter_expr`` (review P10);
g. a record card's ``linked_component`` names a component that emits a selection,
   on the card's ``id_col`` when both read the same data collection;
h. (warn only) a record card declares a ``linked_component``;
i. a persistent (pinned) filter reaches the MultiQC panels: the data collection
   hosting it has an enabled link to the MultiQC collection, unless it is listed
   in ``PINNED_FILTER_DCS_NOT_SAMPLE_LEVEL`` with a reason (latest version of
   each pipeline only).
j. a ``::: steps`` line that links a tab the import can prune (every collection it
   reads is ``optional`` or removed by a ``conditional``) cites a ``{{value}}`` from
   one of that tab's collections, so the line goes with the tab (RULES.md 13). A
   MultiQC tab is exempt: no value can be computed from a MultiQC collection.

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


_BLOCK_LINE_RE = re.compile(r"^\s*(?:#|[-*+]\s|\d+[.)]\s|\||-{3,}\s*$)")
_FENCE_RE = re.compile(r"^\s*:::")
_LINK_RE = re.compile(r"(!?)\[([^\]\n]*)\]\([^)\n]*\)")
_PLACEHOLDER_RE = re.compile(r"\{\{[^{}\n]+\}\}")


def prose_of(body: str) -> str:
    """The paragraphs of a text body, without its block markdown.

    A body is read by the reader as prose plus layout: a heading, a list of tab
    tiles, the rows of a findings list or a ``::: steps`` flow are not sentences,
    and the sentence rule would otherwise count every ``1. [Tab](tab:X)`` item.
    Link targets, icons and live-value placeholders are dropped too.
    """
    kept: list[str] = []
    fenced = False
    for line in str(body).splitlines():
        if _FENCE_RE.match(line):
            fenced = not fenced
            continue
        if fenced or _BLOCK_LINE_RE.match(line):
            continue
        kept.append(line)
    text = _LINK_RE.sub(lambda m: "" if m.group(1) else m.group(2), "\n".join(kept))
    return _PLACEHOLDER_RE.sub("x", text)


def check_text_intro_length(template_id: str) -> list[Violation]:
    """At most ``MAX_INTRO_SENTENCES`` per paragraph (RULES.md, Prose).

    Per paragraph, not per tile: an "About" card of two short paragraphs reads
    as easily as one of three sentences. A folded (``>``) body keeps its
    paragraphs on single lines with no blank line between them, so it is still
    counted whole, the stricter reading.
    """
    out: list[Violation] = []
    for label, tab in _iter_tabs(template_id):
        for c in _components(tab, "text"):
            paragraphs = re.split(r"\n\s*\n", prose_of(c.get("body") or ""))
            n = max((count_sentences(p) for p in paragraphs), default=0)
            if n > MAX_INTRO_SENTENCES:
                out.append(f"{label} {_label(c)}: {n} sentences in one paragraph")
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
            for key in ("title", "description", "body", "caption", "subtitle"):
                if c.get(key):
                    yield f"{label} {_label(c)}.{key}", str(c[key])
            # A live value's filter can pin a megatest sample as surely as prose can.
            for name, spec in (c.get("values") or {}).items():
                if isinstance(spec, dict) and spec.get("filter_expr"):
                    yield f"{label} {_label(c)}.values.{name}", str(spec["filter_expr"])


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


def check_group_col_in_filter_expr(template_id: str) -> list[Violation]:
    """No ``filter_expr`` names ``{GROUP_COL}`` (RULES.md, Conditional routes and pruning).

    Without metadata the variable resolves to the ``__no_group__`` sentinel, which
    the filter guard rejects as a dunder, so the import fails before any pruning.
    """
    out: list[Violation] = []
    for label, tab in _iter_tabs(template_id):
        for c in _components(tab):
            exprs = [("filter_expr", c.get("filter_expr"))] + [
                (f"values.{name}", spec.get("filter_expr"))
                for name, spec in (c.get("values") or {}).items()
                if isinstance(spec, dict)
            ]
            out += [
                f"{label} {_label(c)}.{where}: {expr}"
                for where, expr in exprs
                if expr and "{GROUP_COL}" in str(expr)
            ]
    return out


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


# ---- i. persistent filters reach MultiQC ----------------------------------
#
# A persistent filter section on the Overview applies to every tab, MultiQC
# included. A filter only narrows a MultiQC panel through an enabled project
# link from the filter's data collection (DC) to the MultiQC DC (template.yaml
# ``links:``, ``resolver: sample_mapping``); without it the filter is silently
# ignored on the MultiQC tab. The rule is vacuous for a template without a
# MultiQC panel.
#
# DCs that legitimately hold no sample-level rows (cells, bins, fusions,
# contrasts, genes, per-library QC thresholds on a metrics DC) are listed here,
# per pipeline, with the reason. A listed DC that no longer hosts a pinned
# filter, or that gained a link, is reported as stale.
PINNED_FILTER_DCS_NOT_SAMPLE_LEVEL: dict[str, dict[str, str]] = {
    "atacseq": {
        "ataqv_metrics": "QC threshold slider (TSS enrichment) on a per-library metrics DC; "
        "only a forward link sample_design -> ataqv_metrics exists, so it does not narrow "
        "MultiQC today (a link ataqv_metrics -> multiqc_data would)",
        "macs2_peak_summary": "QC threshold sliders (FRiP, peak count) on a per-library peak "
        "metrics DC; only a forward link sample_design -> macs2_peak_summary exists, so it "
        "does not narrow MultiQC today (a link macs2_peak_summary -> multiqc_data would)",
    },
    "chipseq": {
        "macs2_peak_summary": "QC threshold sliders (FRiP, peak count) on a per-library peak "
        "metrics DC; only a forward link design -> macs2_peak_summary exists, so it does not "
        "narrow MultiQC today (a link macs2_peak_summary -> multiqc_data would)",
    },
    "eager": {
        "qualimap_bamqc_genome_results": "QC floors (coverage, duplication rate) on a per-library "
        "metrics DC; reverse link qualimap_bamqc_genome_results -> samples narrows the hub, "
        "which is linked to MultiQC",
        "endorspy_endogenous": "QC floor (endogenous DNA) on a per-library metrics DC; reverse "
        "link endorspy_endogenous -> samples narrows the hub, which is linked to MultiQC",
    },
    "mag": {
        "bin_summary": "bin-level filters (assembler, binner): a bin is not a MultiQC sample",
    },
    "mcmicro": {
        "samples": "the report's one section is the prelude's custom-content check matrix, "
        "whose rows are the checks and whose columns the images: no MultiQC sample is an "
        "image, so a sample link would empty the panel rather than narrow it",
    },
    "rnafusion": {
        "fusion_consensus": "fusion-level filters (fusion, caller agreement), not sample-level",
    },
    "rnasplice": {
        "contrasts": "contrast filter: a contrast is a comparison between groups, not a sample",
        "splicing_genes": "gene-level filter on splicing results, not sample-level",
    },
    "scrnaseq": {
        "cellranger_cell_qc": "cell-level filters (cluster, QC status, UMI and gene counts), "
        "not sample-level",
    },
}


def _is_persistent(section: dict[str, Any]) -> bool:
    return bool(section.get("persistent") or section.get("pin"))


def _pinned_filter_components(dashboards: list[dict[str, Any]]) -> dict[str, list[str]]:
    """``{dc_tag: [component labels]}`` of interactive components in a persistent section."""
    out: dict[str, list[str]] = {}
    for dashboard in dashboards:
        for tab in _tabs(dashboard):
            pinned = {
                s["name"]
                for s in [*(tab.get("filter_sections") or []), *(tab.get("grid_sections") or [])]
                if s.get("name") and _is_persistent(s)
            }
            for c in _components(tab, "interactive"):
                if c.get("section") in pinned and c.get("data_collection_tag"):
                    out.setdefault(str(c["data_collection_tag"]), []).append(_label(c))
    return out


def _multiqc_dcs_with_panels(
    template: dict[str, Any], dashboards: list[dict[str, Any]]
) -> set[str]:
    """Tags of the template's MultiQC DCs that at least one multiqc panel reads."""
    declared = {
        str(dc.get("data_collection_tag"))
        for wf in template.get("workflows") or []
        for dc in wf.get("data_collections") or []
        if str((dc.get("config") or {}).get("type")).lower() == "multiqc"
    }
    used = {
        str(c.get("data_collection_tag"))
        for dashboard in dashboards
        for tab in _tabs(dashboard)
        for c in _components(tab, "multiqc")
    }
    return declared & used


def persistent_filter_problems(
    template_id: str,
    template: dict[str, Any],
    dashboards: list[dict[str, Any]],
    allowlist: dict[str, str],
) -> tuple[list[Violation], list[Violation]]:
    """``(unreached, stale_allowlist)`` for one parsed template. Pure: no files read.

    ``unreached``: a DC hosts a pinned filter, the template draws MultiQC panels,
    and no enabled link goes from that DC to the MultiQC DC. ``stale_allowlist``:
    an allowlisted DC that is no longer a violation (no pinned filter, or linked).
    """
    mqc = _multiqc_dcs_with_panels(template, dashboards)
    if not mqc:
        return [], []
    linked = {
        str(link.get("source_dc_tag"))
        for link in template.get("links") or []
        if link.get("enabled", True) and link.get("target_dc_tag") in mqc
    }
    pinned = _pinned_filter_components(dashboards)
    pipeline = template_id.split("/")[0]
    target = " or ".join(sorted(mqc))
    unreached: list[Violation] = []
    for dc_tag, labels in sorted(pinned.items()):
        if dc_tag in mqc or dc_tag in linked or dc_tag in allowlist:
            continue
        unreached.append(
            f"{template_id}: DC '{dc_tag}' hosts the pinned filter(s) {sorted(set(labels))} "
            f"but has no enabled link to the MultiQC DC '{target}', so the filter is ignored "
            f"on the MultiQC tab. Add to template.yaml links: (source_dc_tag: {dc_tag}, "
            f"source_column: <sample id column>, target_dc_tag: {target}, target_type: "
            f"multiqc, link_config: {{resolver: sample_mapping}}, enabled: true), or add "
            f"PINNED_FILTER_DCS_NOT_SAMPLE_LEVEL[{pipeline!r}][{dc_tag!r}] with the reason "
            f"it is not sample-level."
        )
    stale = [
        f"{template_id}: PINNED_FILTER_DCS_NOT_SAMPLE_LEVEL[{pipeline!r}][{dc_tag!r}] is stale "
        f"({'no pinned filter on it' if dc_tag not in pinned else 'it is linked to MultiQC now'})"
        f": remove the entry"
        for dc_tag in sorted(allowlist)
        if dc_tag not in pinned or dc_tag in linked or dc_tag in mqc
    ]
    return unreached, stale


def _load_template_and_dashboards(template_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    template_path = NF_CORE_DIR / template_id / "template.yaml"
    template = yaml.safe_load(template_path.read_text()) or {} if template_path.is_file() else {}
    dashboards = [yaml.safe_load(p.read_text()) or {} for p in _dashboard_files(template_id)]
    return template, dashboards


def check_persistent_filters_reach_multiqc(template_id: str) -> list[Violation]:
    template, dashboards = _load_template_and_dashboards(template_id)
    allowlist = PINNED_FILTER_DCS_NOT_SAMPLE_LEVEL.get(template_id.split("/")[0], {})
    unreached, _ = persistent_filter_problems(template_id, template, dashboards, allowlist)
    return unreached


def check_persistent_filter_allowlist_not_stale(template_id: str) -> list[Violation]:
    template, dashboards = _load_template_and_dashboards(template_id)
    allowlist = PINNED_FILTER_DCS_NOT_SAMPLE_LEVEL.get(template_id.split("/")[0], {})
    _, stale = persistent_filter_problems(template_id, template, dashboards, allowlist)
    return stale


_STEPS_BLOCK = re.compile(r"^:::\s*steps\s*$(.*?)^:::\s*$", re.M | re.S)
_STEP_ITEM = re.compile(r"^\s*\d+[.)]\s+")
_TAB_LINK = re.compile(r"\]\(tab:((?:[^()\n]|\([^()\n]*\))+)\)")
_VALUE_REF = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")


def _prunable_dcs(template: dict[str, Any]) -> set[str]:
    """Collections an import may lack: ``optional``, or removed by a ``conditional``."""
    out: set[str] = set()
    for workflow in template.get("workflows") or []:
        for dc in workflow.get("data_collections") or []:
            if dc.get("optional") and dc.get("data_collection_tag"):
                out.add(dc["data_collection_tag"])
    for cond in (template.get("template") or {}).get("conditional") or []:
        out.update(cond.get("remove_dc_tags") or [])
    return out


def _multiqc_dcs(template: dict[str, Any]) -> set[str]:
    return {
        dc["data_collection_tag"]
        for workflow in template.get("workflows") or []
        for dc in workflow.get("data_collections") or []
        if str((dc.get("config") or {}).get("type") or "").lower() == "multiqc"
    }


def _tab_name(tab: dict[str, Any]) -> str:
    return str(tab.get("title") or "")


def check_steps_cite_prunable_tabs(template_id: str) -> list[Violation]:
    template, dashboards = _load_template_and_dashboards(template_id)
    prunable = _prunable_dcs(template)
    multiqc = _multiqc_dcs(template)
    out: list[Violation] = []
    for dashboard in dashboards:
        tab_dcs = {
            _tab_name(tab): {
                str(c["data_collection_tag"])
                for c in _components(tab)
                if c.get("data_collection_tag")
            }
            for tab in dashboard.get("tabs") or []
        }
        main = dashboard.get("main_dashboard") or {}
        for c in _components(main, "text"):
            values = c.get("values") or {}
            for block in _STEPS_BLOCK.findall(str(c.get("body") or "")):
                for line in block.splitlines():
                    if not _STEP_ITEM.match(line):
                        continue
                    cited = {
                        str((values.get(name) or {}).get("dc") or "")
                        for name in _VALUE_REF.findall(line)
                    }
                    for name in _TAB_LINK.findall(line):
                        dcs = tab_dcs.get(name.strip())
                        if not dcs or not dcs <= prunable or dcs <= multiqc or cited & dcs:
                            continue
                        out.append(
                            f"{_label(c)}: the step linking tab {name.strip()!r} cites no "
                            f"value from its collections ({', '.join(sorted(dcs))})"
                        )
    return out


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version))


def _latest_template_ids() -> list[str]:
    """The highest version dir of each pipeline, as seeding and the CLI resolve it."""
    best: dict[str, str] = {}
    for tid in _template_ids():
        pipeline, version = tid.split("/")
        if pipeline not in best or _version_key(version) > _version_key(
            best[pipeline].split("/")[1]
        ):
            best[pipeline] = tid
    return sorted(best.values())


RULES: dict[str, Callable[[str], list[Violation]]] = {
    "pinned_table_not_repeated": check_pinned_table_not_repeated,
    "top_n_only_under_sum": check_top_n_only_under_sum,
    "threshold_warn_side": check_threshold_warn_side,
    "text_intro_length": check_text_intro_length,
    "forbidden_terms": check_forbidden_terms,
    "group_col_in_filter_expr": check_group_col_in_filter_expr,
    "no_mean_of_percentages": check_no_mean_of_percentages,
    "record_card_linked_source": check_record_card_linked_source,
    "record_card_linked": check_record_card_linked,
    "persistent_filters_reach_multiqc": check_persistent_filters_reach_multiqc,
    "steps_cite_prunable_tabs": check_steps_cite_prunable_tabs,
}


def collect_violations() -> dict[str, dict[str, list[Violation]]]:
    """``{rule: {template_id: [violations]}}`` over every linted template."""
    return {
        rule: {tid: v for tid in _template_ids() if (v := check(tid))}
        for rule, check in RULES.items()
    }


TEMPLATE_IDS = _template_ids()
LATEST_TEMPLATE_IDS = _latest_template_ids()


def _assert_clean(violations: list[Violation]) -> None:
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize("template_id", LATEST_TEMPLATE_IDS)
def test_steps_cite_prunable_tabs(template_id: str) -> None:
    _assert_clean(check_steps_cite_prunable_tabs(template_id))


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


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_no_group_col_in_filter_expr(template_id: str) -> None:
    _assert_clean(check_group_col_in_filter_expr(template_id))


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


@pytest.mark.parametrize("template_id", LATEST_TEMPLATE_IDS)
def test_persistent_filters_reach_multiqc(template_id: str) -> None:
    _assert_clean(check_persistent_filters_reach_multiqc(template_id))


@pytest.mark.parametrize("template_id", LATEST_TEMPLATE_IDS)
def test_persistent_filter_allowlist_not_stale(template_id: str) -> None:
    _assert_clean(check_persistent_filter_allowlist_not_stale(template_id))


def test_persistent_filter_allowlist_names_shipped_pipelines() -> None:
    pipelines = {tid.split("/")[0] for tid in LATEST_TEMPLATE_IDS}
    assert set(PINNED_FILTER_DCS_NOT_SAMPLE_LEVEL) <= pipelines
    assert all(
        r.strip() for dcs in PINNED_FILTER_DCS_NOT_SAMPLE_LEVEL.values() for r in dcs.values()
    )


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


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # Layout only: a steps flow, tab tiles under group headings, findings rows.
        (
            "::: steps\n1. ![](icon:mdi:dna) **Trim** primers. [Settings](params:primer)\n"
            "2. ![](icon:mdi:filter) **Denoise** DADA2\n:::",
            0,
        ),
        (
            "### Data & QC\n- [MultiQC](tab:MultiQC): Did the run work?\n"
            "### Taxa\n1. [Community](tab:Community): Who is there?\n"
            "2. [Differential](tab:Differential): What differs?",
            0,
        ),
        (
            "- **{{share}}** of reads are {{top}}. [Community](tab:Community)\n"
            "- **{{n_sig}}** phyla differ. [Differential](tab:Differential)",
            0,
        ),
        # Prose around the layout still counts.
        ("## How to read\nStart with the overview. Then open a tab.\n- [QC](tab:QC): ok", 2),
        ("Plain prose. With [a link](tab:QC). And a third.", 3),
    ],
)
def test_sentence_rule_counts_prose_only(body: str, expected: int) -> None:
    assert count_sentences(prose_of(body)) == expected


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
                    {
                        "component_type": "card",
                        "tag": "bygroup",
                        "aggregation": "max",
                        "column_name": "r2",
                        "filter_expr": "col('term') == '{GROUP_COL}'",
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
    [by_group] = check_group_col_in_filter_expr(tid)
    assert " bygroup.filter_expr: " in by_group


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


def _synthetic_pinned_filter_template(
    links: list[dict[str, Any]], panel: bool = True
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    template = {
        "workflows": [
            {
                "data_collections": [
                    {"data_collection_tag": "samples", "config": {"type": "Table"}},
                    {"data_collection_tag": "metrics", "config": {"type": "Table"}},
                    {"data_collection_tag": "multiqc_data", "config": {"type": "MultiQC"}},
                ]
            }
        ],
        "links": links,
    }

    def interactive(tag: str, dc: str, section: str) -> Component:
        return {
            "component_type": "interactive",
            "tag": tag,
            "section": section,
            "data_collection_tag": dc,
        }

    mqc_panel = {
        "component_type": "multiqc",
        "tag": "fastqc",
        "data_collection_tag": "multiqc_data",
    }
    dashboard = {
        "main_dashboard": {
            "title": "Overview",
            "filter_sections": [
                {"name": "Sample filters", "persistent": True, "pin": "top"},
                {"name": "Local", "icon": "mdi:filter"},
            ],
            "components": [
                interactive("pick-sample", "samples", "Sample filters"),
                interactive("min-frip", "metrics", "Sample filters"),
                # Not pinned: a tab-local filter needs no link.
                interactive("local-metric", "metrics", "Local"),
            ],
        },
        "tabs": [{"title": "MultiQC", "components": [mqc_panel] if panel else []}],
    }
    return template, [dashboard]


def _mqc_link(source: str, enabled: bool = True) -> dict[str, Any]:
    return {
        "source_dc_tag": source,
        "source_column": "sample",
        "target_dc_tag": "multiqc_data",
        "target_type": "multiqc",
        "link_config": {"resolver": "sample_mapping"},
        "enabled": enabled,
    }


def test_persistent_filter_on_unlinked_dc_is_reported() -> None:
    template, dashboards = _synthetic_pinned_filter_template([_mqc_link("samples")])
    unreached, stale = persistent_filter_problems("demo/1.0.0", template, dashboards, {})
    assert stale == []
    [problem] = unreached
    # Names the template, the DC, the component and both ways out.
    assert problem.startswith("demo/1.0.0: DC 'metrics' hosts the pinned filter(s) ['min-frip']")
    assert "local-metric" not in problem
    assert "template.yaml links:" in problem
    assert "PINNED_FILTER_DCS_NOT_SAMPLE_LEVEL['demo']['metrics']" in problem


def test_persistent_filter_on_linked_dcs_is_clean() -> None:
    template, dashboards = _synthetic_pinned_filter_template(
        [_mqc_link("samples"), _mqc_link("metrics")]
    )
    assert persistent_filter_problems("demo/1.0.0", template, dashboards, {}) == ([], [])


def test_persistent_filter_disabled_link_does_not_count() -> None:
    template, dashboards = _synthetic_pinned_filter_template(
        [_mqc_link("samples"), _mqc_link("metrics", enabled=False)]
    )
    [problem] = persistent_filter_problems("demo/1.0.0", template, dashboards, {})[0]
    assert "DC 'metrics'" in problem


def test_persistent_filter_allowlist_silences_and_goes_stale() -> None:
    template, dashboards = _synthetic_pinned_filter_template([_mqc_link("samples")])
    allow = {"metrics": "QC thresholds on a metrics DC"}
    assert persistent_filter_problems("demo/1.0.0", template, dashboards, allow) == ([], [])
    # Once the DC is linked, the entry has no reason left to exist.
    linked, dashboards = _synthetic_pinned_filter_template(
        [_mqc_link("samples"), _mqc_link("metrics")]
    )
    unreached, stale = persistent_filter_problems("demo/1.0.0", linked, dashboards, allow)
    assert unreached == []
    assert len(stale) == 1
    assert "['metrics'] is stale" in stale[0]
    # An entry for a DC that hosts no pinned filter is stale too.
    _, stale = persistent_filter_problems("demo/1.0.0", template, dashboards, {"nowhere": "x"})
    assert len(stale) == 1


def test_persistent_filter_rule_is_vacuous_without_multiqc_panels() -> None:
    template, dashboards = _synthetic_pinned_filter_template([], panel=False)
    assert persistent_filter_problems("demo/1.0.0", template, dashboards, {}) == ([], [])
    # A declared MultiQC DC that no panel reads does not count either.
    assert persistent_filter_problems("demo/1.0.0", {**template, "links": []}, [], {}) == ([], [])
