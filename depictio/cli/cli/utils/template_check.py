"""What a template does with a run's parameters: the engine of ``depictio template check``.

For a pipeline developer reading a Depictio template, three questions:

* which of the template's variables are set by a ``from_params`` rule, which
  are found in the outputs, and which only a user can pass (``--var``);
* for a given run (its ``params_<ts>.json``) or a default run (the release's
  ``nextflow_schema.json`` defaults), which rules hold and what each conditional
  then removes or repoints;
* whether every param a rule reads exists in the targeted release, and which
  ``skip_*`` params of that release no rule reads.

Pure functions over a ``TemplateMetadata``; no server, no FastAPI: this runs on
the CLI-only install, and in CI (``.github/workflows/template-params.yaml``).
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from depictio.models.models.templates import (
    ParamRule,
    TemplateConditional,
    TemplateMetadata,
    _truthy,
)

SCHEMA_URL = "https://raw.githubusercontent.com/nf-core/{pipeline}/{release}/nextflow_schema.json"

# Variables the CLI fills from the run itself, not from a rule (see
# ``resolve_template_config`` and ``_introspect_pipeline_params``).
AUTO_VARIABLES = {
    "DATA_ROOT": "the results directory given to `depictio ingest`",
    "SAMPLESHEET_FILE": "found in `input/` (samplesheet*.csv|tsv)",
    "METADATA_FILE": "found in `input/` when the run had `--metadata`",
    "PPLACE_TREE_FILE": "found in `pplace/` when the run had `--pplace_tree`",
    "PHYLUM_LEVEL": "read from the QIIME2 barplots / DADA2 taxonomy",
    "CLASS_LEVEL": "PHYLUM_LEVEL + 1",
    "ORDER_LEVEL": "PHYLUM_LEVEL + 2",
    "FAMILY_LEVEL": "PHYLUM_LEVEL + 3",
    "GENUS_LEVEL": "PHYLUM_LEVEL + 4",
}


# -- the pipeline's schema -------------------------------------------------------


@dataclass(frozen=True)
class SchemaParam:
    name: str
    type: str | None
    default: Any
    group: str | None


def schema_params(schema: dict) -> dict[str, SchemaParam]:
    """Every parameter of an nf-core ``nextflow_schema.json``: draft-07
    ``definitions`` or 2020-12 ``$defs`` groups, plus top-level ``properties``."""

    def take(props: dict, group: str | None) -> None:
        for name, spec in props.items():
            spec = spec if isinstance(spec, dict) else {}
            found[name] = SchemaParam(name, spec.get("type"), spec.get("default"), group)

    found: dict[str, SchemaParam] = {}
    take(schema.get("properties", {}), None)
    for key in ("definitions", "$defs"):
        for group_name, group in schema.get(key, {}).items():
            take(group.get("properties", {}), group.get("title") or group_name)
    return found


def schema_defaults(params: dict[str, SchemaParam]) -> dict[str, Any]:
    """The params of a run made with no option: each param's schema default."""
    return {name: p.default for name, p in params.items() if p.default is not None}


def nfcore_target(template_id: str) -> tuple[str, str] | None:
    """``("rnaseq", "3.26.0")`` for ``nf-core/rnaseq/3.26.0[/…]``, else None."""
    parts = template_id.split("/")
    if len(parts) >= 3 and parts[0] == "nf-core":
        return parts[1], parts[2]
    return None


def fetch_schema(pipeline: str, release: str, cache: Path | None = None) -> dict:
    """The release's ``nextflow_schema.json`` from GitHub (raw, no API quota)."""
    cached = cache / f"{pipeline}-{release}.json" if cache else None
    if cached and cached.is_file():
        return json.loads(cached.read_text())
    url = SCHEMA_URL.format(pipeline=pipeline, release=release)
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 (fixed https host)
        text = resp.read().decode()
    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(text)
    return json.loads(text)


# -- the template ----------------------------------------------------------------


def rule_text(rule: ParamRule) -> str:
    """A rule as it reads in template.yaml, in YAML flow style."""
    if rule.any is not None or rule.all is not None:
        key, group = ("any", rule.any) if rule.any is not None else ("all", rule.all)
        return "{" + f"{key}: [" + ", ".join(rule_text(r) for r in group or []) + "]}"
    for key, value in (
        ("is", rule.is_),
        ("equals", rule.equals),
        ("not_equals", rule.not_equals),
        ("contains", rule.contains),
        ("not_contains", rule.not_contains),
    ):
        if value is not None:
            shown = str(value).lower() if isinstance(value, bool) else value
            return f"{{param: {rule.param}, {key}: {shown}}}"
    return f"{{param: {rule.param}}}"


def effect_text(cond: TemplateConditional, default_dashboards: list[str] | None = None) -> str:
    """What a conditional does when it fires, in one line (a dashboard list equal
    to the template's own is no change, and is left out)."""
    parts = []
    if cond.remove_dc_tags:
        parts.append("drops " + ", ".join(cond.remove_dc_tags))
    if cond.override_dcs:
        parts.append("repoints " + ", ".join(o.data_collection_tag for o in cond.override_dcs))
    if cond.dashboards and cond.dashboards != (default_dashboards or []):
        parts.append("dashboards " + ", ".join(cond.dashboards))
    return "; ".join(parts) or "no effect"


def _names(text: str, tool: str) -> bool:
    """Whether ``text`` names ``tool`` as a word (``qc`` in ``deseq2_qc_pca``, not
    in ``multiqc``): letters and digits join a word, ``_`` ``/`` ``.`` split it."""
    return (
        re.search(rf"(?<![a-z0-9]){re.escape(tool.lower())}(?![a-z0-9])", text.lower()) is not None
    )


def _condition(cond: TemplateConditional) -> tuple[str, bool]:
    """(variable, fires when present)."""
    if cond.if_var_present is not None:
        return cond.if_var_present, True
    return cond.if_var_absent or "", False


@dataclass
class VariableRow:
    name: str
    source: str  # rule | auto | user | required
    how: str  # the rule, or where an auto variable comes from
    params: list[str] = field(default_factory=list)
    on_default_run: bool | None = None  # rule only, with a schema
    on_this_run: bool | None = None  # set for this run (rules: holds; others: provided)
    effects: list[str] = field(default_factory=list)


@dataclass
class FiredConditional:
    condition: str
    effect: str


@dataclass
class TemplateCheck:
    template_id: str
    path: Path | None
    rows: list[VariableRow]
    fired: list[FiredConditional] | None  # None without a run
    unknown_params: dict[str, list[str]]  # variable -> params the release lacks
    unread_skip_params: list[str]  # skip_* params of the release no rule reads
    schema_checked: bool
    run_vars: dict[str, str] = field(default_factory=dict)
    # ...of which the tool they skip is named in the template (a DC tag, a path):
    # a run with that flag may lack files the template reads.
    suspect_skip_params: list[str] = field(default_factory=list)

    @property
    def rule_count(self) -> int:
        return sum(r.source == "rule" for r in self.rows)

    @property
    def ok(self) -> bool:
        return not self.unknown_params


def check_template(
    meta: TemplateMetadata,
    *,
    path: Path | None = None,
    schema: dict | None = None,
    run_params: dict | None = None,
    run_vars: dict[str, str] | None = None,
    template_text: str = "",
) -> TemplateCheck:
    """Classify the template's variables, evaluate its rules and its conditionals.

    ``run_params``: the run's ``params_<ts>.json`` (or None: no run). ``run_vars``:
    explicit ``--var`` values plus what the outputs gave (auto variables); a
    ``--var X=false`` on a rule variable unsets it, as ``apply_params_rules``
    does at ingestion. ``template_text``: the template's YAML (and dashboards),
    where an unread ``skip_<tool>`` whose ``<tool>`` appears is flagged.
    """
    known = schema_params(schema) if schema is not None else None
    defaults = schema_defaults(known) if known is not None else None
    explicit = dict(run_vars or {})

    effects: dict[str, list[str]] = {}
    for cond in meta.conditional:
        var, present = _condition(cond)
        effects.setdefault(var, []).append(
            f"{'set' if present else 'unset'} → {effect_text(cond, meta.dashboards)}"
        )

    rows: list[VariableRow] = []
    unknown: dict[str, list[str]] = {}
    read_by_rules: set[str] = set()
    for var in meta.variables:
        row = VariableRow(var.name, "user", var.description, effects=effects.get(var.name, []))
        if var.from_params is not None:
            used = sorted(var.from_params.params_used())
            read_by_rules |= set(used)
            row.source, row.how, row.params = "rule", rule_text(var.from_params), used
            if known is not None:
                missing = [p for p in used if p not in known]
                if missing:
                    unknown[var.name] = missing
                row.on_default_run = var.from_params.holds(defaults or {})
        elif var.name in AUTO_VARIABLES:
            row.source, row.how = "auto", AUTO_VARIABLES[var.name]
        elif var.required:
            row.source = "required"
        rows.append(row)

    fired: list[FiredConditional] | None = None
    present: dict[str, str] = {}
    if run_params is not None or run_vars:
        present = dict(explicit)
        if run_params:
            for name, value in meta.variables_from_params(run_params).items():
                present.setdefault(name, value)
        for var in meta.variables:
            if var.from_params is not None and var.name in present:
                if not _truthy(present[var.name]):
                    del present[var.name]
        for row in rows:
            row.on_this_run = row.name in present
        fired = []
        for cond in meta.conditional:
            var, when_present = _condition(cond)
            if (var in present) == when_present:
                label = f"{'if_var_present' if when_present else 'if_var_absent'}: {var}"
                fired.append(FiredConditional(label, effect_text(cond, meta.dashboards)))

    unread = []
    if known is not None:
        unread = sorted(
            n
            for n, p in known.items()
            if n.startswith("skip_") and p.type == "boolean" and n not in read_by_rules
        )
    return TemplateCheck(
        template_id=meta.template_id,
        path=path,
        rows=rows,
        fired=fired,
        unknown_params=unknown,
        unread_skip_params=unread,
        suspect_skip_params=[n for n in unread if _names(template_text, n.removeprefix("skip_"))],
        schema_checked=known is not None,
        run_vars=present,
    )
