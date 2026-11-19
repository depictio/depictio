"""Declarative bio-catalog: the tool→viz **linking table**.

For each tool output, one catalog entry links:

  - `find`        — how to recognise the raw nf-core file (used at scan time).
  - `recipe`      — optional `.py` that reshapes it. **The recipe owns the
                    output columns** (its `OUTPUT_SCHEMA`); the catalog does
                    not repeat them.
  - `columns`     — the bindable columns, declared **only when there is no
                    recipe** (raw == bindable). Omitted when a recipe is present.
  - `renders_as`  — which dashboard component(s) render it (advanced viz,
                    MultiQC plot, table…) + the role→column binding.
  - identity      — bio.tools / nf-core / EDAM URLs (robust anchors).

Anchored on bio.tools & nf-core for robustness, and consumed at **scan time**
to build or assist dashboards. This catalog is *not* a runtime column→viz
suggestion engine (`schemas.suggest_viz_kinds` does that from a DC schema); it is
the file → recipe → component map.

The model layer stays offline + import-cheap: it never imports recipe `.py`
files. Cross-checking `renders_as` roles against a recipe's real output columns
is done by `depictio catalog validate` (a trusted CLI/CI context), not here.
"""

from __future__ import annotations

from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from depictio.models.components.lite import CardLiteComponent, ReferenceLine
from depictio.models.components.types import (
    AdvancedVizKind,
    AggregationFunction,
    ChartType,
    ComponentType,
    InteractiveType,
)

CATALOG_DIR = Path(__file__).resolve().parents[3] / "catalog"

# Figure kwargs a render may not set: RULES.md §7 keeps colours in the
# dashboard's ``category_colors`` (or a continuous scale), never in a per-figure
# map, so a value keeps its colour on every tile that draws it.
_FORBIDDEN_FIGURE_KWARGS: frozenset[str] = frozenset(
    {"color_discrete_map", "color_discrete_sequence"}
)

# plotly-express kwargs whose VALUES are column names (grounded against data);
# other dict_kwargs (title, points, log_x…) are passed through untouched.
_FIGURE_COLUMN_KWARGS: frozenset[str] = frozenset(
    {"x", "y", "color", "facet_col", "facet_row", "size", "symbol", "names", "values", "hover_name"}
)

# Render targets = depictio's real component registry (`ComponentType`:
# advanced_viz, figure, table, card, text, jbrowse, image, map) plus the
# dash-module `multiqc` component. Validated against the actual components, so a
# catalog entry can only target a component that exists.
ComponentKind = ComponentType | Literal["multiqc"]

# How a multi-metric card renders its secondary strip. Derived from
# ``CardLiteComponent`` rather than re-spelled, so a layout added there can't be
# rejected here — the two had already drifted once.
CardLayout = CardLiteComponent.model_fields["secondary_layout"].annotation

# Layouts that require a ``breakdown_col``. Single source of truth in
# ``card_breakdown``; imported lazily below to keep the models package free of
# an API-layer import at module scope.
_BREAKDOWN_CARD_LAYOUTS = ("top_n", "concentration", "composition", "donut")


def _check_identity_urls(
    nf_core_url: str | None,
    biotools_url: str | None,
    edam: dict[str, list[str]],
    source_url: str | None = None,
) -> None:
    """Validate identity references point at the right authority (offline check).

    Format-level only: guarantees well-formed bio.tools / nf-core / EDAM refs.
    Existence (the term/module is real) is a CI step against a vendored index.
    `source_url` (Snakemake/Galaxy fetch origin) has no authority to check
    against, so only its scheme is asserted.
    """
    if biotools_url and not biotools_url.startswith("https://bio.tools/"):
        raise ValueError(f"biotools_url must be a https://bio.tools/ URL, got {biotools_url!r}")
    if nf_core_url and "github.com/nf-core/modules" not in nf_core_url:
        raise ValueError(
            f"nf_core_url must point at github.com/nf-core/modules/..., got {nf_core_url!r}"
        )
    if source_url and not source_url.startswith(("http://", "https://")):
        raise ValueError(f"source_url must be an http(s):// URL, got {source_url!r}")
    for category, urls in edam.items():  # category -> expected EDAM prefix
        for url in urls:
            if not url.startswith(f"http://edamontology.org/{category}_"):
                raise ValueError(
                    f"edam_{category} entries must be http://edamontology.org/{category}_NNNN URLs, "
                    f"got {url!r}"
                )


# Where an output sits in a pipeline, in reading order. A composed dashboard opens
# one tab per stage present, in this order (`depictio template compose`); a tool
# declares its stage in `module.yaml` and an output overrides it when it belongs
# elsewhere (a MultiQC section is FastQC's QC or STAR's alignment numbers).
Stage = Literal[
    "qc",
    "alignment",
    "quantification",
    "peaks",
    "variants",
    "fusions",
    "taxonomy",
    "annotation",
    "immune",
    "differential",
    "benchmarking",
    "other",
]
STAGE_ORDER: tuple[str, ...] = get_args(Stage)
STAGE_LABELS: dict[str, str] = {
    "qc": "Quality control",
    "alignment": "Alignment & coverage",
    "quantification": "Quantification",
    "peaks": "Peaks",
    "variants": "Variants",
    "fusions": "Fusions",
    "taxonomy": "Taxonomy & diversity",
    "annotation": "Functional annotation",
    "immune": "Immune repertoire",
    "differential": "Differential analysis",
    "benchmarking": "Benchmarking",
    "other": "Other results",
}


# Accepted polars dtype names for `columns` (string form, as polars prints them).
ALLOWED_DTYPES: frozenset[str] = frozenset(
    {
        "String",
        "Int64",
        "Int32",
        "UInt32",
        "UInt64",
        "Float64",
        "Float32",
        "Boolean",
        "Date",
        "Datetime",
        "Time",
        "Categorical",
        "List",
    }
)


# Roles a kind binds as an ordered LIST of columns rather than a single one.
# `buildAdvancedVizConfigBlob` (viewer) maps them onto the list-typed config
# fields — `steps` → ``SankeyConfig.step_cols``, `ranks` → ``rank_cols``,
# `value_columns` / `row_annotation_cols` → the ComplexHeatmap fields of the
# same name. Mirrors depictio/viewer/src/builder/advanced_viz/configBlob.ts;
# without them the builder could bind a sankey the catalog had no way to spell,
# so the binding was dropped on export and the render could never work.
_LIST_ROLES: dict[str, frozenset[str]] = {
    "sankey": frozenset({"steps"}),
    "sunburst": frozenset({"ranks"}),
    "complex_heatmap": frozenset({"value_columns", "row_annotation_cols"}),
    # The markers a spatial_cells tile's colour picker offers.
    "spatial_cells": frozenset({"value_columns"}),
}

# Roles that pick a *setting* rather than a column, so they are accepted as
# bindings but never grounded against the data shape.
_NON_COLUMN_ROLES: dict[str, frozenset[str]] = {
    "embedding": frozenset({"compute_method"}),
}


def role_config_key(kind: str | None, role: str) -> str:
    """The per-kind config field a role binds to.

    The Python twin of `buildAdvancedVizConfigBlob`
    (depictio/viewer/src/builder/advanced_viz/configBlob.ts): most roles become
    ``<role>_col``, the list-typed ones have their own field names, and
    `compute_method` is a scalar setting. Kept here so the catalog preview
    payload and the `use:` inheritance both spell a binding the same way the
    builder does — a mismatch silently hands the renderer an unknown key.
    """
    if kind == "sunburst" and role == "ranks":
        return "rank_cols"
    if kind == "sankey" and role == "steps":
        return "step_cols"
    if kind == "complex_heatmap" and role == "index":
        # ComplexHeatmapConfig's row-id field is `index_column`, not `index_col`.
        return "index_column"
    if role in ("value_columns", "row_annotation_cols", "compute_method"):
        return role
    return f"{role}_col"


# Kinds that read a structure from an `indexed_file` collection (`file`, the
# model default) or fetch one for a UniProt accession, a gene or a sequence.
_STRUCTURE_KINDS = frozenset({"molecule_3d", "ramachandran"})


def with_inferred_structure_source(kind: str | None, config: dict) -> dict:
    """Mark a structure tile that binds an accession, gene or sequence as `resolve`.

    A catalog render carries roles only, and the model defaults to `file`: a tile
    bound to `sequence` and to no structure collection then went looking for a
    collection nobody bound and failed to render. Anything already said (a
    `structure_source`, a structure collection) is left alone.
    """
    if (
        kind in _STRUCTURE_KINDS
        and "structure_source" not in config
        and not (config.get("structure_dc_id") or config.get("structure_dc_tag"))
        and any(config.get(key) for key in ("uniprot_col", "gene_col", "sequence_col"))
    ):
        return {**config, "structure_source": "resolve"}
    return config


def _allowed_roles(kind: AdvancedVizKind) -> set[str]:
    """Every role name a kind accepts: required + optional (the vocabulary the
    builder's binding panel offers), plus its list-typed and setting roles."""
    from depictio.models.components.advanced_viz.schemas import role_dtype_specs

    return (
        set(role_dtype_specs(kind))
        | set(_LIST_ROLES.get(kind, frozenset()))
        | set(_NON_COLUMN_ROLES.get(kind, frozenset()))
    )


# ---------------------------------------------------------------------------
# Recognition: how to find the raw file in a scanned run (MultiQC-style)
# ---------------------------------------------------------------------------


class CatalogFind(BaseModel):
    """How to recognise the raw output file among a scanned run's files."""

    filename: str | None = None  # glob on the basename, e.g. "*.pangolin.csv"
    path_glob: str | None = None  # glob on the path under the run root (** aware)
    # Extra path globs for layouts the canonical `path_glob` cannot reach; every
    # entry of `path_globs()` is tried. `PurePosixPath.match` reads `**` as one
    # segment (`full_match` is 3.13-only), so a nested report dir such as
    # `multiqc/star_salmon/multiqc_report_data/` needs its own literal-depth glob.
    path_glob_alt: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _at_least_one(self) -> CatalogFind:
        if self.path_glob_alt and not self.path_glob:
            raise ValueError("path_glob_alt requires path_glob")
        if not (self.filename or self.path_glob):
            raise ValueError("find must declare at least one of: filename, path_glob")
        return self

    def path_globs(self) -> list[str]:
        """Every path glob to try, canonical first; empty when there is no `path_glob`."""
        if not self.path_glob:
            return []
        return [self.path_glob, *self.path_glob_alt]


def _config_columns(config: dict[str, Any]) -> set[str]:
    """Columns a render's viz `config` names (`*_col` keys and column lists).

    A display option such as `color_col` or `value_columns` still points at a
    column, so it is grounded like a role.
    """
    cols: set[str] = set()
    for key, value in config.items():
        if key.endswith("_col") and isinstance(value, str) and value:
            cols.add(value)
        elif key in ("value_columns", "row_annotation_cols") and isinstance(value, list):
            cols |= {v for v in value if isinstance(v, str) and v}
    return cols


@lru_cache(maxsize=1)
def _viz_config_models() -> dict[str, type[BaseModel]]:
    """``viz_kind -> config model``, read off the discriminated union.

    Imported lazily: the config models are heavy and this module stays
    import-cheap for the CLI.
    """
    from depictio.models.components.advanced_viz import configs

    union = get_args(configs._VizConfigUnion)[0]
    models: dict[str, type[BaseModel]] = {}
    for model in get_args(union):
        for kind in get_args(model.model_fields["viz_kind"].annotation):
            models[kind] = model
    return models


def _check_viz_config(kind: str, roles: dict[str, Any], config: dict[str, Any]) -> None:
    """Reject a render `config` key the kind's config model does not have.

    A retired kind (`ma`, `qq`...) is checked against the model it is rewritten
    into, the way every stored config is. Only the keys are checked here: the
    values are validated with the bound roles when the component is built.
    A key a role already derives is refused, so a binding has one home.
    """
    if not config:
        return
    from depictio.models.components.advanced_viz.configs import resolve_viz_kind

    model = _viz_config_models().get(resolve_viz_kind(kind) or kind)
    if model is None:
        raise ValueError(f"renders_as {kind}: no config model, so 'config' cannot be set")
    if "viz_kind" in config:
        raise ValueError(f"renders_as {kind}: 'viz_kind' comes from 'kind', not 'config'")
    unknown = set(config) - set(model.model_fields)
    if unknown:
        raise ValueError(
            f"renders_as {kind}: unknown config key(s) {sorted(unknown)} for {model.__name__}"
        )
    from_roles = {role_config_key(kind, r) for r in roles} & set(config)
    if from_roles:
        raise ValueError(
            f"renders_as {kind}: config key(s) {sorted(from_roles)} are set by 'roles' already"
        )
    # The values too: a 41-character axis label or a negative top-N passes the key
    # check and only fails when the dashboard is imported. Validated alone, without
    # the roles, so a field the roles fill is left at its default here.
    from pydantic import ValidationError

    from depictio.models.components.advanced_viz.configs import apply_kind_aliases

    try:
        model.model_validate(apply_kind_aliases({**config, "viz_kind": kind}))
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors()
            if e["loc"] and e["loc"][0] in config
        ]
        if problems:
            raise ValueError(f"renders_as {kind}: invalid config {problems}") from None


# ---------------------------------------------------------------------------
# Versions
#
# A module (`module.yaml` `version`) is the unit the locks hold: one revision of
# each module is kept, and a template records the revisions it consumes. Inside
# it, an output or a render may say *since which module revision* it is as it is
# now (`version`, optional). Unset, it reads as "unchanged since an earlier
# revision, or never said": the module's revision still covers it. A module may
# also keep a `changelog`, newest first, whose top entry is its current version.
# ---------------------------------------------------------------------------

SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"


def semver_key(version: str) -> tuple[int, int, int]:
    """``"1.10.0"`` -> ``(1, 10, 0)``: compares as numbers, not as text."""
    major, minor, patch = (int(p) for p in version.split("."))
    return major, minor, patch


class ChangelogEntry(BaseModel):
    """One revision of a module: its version and what changed in it."""

    version: str = Field(pattern=SEMVER_PATTERN)
    # ISO day (YYYY-MM-DD), optional: the catalog has no release clock of its own.
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    # One line per change. Name the output or render it concerns, so a reader of
    # the gallery can tell which changes touch what they use.
    changes: list[str] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class Render(BaseModel):
    """One render target for an output: a dashboard component + its binding.

    - `advanced_viz` → `kind` + `roles` (role → column).
    - `figure` → either UI mode (`visu_type` + `dict_kwargs`, plotly-express) or
      code mode (`code`: an inline snippet that sets `fig`, depictio's
      figure `code_content`).
    - `card` → `column` + `aggregation` (a metric/KPI).
    - `interactive` → `interactive_type` + `column_name`, the two fields
      `InteractiveLiteComponent` requires to instantiate a filter control.
    - `table` → optional display options mirroring `TableLiteComponent`.
    - `multiqc`/`text`/… → no extra binding.

    An optional `id` makes the render a first-class, tool-unique handle so a
    dashboard can address it directly with ``use: <tool>/<render-id>`` — no need
    to name the output and disambiguate with ``viz_kind``. Ids only need to be
    unique within a tool (enforced on the entry), and a render binds to its
    parent output's columns, so the id lives here, never in ``module.yaml``.
    """

    # Optional tool-unique handle for `use: <tool>/<id>` (advanced_viz renders).
    id: str | None = None
    component: ComponentKind
    # The module revision this render last changed in (see "Versions" above).
    # Optional; never above the module's `version`.
    version: str | None = Field(default=None, pattern=SEMVER_PATTERN)
    # Ordering when a dashboard is composed from the catalog: lower comes first
    # within its output; unset renders keep their declared order after the set ones.
    priority: int | None = Field(default=None, ge=0)
    # Every component: the tile title, and the text of its info popover
    # ("About this component"). The description follows RULES.md §14: a lead,
    # then `How to read:`, `Lines and annotations:` (every mark drawn, with its
    # value and source) and `Source:` paragraphs, separated by blank lines.
    title: str | None = None
    description: str | None = None
    # advanced_viz
    kind: AdvancedVizKind | None = None
    # advanced_viz: the kind's display options and reference marks, merged over
    # the role bindings (`top_n_labels`, `legend_pos`, `effect_label`,
    # `score_threshold`, `reference_line`, `shaded_bands`, `color_mode`...).
    # Keys are checked against the kind's config model; column bindings belong
    # in `roles`, not here.
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind", mode="before")
    @classmethod
    def _renamed_kind(cls, value: object) -> object:
        """A catalog entry may still name `stacked_taxonomy`, which is `stacked_bar` now.

        Only this one rename: the kinds merged into a survivor (`ma`, `qq`, ...)
        keep their own catalog roles, which differ from the survivor's.
        """
        return "stacked_bar" if value == "stacked_taxonomy" else value

    # viz role -> column, or -> ordered column list for the few list-typed
    # roles (see `_LIST_ROLES`).
    roles: dict[str, str | list[str]] = Field(default_factory=dict)
    # figure
    visu_type: ChartType | None = None  # UI mode: box/scatter/bar/histogram…
    # plotly-express kwargs. Column-valued keys (x, y, color...) are strings
    # grounded against the data; `labels` maps column -> axis or legend title.
    dict_kwargs: dict[str, Any] = Field(default_factory=dict)
    code: str | None = None  # code mode: inline Python that sets `fig`
    # UI mode: guide lines, fixed (`value`) or at a statistic of a column over
    # the rows on show (`stat` + `column`, named "median of this table"; RULES
    # §17). Mirrors `FigureLiteComponent.reference_lines`.
    reference_lines: list[ReferenceLine] = Field(default_factory=list)
    # card (single- or multi-metric)
    column: str | None = None
    aggregation: AggregationFunction | None = None  # hero metric
    aggregations: list[AggregationFunction] = Field(
        default_factory=list
    )  # secondary (multi-metric)
    secondary_layout: CardLayout | None = None  # vertical/compact/box_plot(Tukey)/top_n/coverage/…
    breakdown_col: str | None = None  # group-by column for top_n / concentration / composition
    top_n_count: int | None = Field(default=None, ge=1, le=5)
    coverage_max: float | None = None  # denominator for secondary_layout=coverage/gauge
    threshold_value: float | None = None  # QC cut-off for secondary_layout=threshold
    threshold_direction: Literal["min", "max"] | None = None  # which side passes
    threshold_warn: float | None = None  # optional warn band
    attrition_cols: list[str] = Field(default_factory=list)  # stages for =attrition
    trend_col: str | None = None  # ordered axis for secondary_layout=trend
    filter_expr: str | None = None  # optional polars pre-filter
    # What the secondary strip shows ("median, with its spread"); without it the
    # card prints the bare aggregation ("(Average)"). RULES.md §5.
    caption: str | None = None
    # A card worth a place in a composed dashboard's Overview: the run's key
    # metrics, the way MultiQC's General Statistics picks a few columns per tool.
    headline: bool = False
    # interactive — both are required by InteractiveLiteComponent, so a render
    # carrying neither could not be turned into a filter control at all.
    interactive_type: InteractiveType | None = None  # Select/MultiSelect/Slider/…
    column_name: str | None = None  # column the control filters on
    # table — optional display options, mirroring TableLiteComponent field for
    # field. All default to "unset" so a bare `{component: table}` still means
    # "every column, defaults", which is what the committed entries say.
    columns: list[str] = Field(default_factory=list)  # displayed columns (empty = all)
    page_size: int | None = Field(default=None, ge=1, le=500)
    sortable: bool | None = None
    filterable: bool | None = None
    row_selection_enabled: bool | None = None  # row selection filters other components
    row_selection_column: str | None = None  # column extracted from selected rows
    # multiqc
    section: str | None = None

    model_config = ConfigDict(extra="forbid")

    def bound_columns(self) -> set[str]:
        """Columns this render binds to (for grounding against the data shape)."""
        cols: set[str] = set()
        settings = _NON_COLUMN_ROLES.get(self.kind or "", frozenset())
        for role, value in self.roles.items():
            if role in settings:
                continue  # a setting (e.g. embedding's reduction), not a column
            if isinstance(value, list):
                cols |= {c for c in value if c}
            elif value:
                cols.add(value)
        cols |= {
            v
            for k, v in self.dict_kwargs.items()
            if k in _FIGURE_COLUMN_KWARGS and isinstance(v, str) and v
        }
        cols |= _config_columns(self.config)
        cols |= {line.column for line in self.reference_lines if line.column}
        if self.column:
            cols.add(self.column)
        if self.breakdown_col:
            cols.add(self.breakdown_col)
        if self.trend_col:
            cols.add(self.trend_col)
        cols |= {c for c in self.attrition_cols if c}
        if self.column_name:
            cols.add(self.column_name)
        cols |= {c for c in self.columns if c}
        if self.row_selection_column:
            cols.add(self.row_selection_column)
        return cols  # NB: `code`-mode figures are free-form → not grounded

    @model_validator(mode="after")
    def _check_component(self) -> Render:
        c = self.component
        # advanced_viz: kind + roles
        if c == "advanced_viz":
            if not self.kind:
                raise ValueError("renders_as advanced_viz requires a 'kind'")
            # Validated against the kind's FULL role vocabulary — required and
            # optional — because that is what the builder's binding panel
            # offers. Checking only the canonical (required) roles rejected
            # every optional binding a user could make there, e.g. a volcano's
            # `label` or an embedding's `color`.
            allowed = _allowed_roles(self.kind)
            unknown = set(self.roles) - allowed
            if unknown:
                raise ValueError(
                    f"renders_as {self.kind}: unknown role(s) {sorted(unknown)}; "
                    f"valid roles: {sorted(allowed)}"
                )
            list_roles = _LIST_ROLES.get(self.kind, frozenset())
            for role, value in self.roles.items():
                if isinstance(value, list) and role not in list_roles:
                    raise ValueError(
                        f"renders_as {self.kind}: role '{role}' binds one column, not a list"
                    )
                if role in list_roles and not isinstance(value, list):
                    raise ValueError(
                        f"renders_as {self.kind}: role '{role}' binds a list of columns"
                    )
            # A sankey without its steps cannot be built at all: `step_cols` is
            # required with >=2 entries on SankeyConfig, and nothing downstream
            # can infer them. Failing here says so while the entry is being
            # authored rather than when the dashboard renders nothing.
            if self.kind == "sankey":
                steps = self.roles.get("steps")
                if not isinstance(steps, list) or len(steps) < 2:
                    raise ValueError(
                        "renders_as sankey requires 'roles.steps' with at least 2 columns"
                    )
            _check_viz_config(self.kind, self.roles, self.config)
        else:
            if self.kind is not None:
                raise ValueError(f"'kind' is only valid for component=advanced_viz, not {c}")
            if self.roles:
                raise ValueError(f"'roles' is only valid for component=advanced_viz, not {c}")
            if self.config:
                raise ValueError(f"'config' is only valid for component=advanced_viz, not {c}")
        # figure: visu_type (UI) or code (code mode)
        if c == "figure":
            if not (self.visu_type or self.code):
                raise ValueError(
                    "renders_as figure requires 'visu_type' (UI) or 'code' (code mode)"
                )
        elif self.visu_type or self.dict_kwargs or self.code or self.reference_lines:
            raise ValueError(f"figure fields are only valid for component=figure, not {c}")
        if self.reference_lines and not self.visu_type:
            raise ValueError("'reference_lines' are drawn on UI-mode figures (visu_type) only")
        forbidden = _FORBIDDEN_FIGURE_KWARGS & set(self.dict_kwargs)
        if forbidden:
            raise ValueError(
                f"dict_kwargs {sorted(forbidden)}: a per-figure colour map is not allowed; "
                "colour by a column and let the dashboard's category_colors pick the hues"
            )
        # card: column + hero aggregation (+ optional secondary aggregations / filter)
        if c == "card":
            if not (self.column and self.aggregation):
                raise ValueError("renders_as card requires 'column' and 'aggregation'")
            if self.secondary_layout in _BREAKDOWN_CARD_LAYOUTS and not self.breakdown_col:
                raise ValueError(
                    f"secondary_layout={self.secondary_layout!r} requires 'breakdown_col'"
                )
            if self.secondary_layout in ("coverage", "gauge") and self.coverage_max is None:
                raise ValueError(
                    f"secondary_layout={self.secondary_layout!r} requires 'coverage_max'"
                )
            if self.secondary_layout == "threshold" and self.threshold_value is None:
                raise ValueError("secondary_layout='threshold' requires 'threshold_value'")
            if self.secondary_layout == "attrition" and not self.attrition_cols:
                raise ValueError(
                    "secondary_layout='attrition' requires 'attrition_cols' "
                    "(the stages after the card's own column)"
                )
            if self.secondary_layout == "trend" and not self.trend_col:
                raise ValueError(
                    "secondary_layout='trend' requires 'trend_col' (the ordered "
                    "column the sparkline is bucketed along)"
                )
        elif any(
            (
                self.column,
                self.aggregation,
                self.aggregations,
                self.secondary_layout,
                self.breakdown_col,
                self.top_n_count,
                self.coverage_max,
                self.threshold_value,
                self.threshold_direction,
                self.threshold_warn,
                self.attrition_cols,
                self.trend_col,
                self.filter_expr,
                self.caption,
                self.headline,
            )
        ):
            raise ValueError(f"card fields are only valid for component=card, not {c}")
        # interactive: the widget + the column it filters on
        if c == "interactive":
            if not (self.interactive_type and self.column_name):
                raise ValueError(
                    "renders_as interactive requires 'interactive_type' and 'column_name'"
                )
        elif self.interactive_type or self.column_name:
            raise ValueError(
                f"interactive fields are only valid for component=interactive, not {c}"
            )
        # table: every option is optional, so there is nothing to require —
        # only to keep off the other component types.
        if c != "table" and any(
            (
                self.columns,
                self.page_size,
                self.sortable is not None,
                self.filterable is not None,
                self.row_selection_enabled is not None,
                self.row_selection_column,
            )
        ):
            raise ValueError(f"table fields are only valid for component=table, not {c}")
        return self


class CatalogOutput(BaseModel):
    """One file a tool emits → one or more dashboard renders."""

    id: str
    # Short display label, e.g. "Amplicon coverage". This is what a picker or a
    # gallery lists; `description` is the full sentence behind it and is too long
    # to scan. Declared per output rather than derived from `id` so the wording is
    # the catalog's to choose. Optional for third-party catalogs; every bundled
    # output declares one (enforced by the catalog tests).
    name: str | None = None
    # The third-party tool the output actually comes from, when the catalog tool
    # is an aggregator rather than the producer: a MultiQC section is MultiQC's
    # file but FastQC's or Cutadapt's numbers, and a picker that only says
    # "Raw-read QC" hides which tool ran. Declared, not derived: MultiQC persists
    # anchors (`fastqc`, `samtools_bowtie2`), the report's own display names are
    # decorated by the pipeline ("PREPROCESS: FastQC (raw reads)"), and the
    # MultiQC package ships no anchor-to-name registry. Left unset when the tool
    # itself is the producer, or when the section is pipeline-generated content.
    origin_tool: str | None = None
    mode: str | None = None
    description: str = ""
    # The module revision this output last changed in (see "Versions" above):
    # its `find`, recipe, columns or renders. Optional; never above the module's
    # `version`, and never below one of its own renders'.
    version: str | None = Field(default=None, pattern=SEMVER_PATTERN)
    # Overrides the tool's `stage` for this output (see `Stage`).
    stage: Stage | None = None

    find: CatalogFind
    # Module-owned (preferred): `<module>/<name>.py`, co-located in this catalog
    # folder, e.g. `qiime2/ancombc.py`. Pipeline-keyed legacy form still resolves:
    # `nf-core/<pipeline>/<name>.py` (kept for pipeline-version-specific reshapes).
    recipe: str | None = None

    # Bindable columns. REQUIRED when there is no recipe (raw == bindable);
    # FORBIDDEN when a recipe is present (the recipe owns the output columns).
    columns: dict[str, str] = Field(default_factory=dict)

    renders_as: list[Render] = Field(default_factory=list)

    # A bundled sample of this output's bindable shape (path under
    # depictio/projects/, e.g. nf-core/ampliseq/2.16.0/alpha_diversity_multi_canonical.tsv).
    # Used by `catalog validate` (ground renders against real columns) and, later,
    # by `catalog preview` (render the component on real data).
    fixture: str | None = None

    # Per-output identity overrides (e.g. QIIME 2 subcommands = distinct modules).
    nf_core_url: str | None = None
    biotools_url: str | None = None
    edam_operations: list[str] = Field(default_factory=list)
    edam_formats: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    # Folder this output's YAML was loaded from (set by the loader). The
    # `fixture` is resolved relative to it → fixtures are co-located with the
    # module's YAML.
    _source_dir: Path | None = PrivateAttr(default=None)
    # The YAML file itself (set by the loader). `_source_dir` alone only gets a
    # caller as far as the tool folder, and the picker links to the module's own
    # definition.
    _source_file: Path | None = PrivateAttr(default=None)

    def fixture_file(self) -> Path | None:
        """Resolved path of the co-located fixture, if any."""
        if self.fixture and self._source_dir is not None:
            return self._source_dir / self.fixture
        return None

    @model_validator(mode="after")
    def _columns_ownership(self) -> CatalogOutput:
        # No duplication: a recipe owns the output columns.
        if self.recipe and self.columns:
            raise ValueError(
                f"output {self.id!r}: a recipe is set, so the recipe owns the output "
                f"columns — remove 'columns' (it must not be duplicated in the YAML)"
            )
        bad = {c: t for c, t in self.columns.items() if t not in ALLOWED_DTYPES}
        if bad:
            raise ValueError(
                f"output {self.id!r}: unknown dtype(s) {bad}; allowed: {sorted(ALLOWED_DTYPES)}"
            )
        if self.columns:
            # Renders must bind to declared columns (unless a fixture grounds them).
            for r in self.renders_as:
                missing = r.bound_columns() - set(self.columns)
                if missing and not self.fixture:
                    raise ValueError(
                        f"output {self.id!r} render {r.kind or r.component}: "
                        f"binds unknown column(s) {sorted(missing)}; "
                        f"declared columns: {sorted(self.columns)}"
                    )
        elif not self.recipe and not self.fixture:
            # No columns, no recipe, no fixture: bindings can't be grounded.
            # Allowed only for non-tabular / binding-less renders (multiqc, figure code…).
            for r in self.renders_as:
                if r.bound_columns():
                    raise ValueError(
                        f"output {self.id!r} render {r.kind or r.component}: binds "
                        f"{sorted(r.bound_columns())} but has no 'columns', 'recipe' or "
                        f"'fixture' to ground them"
                    )
        # recipe/fixture grounding (against the recipe's real output or the
        # fixture's real columns) is done by `depictio catalog validate`.
        return self

    @model_validator(mode="after")
    def _identity_urls(self) -> CatalogOutput:
        _check_identity_urls(
            self.nf_core_url,
            self.biotools_url,
            {"operation": self.edam_operations, "format": self.edam_formats},
        )
        return self


class CatalogTool(BaseModel):
    """A tool. Identity is stored as directly-clickable URLs."""

    id: str
    name: str
    # The module's own revision (semver), held to its content by
    # `depictio/catalog/catalog_versions.lock.json`. A template's lock entry records
    # the revision of each module it consumes, so bumping a module bumps them too.
    version: str = Field(default="1.0.0", pattern=SEMVER_PATTERN)
    # What changed in each revision, newest first (optional). When kept, its top
    # entry is `version`: a bump without its line fails, so the history a reader
    # sees in the gallery cannot fall behind the module.
    changelog: list[ChangelogEntry] = Field(default_factory=list)
    description: str = ""
    homepage: str | None = None
    # Where a non-nf-core source (Snakemake wrapper / Galaxy tool) was fetched
    # from — kept distinct from `homepage` (the tool's own upstream page). No
    # authority check: any source, so only well-formedness is asserted.
    source_url: str | None = None
    nf_core_url: str | None = None
    biotools_url: str | None = None
    edam_topics: list[str] = Field(default_factory=list)
    # Where the tool's outputs sit in a pipeline (see `Stage`); an output may
    # override it. Unset reads as "other".
    stage: Stage | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _changelog_order(self) -> CatalogTool:
        if not self.changelog:
            return self
        versions = [e.version for e in self.changelog]
        if versions[0] != self.version:
            raise ValueError(
                f"tool {self.id!r}: changelog starts at {versions[0]}, but the module "
                f"is at {self.version}; add a changelog entry for {self.version}"
            )
        keys = [semver_key(v) for v in versions]
        if any(a <= b for a, b in zip(keys, keys[1:], strict=False)):
            raise ValueError(
                f"tool {self.id!r}: changelog versions must be unique and newest "
                f"first, got {versions}"
            )
        return self

    @model_validator(mode="after")
    def _identity_urls(self) -> CatalogTool:
        _check_identity_urls(
            self.nf_core_url,
            self.biotools_url,
            {"topic": self.edam_topics},
            self.source_url,
        )
        return self


class CatalogEntry(CatalogTool):
    """A tool + all its outputs (one flat file, or a folder of files)."""

    schema_version: int = 1
    outputs: list[CatalogOutput] = Field(min_length=1)

    def stage_of(self, output: CatalogOutput) -> str:
        """The output's stage: its own, else the tool's, else ``other``."""
        return output.stage or self.stage or "other"

    @model_validator(mode="after")
    def _versions_within_module(self) -> CatalogEntry:
        # An output or render cannot have changed in a revision the module has
        # not reached, and an output changes whenever one of its renders does.
        module = semver_key(self.version)
        problems: list[str] = []
        for out in self.outputs:
            if out.version and semver_key(out.version) > module:
                problems.append(f"output {out.id!r} version {out.version}")
            for i, r in enumerate(out.renders_as):
                if not r.version:
                    continue
                label = f"render {r.id or i!r} of {out.id!r} version {r.version}"
                if semver_key(r.version) > module:
                    problems.append(label)
                elif out.version and semver_key(r.version) > semver_key(out.version):
                    raise ValueError(
                        f"tool {self.id!r}: {label} is newer than its output's "
                        f"{out.version}; a render change is a change of its output"
                    )
        if problems:
            raise ValueError(
                f"tool {self.id!r}: {', '.join(problems)} above the module's version {self.version}"
            )
        return self

    def output_version(self, output: CatalogOutput) -> str:
        """The revision an output is as of: its own, else the module's."""
        return output.version or self.version

    @model_validator(mode="after")
    def _unique_output_ids(self) -> CatalogEntry:
        ids = [o.id for o in self.outputs]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate output ids in tool {self.id!r}: {sorted(dupes)}")
        return self

    @model_validator(mode="after")
    def _unique_render_ids(self) -> CatalogEntry:
        # Render ids are the `use: <tool>/<id>` handles — unique within a tool.
        ids = [r.id for o in self.outputs for r in o.renders_as if r.id]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate render ids in tool {self.id!r}: {sorted(dupes)}")
        # A render id must not shadow an output's short id (would make
        # `use: <tool>/<x>` ambiguous between a render and an output).
        output_short = {o.id.removeprefix(f"{self.id}_") for o in self.outputs} | {
            o.id for o in self.outputs
        }
        clash = set(ids) & output_short
        if clash:
            raise ValueError(
                f"render id(s) {sorted(clash)} in tool {self.id!r} collide with an output id"
            )
        return self


# ---------------------------------------------------------------------------
# Loading: a flat file is one tool; a folder is one tool split across files
# ---------------------------------------------------------------------------

_MODULE_FILE = "module.yaml"


def _load_tool_dir(directory: Path) -> CatalogEntry:
    """Assemble an entry from a `<tool>/` folder: module.yaml + one file/output."""
    module_path = directory / _MODULE_FILE
    if not module_path.exists():
        raise ValueError(f"tool folder {directory} is missing {_MODULE_FILE}")
    tool = CatalogTool.model_validate(yaml.safe_load(module_path.read_text()))
    if tool.id != directory.name:
        # The folder name is the tool's address: the viewer builds the "browse this
        # tool on GitHub" link from the tool id alone, and the docs and the
        # conformance project both address a tool by that path. An id that
        # disagreed with its folder would send all three somewhere that does not
        # exist, so it is rejected here rather than half-working downstream.
        raise ValueError(
            f"tool folder {directory} declares id {tool.id!r}; "
            f"the id must match the folder name ({directory.name!r})"
        )
    outputs: list[CatalogOutput] = []
    for path in sorted(directory.glob("*.yaml")):
        if path.name == _MODULE_FILE:
            continue
        output = CatalogOutput.model_validate(yaml.safe_load(path.read_text()))
        output._source_file = path
        outputs.append(output)
    if not outputs:
        raise ValueError(f"tool folder {directory} has no output files")
    entry = CatalogEntry(**tool.model_dump(), outputs=outputs)
    for out in entry.outputs:
        out._source_dir = directory  # fixtures are co-located in the module folder
    return entry


def load_entries_from_dir(directory: Path) -> list[CatalogEntry]:
    """Load + validate every tool under ``directory`` (flat files + folders)."""
    entries: list[CatalogEntry] = []
    if not directory.exists():
        return entries
    for path in sorted(directory.iterdir()):
        if path.name.startswith((".", "_")):
            continue  # skip non-tool dirs/files like _index/
        try:
            if path.is_dir():
                entries.append(_load_tool_dir(path))
            elif path.suffix == ".yaml":
                raw = yaml.safe_load(path.read_text())
                if raw is not None:
                    entry = CatalogEntry.model_validate(raw)
                    for out in entry.outputs:
                        out._source_dir = path.parent  # fixtures next to the flat file
                        out._source_file = path  # a flat file holds the whole tool
                    entries.append(entry)
        except Exception as exc:
            raise ValueError(f"invalid catalog entry {path}: {exc}") from exc
    return entries


@lru_cache(maxsize=1)
def load_catalog_entries() -> tuple[CatalogEntry, ...]:
    return tuple(load_entries_from_dir(CATALOG_DIR))


# ---------------------------------------------------------------------------
# Existence checks against vendored indices (offline) — used by `validate`.
# nf-core modules + EDAM terms are validated for existence; bio.tools stays
# format-only (its registry is too large to vendor).
# ---------------------------------------------------------------------------

INDEX_DIR = CATALOG_DIR / "_index"


def load_index(name: str) -> set[str]:
    """Load a vendored index (`_index/<name>.txt`); `#`/blank lines ignored."""
    path = INDEX_DIR / f"{name}.txt"
    if not path.exists():
        return set()
    return {
        s for line in path.read_text().splitlines() if (s := line.strip()) and not s.startswith("#")
    }


def _nf_core_module(url: str | None) -> str | None:
    if url and "/modules/nf-core/" in url:
        module = url.split("/modules/nf-core/", 1)[1].rstrip("/")
        # Accept a URL that points at the module's meta.yml / main.nf (what the
        # nf-core docs link to) — the module path is the parent directory.
        for suffix in ("/meta.yml", "/main.nf"):
            if module.endswith(suffix):
                module = module[: -len(suffix)]
        return module
    return None


def check_existence(entries: tuple[CatalogEntry, ...] | list[CatalogEntry]) -> list[str]:
    """Check nf-core modules + EDAM terms exist in the vendored indices.

    Returns a list of problems (empty = all good). A missing/empty index is
    skipped (graceful), so seeding-then-refreshing stays non-breaking.
    """
    nf_index = load_index("nf_core_modules")
    edam_index = load_index("edam_terms")
    problems: list[str] = []

    def _check_nf(url: str | None, ctx: str) -> None:
        module = _nf_core_module(url)
        if module and nf_index and module not in nf_index:
            problems.append(f"{ctx}: nf-core module {module!r} not in vendored index")

    def _check_edam(urls: list[str], ctx: str) -> None:
        for url in urls:
            term = url.rstrip("/").rsplit("/", 1)[-1]
            if edam_index and term not in edam_index:
                problems.append(f"{ctx}: EDAM term {term!r} not in vendored index")

    for entry in entries:
        _check_nf(entry.nf_core_url, entry.id)
        _check_edam(entry.edam_topics, entry.id)
        for out in entry.outputs:
            _check_nf(out.nf_core_url, out.id)
            _check_edam(out.edam_operations + out.edam_formats, out.id)
    return problems


def check_identity(entries: tuple[CatalogEntry, ...] | list[CatalogEntry]) -> list[str]:
    """Flag tools whose catalog card would render without a description or homepage.

    Nothing derives a tool's identity from its nf-core ``meta.yml``: the payload
    reads ``description`` and ``homepage`` from ``module.yaml`` alone, so a module
    that leaves them out ships an empty card.
    """
    problems: list[str] = []
    for entry in entries:
        missing = [field for field in ("description", "homepage") if not getattr(entry, field)]
        if missing:
            problems.append(f"{entry.id}: module.yaml declares no {' or '.join(missing)}")
    return problems


# ---------------------------------------------------------------------------
# Recipe output columns — used by `catalog validate` to ground recipe outputs.
# Imports a recipe module, so it lives here but is only called from the CLI/CI.
# ---------------------------------------------------------------------------


def read_fixture_columns(path: Path) -> list[str]:
    """Read the column header of a fixture file (csv/tsv/parquet)."""
    return list(read_fixture_schema(path).keys())


def _dtype_name(dtype: object) -> str:
    """Base polars dtype name, without its parameters.

    ``str(pl.Datetime)`` renders as ``Datetime(time_unit='us', time_zone=None)``
    and ``List(Int64)`` likewise, but `ALLOWED_DTYPES` and the role dtype specs
    both speak base names. Left parametrised, a parquet fixture's datetime or
    list column could never match anything, so every binding to one was reported
    as a dtype error.
    """
    return str(dtype).split("(", 1)[0]


def read_fixture_schema(path: Path) -> dict[str, str]:
    """Read a fixture's ``{column: polars-dtype-name}`` schema (csv/tsv/parquet).

    For text fixtures dtypes are polars-inferred (up to 10k rows). Used by
    `validate` to ground each render's bindings against the real dtypes, not
    just the column names.
    """
    import polars as pl

    if path.suffix == ".parquet":
        return {name: _dtype_name(dtype) for name, dtype in pl.read_parquet_schema(path).items()}
    sep = "\t" if path.suffix == ".tsv" else ","
    schema = pl.read_csv(path, separator=sep, infer_schema_length=10_000).schema
    return {name: _dtype_name(dtype) for name, dtype in schema.items()}


def recipe_output_columns(recipe_ref: str) -> list[str]:
    """Return the output column names a recipe produces (its OUTPUT_SCHEMA)."""
    from depictio.recipes import load_recipe

    module = load_recipe(recipe_ref)
    return list(module.OUTPUT_SCHEMA.keys())


# Aggregations that are only meaningful on a numeric column. min/max/count/
# nunique/mode work on any dtype, so they're intentionally excluded.
_NUMERIC_AGGREGATIONS: frozenset[str] = frozenset(
    {
        "sum",
        "average",
        "median",
        "range",
        "variance",
        "std_dev",
        "percentile",
        "skewness",
        "kurtosis",
    }
)
_NUMERIC_DTYPES: frozenset[str] = frozenset(
    {"Int8", "Int16", "Int32", "Int64", "UInt8", "UInt16", "UInt32", "UInt64", "Float32", "Float64"}
)


def ground_render_dtypes(out_id: str, render: Render, col_dtypes: dict[str, str]) -> list[str]:
    """Check a render's bound columns have *compatible dtypes*, not merely that
    the names exist. advanced_viz roles are grounded against `role_dtype_specs`
    (the same table the web builder uses); numeric card aggregations require a
    numeric column. An empty `col_dtypes` (e.g. a recipe output with no dtype
    info) skips the checks. Returns a list of problem strings (empty = ok)."""
    from depictio.models.components.advanced_viz.schemas import role_dtype_specs

    problems: list[str] = []
    if not col_dtypes:
        return problems

    if render.component == "advanced_viz" and render.kind:
        specs = role_dtype_specs(render.kind)
        settings = _NON_COLUMN_ROLES.get(render.kind, frozenset())
        for role, value in render.roles.items():
            if role in settings:
                continue
            allowed = specs.get(role, {}).get("dtypes")
            if not isinstance(allowed, list):
                continue  # a list-typed role: no per-column dtype table to check
            for col in value if isinstance(value, list) else [value]:
                dt = col_dtypes.get(col)
                if dt and dt not in allowed:
                    problems.append(
                        f"{out_id} render {render.kind}: role {role!r} → column {col!r} is "
                        f"{dt}, but expects one of {allowed}"
                    )

    if render.component == "card" and render.column:
        dt = col_dtypes.get(render.column)
        for agg in (a for a in [render.aggregation, *render.aggregations] if a):
            if agg in _NUMERIC_AGGREGATIONS and dt and dt not in _NUMERIC_DTYPES:
                problems.append(
                    f"{out_id} render card: aggregation {agg!r} needs a numeric column, "
                    f"but {render.column!r} is {dt}"
                )
    return problems


# ---------------------------------------------------------------------------
# Recognition: match a scanned run directory against the catalog
# ---------------------------------------------------------------------------


class CatalogMatch(BaseModel):
    """One recognised file: which tool/output it is, where, and what it renders.

    `renders` lists the dashboard components the matched output maps to, as
    `"component"` or `"component:kind"` strings — the building blocks a guided
    dashboard would assemble for this module.
    """

    tool_id: str
    output_id: str
    path: str
    mode: str | None = None
    renders: list[str] = Field(default_factory=list)


def read_software_versions(run_dir: str | Path) -> set[str]:
    """Collect the tool names from a run's nf-core ``software_versions.yml``.

    nf-core writes ``{PROCESS: {tool: version}}``; we return the set of tool
    names (lowercased) actually executed — the module-level provenance used to
    scope/confirm recognition. Empty set if no such file is found.
    """
    run_dir = Path(run_dir)
    tools: set[str] = set()
    for path in run_dir.rglob("software_versions.yml"):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except Exception:
            continue
        for versions in data.values():
            if isinstance(versions, dict):
                tools.update(str(tool).lower() for tool in versions)
    return tools


def match_run_dir(
    run_dir: str | Path,
    entries: tuple[CatalogEntry, ...] | None = None,
    confirm_with_versions: bool = False,
) -> list[CatalogMatch]:
    """Walk ``run_dir`` and return every module output the catalog recognises.

    The catalog analogue of MultiQC's file search, at **module granularity**
    (pipeline-agnostic). NOTE: exposed via `depictio catalog match`/`compose`
    and intended as the scan-time recogniser; not yet wired into live ingestion.

    With ``confirm_with_versions=True`` and a ``software_versions.yml`` present,
    matches are restricted to tools the run actually executed — a second signal
    on top of filename matching (no file present → no restriction, non-breaking).
    """
    run_dir = Path(run_dir)
    entries = entries if entries is not None else load_catalog_entries()
    executed = read_software_versions(run_dir) if confirm_with_versions else set()
    matches: list[CatalogMatch] = []
    for entry in entries:
        if executed and entry.id.lower() not in executed:
            continue  # tool not in the run's software_versions.yml
        for output in entry.outputs:
            f = output.find
            if f.path_glob:
                # Every glob is tried; a file two of them reach (an alt overlapping
                # the canonical glob) is reported once, in glob order.
                hits = (p for g in f.path_globs() for p in run_dir.glob(g) if p.is_file())
                candidates = list(dict.fromkeys(hits))
            elif f.filename:
                candidates = [p for p in run_dir.rglob(f.filename) if p.is_file()]
            else:
                candidates = []
            renders: list[str] = [
                f"{r.component}:{r.kind}" if r.kind else str(r.component) for r in output.renders_as
            ]
            for path in candidates:
                if f.filename and not fnmatch(path.name, f.filename):
                    continue
                matches.append(
                    CatalogMatch(
                        tool_id=entry.id,
                        output_id=output.id,
                        path=path.relative_to(run_dir).as_posix(),
                        mode=output.mode,
                        renders=renders,
                    )
                )
    return matches


def compose_run_dir(
    run_dir: str | Path,
    entries: tuple[CatalogEntry, ...] | None = None,
    confirm_with_versions: bool = False,
) -> dict[str, list[CatalogMatch]]:
    """Group recognised module outputs by tool — a guided-dashboard *proposal*.

    This is the pipeline-agnostic composition step: scan a run (an nf-core
    pipeline OR a custom workflow reusing nf-core modules), recognise the module
    outputs present, and group them so a starter dashboard can be assembled from
    each module's `renders`. A preview only — it does not yet build a dashboard.
    """
    by_tool: dict[str, list[CatalogMatch]] = {}
    for match in match_run_dir(run_dir, entries, confirm_with_versions=confirm_with_versions):
        by_tool.setdefault(match.tool_id, []).append(match)
    return by_tool


def catalog_source_for_use(ref: str) -> dict[str, str] | None:
    """Resolve a ``use: <tool>/<ref>`` handle into the provenance the chrome draws.

    ``use:`` and ``catalog_source`` say the same thing in two registers. ``use:``
    is what a YAML author writes, because it is also the binding that expands
    into ``viz_kind`` + ``config``; ``catalog_source`` is what the tile chrome
    and the metadata popover read to show a component came from the catalog.
    Nothing connected them, so every dashboard authored in ``use:`` claimed no
    catalog provenance at all and went unbadged, which is exactly backwards:
    those are the components whose origin is known most precisely.

    Resolution mirrors ``_expand_catalog_use``: render id first, then output id.
    Returns ``None`` rather than raising for anything it cannot resolve, because
    a dashboard that fails to badge is a cosmetic loss and must never be a
    reason an otherwise valid import fails.
    """
    if not isinstance(ref, str) or "/" not in ref:
        return None
    tool_id, short = ref.split("/", 1)

    entry = next((e for e in load_catalog_entries() if e.id == tool_id), None)
    if entry is None:
        return None

    output = next(
        (o for o in entry.outputs if any(r.id == short for r in (o.renders_as or []))),
        None,
    )
    if output is None:
        output = next((o for o in entry.outputs if o.id in (f"{tool_id}_{short}", short)), None)
    if output is None:
        return None

    source = {"toolId": entry.id, "toolName": entry.name, "outputId": output.id, "use": ref}
    if output.description:
        source["description"] = output.description
    return source
