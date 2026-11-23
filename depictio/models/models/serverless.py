"""
Bundle manifest for serverless (backend-less) dashboard deployments.

This is the *contract* layer of the serverless RFC
(``docs/design/rfc-serverless-deployment.md`` §3.1): one schema describing a
dashboard's layout, its data references, its per-component liveness tier, and
its frozen payloads. Producers (export-from-instance, build-from-spec, API
endpoint) emit it; the static runtime consumes it. Neither side knows about
the other beyond this schema.

The TypeScript mirror lives at ``packages/depictio-static-core/src/manifest.ts``.
Both sides are pinned by the committed JSON-schema snapshot
``depictio/models/models/serverless.schema.json``
(see ``depictio/tests/unit/serverless/test_manifest_schema.py``).
"""

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from depictio.models.models.analysis_state import AnalysisGroup, ColorBy, SplitPanel

MANIFEST_VERSION = 1


class BundleMode(str, Enum):
    """Delivery mode — only ``data_refs[].uri`` semantics change between them."""

    SINGLE_FILE = "single-file"  # one self-contained .html, data inlined as base64
    STATIC_DIR = "static-dir"  # index.html + data/ + frozen/, plain fetch
    REMOTE = "remote"  # index.html only, absolute URLs + Range requests


class Producer(str, Enum):
    """Which producer built the bundle (RFC §3.3)."""

    EXPORT_FROM_INSTANCE = "A"
    BUILD_FROM_SPEC = "B"
    API_ENDPOINT = "C"


class ComponentTier(str, Enum):
    """Per-component liveness in the static runtime (RFC §3.2)."""

    LIVE = "live"  # filters re-query in the browser
    PARTIAL = "partial"  # live but degraded fidelity (e.g. build-time sampling)
    FROZEN = "frozen"  # precomputed default-filter payload + visible badge
    OMITTED = "omitted"  # producer could not compute a frozen payload (producer B)


class TierReason(str, Enum):
    """Why a component is not fully live. ``detail`` carries the human string."""

    MULTIQC = "multiqc"
    CELERY_COMPUTE = "celery_compute"
    CODE_MODE = "code_mode"
    BINDING_MISS = "binding_miss"
    TRENDLINE = "trendline"  # a trendline the runtime cannot refit
    MAX_POINTS = "max_points"
    LINK_TABLE_TOO_BIG = "link_table_too_big"
    MAP_TILES = "map_tiles"
    JBROWSE = "jbrowse"
    IMAGE = "image"
    WHOLE_FRAME_VIZ = "whole_frame_viz"
    FILTER_EXPR_WINDOW = "filter_expr_window"  # .over() window predicate
    UNSUPPORTED = "unsupported"


class ColumnSpec(BaseModel):
    """One physical column of a bundled Parquet file."""

    name: str = Field(description="Column name as stored in the Parquet file")
    dtype: str = Field(description="Polars dtype string at export time (e.g. 'Int64', 'Utf8')")

    model_config = ConfigDict(extra="forbid")


class DataRef(BaseModel):
    """One data collection's bundled table.

    Mirrors the shape of ``load_deltatable_lite``'s ``init_data`` entries
    (``deltatables_utils.py:1393``) — the proven "resolve a DC without an API
    round-trip" contract — extended with serverless-only fields.
    """

    uri: str = Field(
        description=(
            "Where the Parquet bytes live. 'inline:dc_<id>' (single-file, resolved "
            "against inline_blobs), a bundle-relative path like 'data/<id>.parquet' "
            "(static-dir), or an absolute URL (remote). All resolution goes through "
            "the runtime's single resolveUri() helper."
        )
    )
    rows: int = Field(ge=0, description="Row count at export time")
    size_bytes: int = Field(ge=0, description="Parquet file size in bytes")
    row_group_bytes: int | None = Field(
        default=None,
        description="Target row-group size used at export (tuned for Range requests in remote mode)",
    )
    columns: list[ColumnSpec] = Field(description="Physical schema after pruning + companions")
    companions: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Companion column name -> source. '__ts__<col>': epoch-microsecond "
            "datetime companion for <col>; '__fe__<sha8>': boolean column for the "
            "component-static filter_expr whose source text is the value; "
            "'__code__<col>': Int32 codebook codes for categorical column <col>."
        ),
    )
    codebooks: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description=(
            "Per categorical non-String column: JSON-serialized option value -> "
            "integer code stored in the '__code__<col>' companion. Keys are "
            "serialized with the same _json_safe path that produces MultiSelect "
            "options, so option values and codebook keys are byte-identical. A "
            "selected value absent from the codebook matches nothing (same as a "
            "failed cast server-side)."
        ),
    )
    aggregation_hash: str | None = Field(
        default=None,
        description=(
            "Staleness token: server-side _get_aggregation_hash for producer A, "
            "hash of the input Parquet bytes for producer B"
        ),
    )

    model_config = ConfigDict(extra="forbid")


class TierEntry(BaseModel):
    """Per-component liveness verdict, shown by ``--check`` and the runtime badge."""

    tier: ComponentTier
    reason: TierReason | None = Field(
        default=None, description="Machine-readable cause when tier != live"
    )
    detail: str | None = Field(
        default=None, description="Human string for the --check table and badge tooltip"
    )

    model_config = ConfigDict(extra="forbid")


class FrozenPayload(BaseModel):
    """A precomputed component payload, rendered when the component is frozen."""

    kind: str = Field(
        description="Component type the payload feeds (figure|table|card|multiqc|advanced_viz|map|image)"
    )
    payload: dict[str, Any] = Field(
        description="Exactly what the corresponding api.ts function would have returned"
    )
    filter_state: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Filter state the payload was computed at (default state = [])",
    )

    model_config = ConfigDict(extra="forbid")


class TraceBinding(BaseModel):
    """One trace's binding in the bind-and-refill scheme (RFC §4)."""

    i: int = Field(ge=0, description="Trace index in the scaffold figure")
    group: dict[str, Any] = Field(
        default_factory=dict,
        description="Equality predicates (grouping column -> value) selecting this trace's rows",
    )
    fields: dict[str, str] = Field(
        description="Trace field path (e.g. 'x', 'y', 'marker.size') -> source column"
    )
    customdata: list[str] = Field(
        default_factory=list,
        description=(
            "Source columns feeding the 2-D customdata array, in plotly's column "
            "order — customdata[k] is this list's k-th column, which is what the "
            "hovertemplate's %{customdata[k]} indices address"
        ),
    )
    axes: dict[str, str] = Field(
        default_factory=dict,
        description="Facet-cell disambiguation: 'xaxis'/'yaxis' -> plotly axis id",
    )

    model_config = ConfigDict(extra="forbid")


#: The px ``trendline`` kinds the runtime refits (``packages/depictio-static-core/src/trendline.ts``).
TrendlineKind = Literal["ols", "lowess", "rolling", "expanding", "ewm"]


class TrendlineBinding(BaseModel):
    """A px trendline trace refit client-side over its raw trace's rows.

    ``kind`` and ``options`` are px's ``trendline`` / ``trendline_options``; the
    binder only emits combinations the runtime ports exactly (anything else
    freezes the figure), so the runtime treats an unknown option as a contract
    violation.
    """

    i: int = Field(ge=0, description="Trendline trace index in the scaffold")
    on: int = Field(ge=0, description="Index of the raw-data trace it is fit against")
    kind: TrendlineKind = Field(default="ols", description="px trendline kind")
    options: dict[str, Any] = Field(
        default_factory=dict, description="px trendline_options, verbatim"
    )

    model_config = ConfigDict(extra="forbid")


class BindingTable(BaseModel):
    """Everything the runtime needs to refill a ui-mode figure (RFC §4)."""

    scaffold: dict[str, Any] = Field(
        description="Full figure JSON from the real create_figure_from_data, data arrays stripped"
    )
    group_cols: list[str] = Field(
        default_factory=list,
        description="px grouping columns in order [color, symbol, line_dash, line_group, pattern_shape, facet_row, facet_col]",
    )
    color_col: str | None = Field(
        default=None,
        description=(
            "The discrete column the figure is coloured by (px ``color``), None when it has "
            "none. Lets the runtime recolour the figure by selection groups: the traces of "
            "that colour are merged and re-cut by the group a row belongs to"
        ),
    )
    traces: list[TraceBinding]
    trendlines: list[TrendlineBinding] = Field(default_factory=list)
    sampled: bool = Field(
        default=False,
        description="True when the build sampled before filtering (FIGURE_MAX_POINTS) -> partial tier",
    )

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Code-mode prologue IR (RFC §7, phase 6)
#
# A code-mode figure's *data prologue* — everything the user's Python does to
# ``df`` before handing it to plotly-express — is compiled server-side (by
# ``depictio.serverless.prologue.transpile``) into this closed JSON IR, so the
# browser runtime can re-run the reshape on filtered data without parsing one
# byte of Python. The TypeScript interpreter lives in
# ``packages/depictio-static-core/src/prologue.ts`` and is pinned against the
# same shapes by ``fixtures/prologue-fixture.json`` /
# ``fixtures/prologue-expected.json`` (generated by
# ``packages/depictio-static-core/scripts/generate_prologue_fixture.py``, which
# executes the IR with Polars — Polars *is* the semantics).
#
# The wire shapes are deliberately terse (bundle bytes) and are pinned by the
# committed schema snapshot:
#
#   {"op": "filter",   "pred": <Pred>}
#   {"op": "unpivot",  "on": [...], "index": [...], "variable": "...", "value": "..."}
#   {"op": "group_by", "by": [...], "agg": [{"col": ..., "fn": ..., "alias": ...}]}
#                      ``col`` is null exactly for ``fn: "len"`` written bare
#                      (``pl.len()`` / ``pl.count()``), which needs no source
#                      column; every other fn carries one.
#   {"op": "sort",     "by": [...], "desc": [true, ...]}
#   {"op": "rename",   "map": {"old": "new"}}
#
# Pinned execution semantics (Polars is the authority):
#   * filter    — a null comparison is *not* a match (Polars default).
#   * group_by  — ``maintain_order=True``: groups in first-appearance order; a
#                 null key forms its own group.
#   * unpivot   — ``DataFrame.unpivot``: one block per ``on`` column in ``on``
#                 order, original row order inside each block.
#   * sort      — ``DataFrame.sort(by, descending=desc)`` with Polars defaults,
#                 including its null placement.
#   * agg traps — std/var use ddof=1 (a single value aggregates to null),
#                 ``count`` is the NON-NULL count of ``col`` while ``len`` is the
#                 GROUP SIZE (mask-independent, nulls included), ``nunique``
#                 COUNTS null, ``median`` interpolates linearly, first/last are
#                 positional.
# --------------------------------------------------------------------------

PredScalar = str | bool | int | float
"""A JSON scalar usable on the right-hand side of a predicate."""


class CmpOperator(str, Enum):
    """Comparison operators expressible in a prologue predicate."""

    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    EQ = "=="
    NE = "!="


class AggFn(str, Enum):
    """Closed allowlist of ``group_by().agg()`` reducers."""

    SUM = "sum"
    MEAN = "mean"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"
    COUNT = "count"  # non-null count of ``col``
    LEN = "len"  # group size: every row, nulls included; ``col`` is not read
    NUNIQUE = "nunique"  # counts null as a distinct value
    STD = "std"  # ddof=1 -> null for a single-row group
    VAR = "var"  # ddof=1 -> null for a single-row group
    FIRST = "first"
    LAST = "last"


class ColRef(BaseModel):
    """Argument of the unary null predicates: ``{"col": "x"}``."""

    col: str = Field(description="Column the predicate tests")

    model_config = ConfigDict(extra="forbid")


class CmpArgs(BaseModel):
    """Argument of ``cmp``: column, operator, literal."""

    col: str
    op: CmpOperator
    value: PredScalar = Field(
        description="JSON scalar compared against the column (never null — use is_null)"
    )

    model_config = ConfigDict(extra="forbid")


class IsInArgs(BaseModel):
    """Argument of ``is_in``: column plus the literal membership set."""

    col: str
    values: list[PredScalar] = Field(description="Literal scalars the column must be one of")

    model_config = ConfigDict(extra="forbid")


class CmpPred(BaseModel):
    """``{"cmp": {"col": "q_val", "op": "<", "value": 0.05}}``"""

    cmp: CmpArgs

    model_config = ConfigDict(extra="forbid")


class IsNullPred(BaseModel):
    """``{"is_null": {"col": "x"}}``"""

    is_null: ColRef

    model_config = ConfigDict(extra="forbid")


class IsNotNullPred(BaseModel):
    """``{"is_not_null": {"col": "x"}}``"""

    is_not_null: ColRef

    model_config = ConfigDict(extra="forbid")


class IsInPred(BaseModel):
    """``{"is_in": {"col": "x", "values": [...]}}``"""

    is_in: IsInArgs

    model_config = ConfigDict(extra="forbid")


class AndPred(BaseModel):
    """``{"and": [<Pred>, ...]}`` — the field is aliased because ``and`` is a keyword."""

    and_: list["Pred"] = Field(alias="and", description="Conjuncts, evaluated left to right")

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


class OrPred(BaseModel):
    """``{"or": [<Pred>, ...]}``"""

    or_: list["Pred"] = Field(alias="or", description="Disjuncts, evaluated left to right")

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


class NotPred(BaseModel):
    """``{"not": <Pred>}``"""

    not_: "Pred" = Field(alias="not", description="Negated sub-predicate")

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


Pred = CmpPred | IsNullPred | IsNotNullPred | IsInPred | AndPred | OrPred | NotPred
"""One node of a prologue filter predicate tree.

Every variant carries exactly one (differently named) required field and forbids
extras, so the untagged union is unambiguous in both directions.
"""

AndPred.model_rebuild()
OrPred.model_rebuild()
NotPred.model_rebuild()


class FilterOp(BaseModel):
    """``df.filter(<pred>)`` — row selection. Nulls never match."""

    op: Literal["filter"] = "filter"
    pred: Pred

    model_config = ConfigDict(extra="forbid")


class UnpivotOp(BaseModel):
    """``df.unpivot(on=, index=, variable_name=, value_name=)`` (a.k.a. legacy ``melt``)."""

    op: Literal["unpivot"] = "unpivot"
    on: list[str] = Field(description="Columns melted into (variable, value) pairs, in block order")
    index: list[str] = Field(default_factory=list, description="Columns carried through unchanged")
    variable: str = Field(default="variable", description="Name of the emitted variable column")
    value: str = Field(default="value", description="Name of the emitted value column")

    model_config = ConfigDict(extra="forbid")


class AggSpec(BaseModel):
    """One reducer of a ``group_by().agg()``.

    ``col`` is null only for ``fn == "len"`` spelled bare (``pl.len()`` /
    the deprecated ``pl.count()``): the group size reads no column. The
    column-attached spelling ``pl.col(c).len()`` keeps ``col = c`` — Polars
    still returns the group size there, but names the output after ``c``, and
    a missing ``c`` still raises.
    """

    col: str | None = Field(
        default=None,
        description="Source column reduced; null only for a bare ``len`` (group size)",
    )
    fn: AggFn
    alias: str = Field(
        description=(
            "Output column name. Polars defaults it to ``col``, except for a bare "
            "``pl.len()`` -> 'len' and a bare ``pl.count()`` -> 'count'"
        )
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _col_required_unless_len(self) -> "AggSpec":
        if self.col is None and self.fn is not AggFn.LEN:
            raise ValueError(f"agg fn '{self.fn.value}' needs a source column")
        return self


class GroupByOp(BaseModel):
    """``df.group_by(by, maintain_order=True).agg(...)`` — first-appearance group order."""

    op: Literal["group_by"] = "group_by"
    by: list[str] = Field(description="Grouping key columns; a null key forms its own group")
    agg: list[AggSpec]

    model_config = ConfigDict(extra="forbid")


class SortOp(BaseModel):
    """``df.sort(by, descending=desc)`` with Polars' default null placement."""

    op: Literal["sort"] = "sort"
    by: list[str]
    desc: list[bool] = Field(description="Per-key direction; same length as ``by``")

    model_config = ConfigDict(extra="forbid")


class RenameOp(BaseModel):
    """``df.rename({"old": "new"})``."""

    op: Literal["rename"] = "rename"
    map: dict[str, str] = Field(description="Old column name -> new column name")

    model_config = ConfigDict(extra="forbid")


PrologueOp = Annotated[
    FilterOp | UnpivotOp | GroupByOp | SortOp | RenameOp,
    Field(discriminator="op"),
]
"""One op of a code-mode figure's data prologue IR (RFC §7), tagged by ``op``."""


class LinkTable(BaseModel):
    """Precomputed value-mapping for a DC link whose source DC is not bundled (tier B)."""

    values: dict[str, list[str]] = Field(
        default_factory=dict, description="Source value -> translated target values"
    )

    model_config = ConfigDict(extra="forbid")


class LinksSection(BaseModel):
    """DC link configs plus precomputed translation tables (RFC §8)."""

    configs: list[dict[str, Any]] = Field(
        default_factory=list, description="Link configs as stored in Mongo, verbatim"
    )
    tables: dict[str, LinkTable] = Field(
        default_factory=dict, description="link_id -> precomputed translation table"
    )

    model_config = ConfigDict(extra="forbid")


class RuntimeLimits(BaseModel):
    """Sampling ceilings the runtime enforces, pinned from the building instance.

    Mirrors ``PerformanceConfig`` (settings_models.py): the advanced_viz data
    path reduces the filtered frame to ``figure_max_points`` rows under the
    kind's policy, and flags aggregating kinds as degraded past
    ``advanced_viz_no_sample_max_rows``. Defaults match the server defaults so
    manifests built before this field existed keep the same behaviour.
    """

    figure_max_points: int = Field(
        default=10_000, description="Scan-level reduction cap (rows) for sampled render paths"
    )
    advanced_viz_no_sample_max_rows: int = Field(
        default=2_000_000,
        description="Ceiling past which 'none'-policy kinds are sampled anyway (degraded); 0 disables",
    )
    advanced_viz_tail_p_threshold: float = Field(
        default=0.05, description="Fallback tail threshold for raw p-value columns"
    )
    advanced_viz_tail_effect_threshold: float = Field(
        default=1.0, description="Fallback tail threshold for signed effect columns"
    )

    model_config = ConfigDict(extra="forbid")


class DashboardSection(BaseModel):
    """The dashboard document the runtime mounts."""

    id: str = Field(
        description=(
            "Dashboard id the runtime passes to App — real Mongo id (producer A/C) "
            "or synthetic sha1(workflow_tag + ':' + dc_tag)[:24]-style id (producer B). "
            "Must be non-empty: ComponentRenderer silently no-ops several component "
            "types without a dashboardId."
        )
    )
    title: str = Field(default="")
    doc: dict[str, Any] = Field(
        description="DashboardDataLite-shaped document: layout + stored_metadata components"
    )

    model_config = ConfigDict(extra="forbid")


class TabEntry(BaseModel):
    """One tab of a bundled tab family.

    Server-side a family is a main tab (``is_main_tab``) plus children carrying
    ``parent_dashboard_id``; the viewer's left rail switches between them by
    navigating to /dashboard/<id>. A bundle has no routing, so it carries every
    tab's document and switches in place.
    """

    id: str
    title: str = Field(default="")
    tab_order: int = Field(default=0, description="0 for the main tab, then child order")
    is_main_tab: bool = Field(default=False)
    icon: str | None = Field(
        default=None,
        description="Pill icon: the tab's own tab_icon, else the dashboard's (Iconify id or image path)",
    )
    icon_color: str | None = Field(default=None)
    # The rest of what the server's tab list (`/dashboards/list?include_child_tabs=true`)
    # hands the left rail. Without them a bundle's rail was flat (no `tab_group`
    # sections), named the main tab by the dashboard title instead of
    # `main_tab_name`, and lost image tab icons — the MultiQC logo — because a
    # child tab draws an image only from its OWN `tab_icon`.
    main_tab_name: str | None = Field(
        default=None, description="Name the rail shows for the main tab (dashboard title otherwise)"
    )
    tab_group: str | None = Field(
        default=None, description="Sidebar section of a child tab; null when ungrouped"
    )
    tab_icon: str | None = Field(
        default=None, description="The tab's own icon as authored (Iconify id or image path)"
    )
    tab_icon_color: str | None = Field(default=None, description="The tab's own icon colour")
    subtitle: str | None = Field(
        default=None, description="One line on what the tab shows (tab links describe it with this)"
    )
    doc: dict[str, Any] = Field(description="That tab's DashboardDataLite-shaped document")

    model_config = ConfigDict(extra="forbid")


class ExportProvenance(BaseModel):
    """Who built the bundle, from where, and against which data.

    Surfaced in the bundle's left rail: a bundle outlives the instance it came
    from, so a reader needs to know whose export it is and how old.
    """

    exported_by: str | None = Field(default=None, description="Email of the exporting user")
    exported_at: str | None = Field(
        default=None, description="ISO 8601; mirrors built_at, kept here for display"
    )
    source: str | None = Field(
        default=None, description="Instance the export ran against (host or deployment name)"
    )
    project_name: str | None = Field(default=None)
    dashboard_url: str | None = Field(
        default=None, description="Absolute URL of the live dashboard, when the builder knows it"
    )

    model_config = ConfigDict(extra="forbid")


class ProjectTemplateSummary(BaseModel):
    """The template a project was built from — its id and revision, nothing more.

    ``TemplateOrigin`` also carries ``data_root``, ``variables`` and a
    ``config_snapshot``: server paths and storage layout, which a file shared
    outside the instance must not leak.
    """

    template_id: str = Field(description="e.g. 'nf-core/ampliseq/2.14.0'")
    template_version: str | None = Field(default=None, description="Template schema revision")
    applied_at: str | None = Field(default=None, description="When the template was applied")

    model_config = ConfigDict(extra="forbid")


class ProjectWorkflowSummary(BaseModel):
    """One workflow of the project, as a reader names it."""

    id: str
    name: str
    tag: str | None = Field(default=None, description="workflow_tag (engine/name)")
    engine: str | None = Field(default=None, description="nextflow, snakemake, galaxy, ...")
    engine_version: str | None = None
    version: str | None = Field(default=None, description="The pipeline's own version")
    repository_url: str | None = Field(
        default=None, description="Public http(s) repository URL; anything else is dropped"
    )
    catalog: str | None = Field(default=None, description="Catalog name (nf-core, WorkflowHub)")

    model_config = ConfigDict(extra="forbid")


class ProjectColumnSummary(BaseModel):
    """One column of a collection as its last ingestion recorded it.

    The schema the live project page lists (name, dtype, description, distinct
    values), so a bundle shows it for every collection of the project, the
    ones the export left out included. Statistics other than the distinct
    count (min, max, samples of values) stay on the server.
    """

    name: str
    type: str | None = Field(default=None, description="Column dtype as recorded at ingestion")
    description: str | None = None
    distinct: int | None = Field(default=None, description="Distinct values at ingestion")

    model_config = ConfigDict(extra="forbid")


class ProjectDataCollectionSummary(BaseModel):
    """One data collection of the project. Size comes from ``data_refs`` when the
    bundle carries the table; a collection the export left out is still listed,
    so a reader can see what the live project holds.

    The ingestion facts (rows, columns, size, time, version, format) are what
    the live data collection viewer shows; none of them names a location, a
    user or a run folder.
    """

    id: str
    tag: str
    type: str = Field(default="table", description="dc type (table, multiqc, image, ...)")
    metatype: str | None = Field(default=None, description="Free-form label, display only")
    workflow_id: str | None = Field(default=None, description="Owning workflow, null when direct")
    description: str | None = None
    rows: int | None = Field(default=None, description="Rows at the last ingestion")
    size_bytes: int | None = Field(default=None, description="Stored size at the last ingestion")
    updated_at: str | None = Field(default=None, description="Time of the last ingestion")
    version: int | None = Field(default=None, description="Delta commit of the last ingestion")
    format: str | None = Field(default=None, description="Source file format (csv, parquet, ...)")
    columns: list[ProjectColumnSummary] = Field(
        default_factory=list, description="Schema at the last ingestion"
    )

    model_config = ConfigDict(extra="forbid")


class ProjectLinkSummary(BaseModel):
    """A cross-collection link (``DCLink``) without its value mappings.

    Mappings and patterns are the resolver's working data, can be large, and
    the bundle already ships what it needs of them in ``links``; this is the
    reader's view of which collection filters which.
    """

    id: str
    source_dc_id: str
    source_dc_tag: str | None = None
    source_column: str
    target_dc_id: str
    target_dc_tag: str | None = None
    target_type: str = Field(default="table")
    resolver: str = Field(default="direct")
    target_field: str | None = None
    description: str | None = None
    enabled: bool = True

    model_config = ConfigDict(extra="forbid")


class ProjectJoinSummary(BaseModel):
    """A top-level join definition: which collections it combines, on what."""

    name: str | None = None
    left_dc: str
    right_dc: str
    on_columns: list[str] = Field(default_factory=list)
    how: str | None = None
    description: str | None = None

    model_config = ConfigDict(extra="forbid")


class RunParameter(BaseModel):
    """One recorded run parameter (``ProvenanceEntry``), as safe to share.

    Values that are absolute paths or object-store URIs keep their last part
    only (``…/samplesheet.tsv``), and keys that look like credentials have
    their value withheld: the parameters say how the data was produced, the
    server's directory layout and secrets are not part of that.
    """

    source: str = ""
    group: str = "Other"
    key: str
    value: str = ""
    highlight: bool = False

    model_config = ConfigDict(extra="forbid")


class ProjectSummary(BaseModel):
    """What a reader can know offline about the dashboard's project.

    Producer A reads it from the project document and keeps only display
    facts: no permissions, owners, emails, tokens, storage credentials or
    server paths. The bundle's project page renders it.
    """

    id: str
    name: str
    description: str | None = None
    project_type: str | None = Field(default=None, description="basic | advanced")
    registered_at: str | None = Field(default=None, description="Project registration time")
    external_url: str | None = Field(
        default=None,
        description="data_management_platform_project_url, kept only when it is http(s)",
    )
    project_url: str | None = Field(
        default=None, description="Absolute URL of the live project page, when the instance has one"
    )
    template: ProjectTemplateSummary | None = None
    workflows: list[ProjectWorkflowSummary] = Field(default_factory=list)
    data_collections: list[ProjectDataCollectionSummary] = Field(default_factory=list)
    links: list[ProjectLinkSummary] = Field(default_factory=list)
    joins: list[ProjectJoinSummary] = Field(default_factory=list)
    run_parameters: list[RunParameter] = Field(default_factory=list)
    run_parameter_files: list[str] = Field(
        default_factory=list, description="File names the parameters were read from (no paths)"
    )

    model_config = ConfigDict(extra="forbid")


class BundledObject(BaseModel):
    """One object-store file shipped inside the bundle (a structure, a PAE matrix).

    The runtime answers the renderer's ``GET /files/indexed/{dc_id}`` from
    :class:`ObjectCollection` and hands it a ``blob:`` URL over these bytes, so
    the renderer's own download path (gunzip by magic bytes, per-object cache)
    runs unchanged and nothing leaves the page.
    """

    sample: str = Field(description="Entity the file belongs to (the indexed_file sample)")
    name: str = Field(description="File name as stored (format sniffing reads its extension)")
    uri: str = Field(description="'inline:obj_<sha>' resolved against inline_blobs")
    size_bytes: int = Field(ge=0, description="Size of the original object in bytes")
    gzip: bool = Field(
        default=False, description="Bytes were gzip-compressed at export (the reader gunzips)"
    )

    model_config = ConfigDict(extra="forbid")


class ObjectCollection(BaseModel):
    """The shipped part of one ``indexed_file`` data collection."""

    format: str = Field(default="", description="indexed_file format (pdb, mmcif, pae, ...)")
    files: list[BundledObject] = Field(default_factory=list)
    total: int = Field(default=0, ge=0, description="Objects the collection held at export")
    cap_bytes: int = Field(
        default=0, ge=0, description="Per-bundle object budget in force at export (raw bytes)"
    )
    dropped: list[str] = Field(
        default_factory=list,
        description="Samples left out because they did not fit the cap (named in the tier detail)",
    )

    model_config = ConfigDict(extra="forbid")


class ResolvedStructure(BaseModel):
    """A structure-resolver answer frozen at export (molecule_3d ``resolve`` mode)."""

    uniprot: str | None = None
    gene: str | None = None
    sequence: str | None = None
    taxon: int = 9606
    uri: str = Field(description="'inline:obj_<sha>' of the PDB model")
    origin: str | None = Field(default=None, description="afdb | esmfold")
    accession: str | None = None
    model_sequence: str = Field(default="", description="One-letter sequence of the model")

    model_config = ConfigDict(extra="forbid")


class RuntimeAddon(BaseModel):
    """An optional runtime piece embedded only into bundles that need it.

    The base runtime (``combined-runtime.js``) stays inside its byte budget; a producer
    appends an add-on's script when a component needs it, and records it here so
    the runtime and the tier table can say what was embedded and why.
    """

    name: Literal["3dmol", "pyodide", "jbrowse"]
    version: str = Field(description="Exact version of the embedded add-on")
    packages: list[str] = Field(
        default_factory=list, description="Python packages loaded (pyodide only)"
    )
    bytes: int = Field(default=0, ge=0, description="Size the add-on adds to the HTML file")
    reason: str = Field(default="", description="Which components needed it")

    model_config = ConfigDict(extra="forbid")


class PythonComponent(BaseModel):
    """A tile the optional Python runtime (Pyodide) recomputes in the browser.

    The runtime runs the server's own function for ``job`` over the bundled
    table under the current filter mask and answers the tile's request with
    it; the frozen payload, when there is one, stays as the fallback (Python
    runtime not embedded, failed to boot, or the frame above ``max_rows``).
    """

    job: Literal["code_figure", "group_compare", "embedding"]
    dc_id: str = Field(description="The bundled table the job reads (all user columns)")
    spec: dict[str, Any] = Field(
        default_factory=dict,
        description="Job inputs fixed at export (code_figure: code + category colours)",
    )
    max_rows: int | None = Field(
        default=None,
        description="Filtered rows above which the runtime serves the frozen payload instead",
    )
    table_uri: str = Field(
        description=(
            "'inline:ipc_<dc_id>': the table as Arrow IPC (zstd), for Python — Pyodide's "
            "polars is built without its Parquet reader. Same rows and order as the Parquet "
            "data_ref, user columns only, so the browser's row mask applies as is"
        )
    )

    model_config = ConfigDict(extra="forbid")


class InitialGrouping(BaseModel):
    """The grouping half of an analysis state a bundle or report opens on.

    The shapes are the analysis state's own (``analysis_state.py``), so a
    producer copies them across and the runtime reads the viewer's types.
    ``split_panels`` is what the viewer derived from the display when the state
    was built; the runtime derives its own from ``groups`` and ``display_mode``.
    """

    groups: list[AnalysisGroup] = Field(default_factory=list)
    color_by: ColorBy = Field(default_factory=ColorBy)
    display_mode: Literal["color", "facet"] = "color"
    show_other: bool = True
    show_overall: bool = True
    split_panels: list[SplitPanel] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @property
    def active(self) -> bool:
        """True when the state holds anything the runtime must seed."""
        return bool(self.groups) or self.color_by.kind != "none"


class BundleManifest(BaseModel):
    """The serverless bundle contract (RFC §3.1). manifest_version 1."""

    manifest_version: int = Field(default=MANIFEST_VERSION)
    mode: BundleMode
    producer: Producer
    built_at: str = Field(description="ISO 8601 build timestamp")
    depictio_version: str = Field(description="Depictio version that built the bundle")

    dashboard: DashboardSection
    tabs: list[TabEntry] = Field(
        default_factory=list,
        description=(
            "Every tab of the bundled family, main tab first, each with its own "
            "document. Empty for a single-tab bundle, where `dashboard` is the "
            "whole story; when populated it includes the entry tab too, so "
            "`dashboard.doc` duplicates one entry. Component-keyed sections "
            "(tiers, frozen, bindings, prologues) span the whole family — "
            "component ids are uuids, so they never collide across tabs"
        ),
    )
    provenance: ExportProvenance = Field(default_factory=ExportProvenance)
    project: ProjectSummary | None = Field(
        default=None,
        description=(
            "The dashboard's project as the bundle's project page shows it (producer A); "
            "null when the producer has no project to describe"
        ),
    )
    data_refs: dict[str, DataRef] = Field(
        default_factory=dict, description="dc_id -> bundled table"
    )
    tiers: dict[str, TierEntry] = Field(
        default_factory=dict, description="component_id -> liveness verdict"
    )
    frozen: dict[str, FrozenPayload] = Field(
        default_factory=dict, description="component_id -> precomputed payload"
    )
    bindings: dict[str, BindingTable] = Field(
        default_factory=dict, description="component_id -> bind-and-refill table (phase 5)"
    )
    prologues: dict[str, list[PrologueOp]] = Field(
        default_factory=dict,
        description=(
            "component_id -> code-mode prologue IR (phase 6): the ops the runtime "
            "replays on the filtered frame before bind-and-refill. Absent for "
            "components whose code needs no reshape (they bind to the base table)"
        ),
    )
    links: LinksSection = Field(default_factory=LinksSection)
    limits: RuntimeLimits = Field(
        default_factory=RuntimeLimits,
        description="Sampling ceilings pinned from the building instance's PerformanceConfig",
    )
    allow_network_tiles: bool = Field(
        default=False,
        description=(
            "Not read: every bundle keeps a map's own basemap, loaded when the reader is "
            "online (depictio/serverless/maps.py); offline the runtime draws the markers "
            "on a blank background"
        ),
    )
    inline_blobs: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "single-file only: 'dc_<id>' -> base64 Parquet bytes, 'obj_<sha>' -> base64 "
            "object bytes, both referenced by inline: URIs"
        ),
    )
    objects: dict[str, ObjectCollection] = Field(
        default_factory=dict,
        description=(
            "indexed_file dc_id -> the objects shipped for it (structures, PAE matrices), "
            "read at export from the collection's storage under a stated cap"
        ),
    )
    resolved_structures: list[ResolvedStructure] = Field(
        default_factory=list,
        description="Structure-resolver answers frozen at export (molecule_3d resolve mode)",
    )
    addons: list[RuntimeAddon] = Field(
        default_factory=list,
        description="Optional runtime add-ons embedded into this bundle's HTML (3Dmol.js, Pyodide)",
    )
    python_components: dict[str, PythonComponent] = Field(
        default_factory=dict,
        description=(
            "component_id -> the Python job the Pyodide add-on runs for it (present only "
            "when the add-on is embedded)"
        ),
    )
    initial_grouping: InitialGrouping | None = Field(
        default=None,
        description=(
            "The selection groups, colour-by and split the runtime opens on (the exported "
            "analysis state's own). The viewer's group store is seeded from it, in memory: "
            "a reader can add, edit and delete groups, none of it saved. None opens with no "
            "group, colouring the figures as built"
        ),
    )
    initial_filters: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Interactive filters the runtime opens on, in the viewer's InteractiveFilter "
            "wire shape (index, value, column_name, interactive_component_type, metadata). "
            "A report (the Quarto export's host of the runtime) sets it to the exported "
            "analysis state and opens on exactly that (empty = no filter); a bundle leaves "
            "it empty and opens on the dashboard's own defaults"
        ),
    )

    model_config = ConfigDict(extra="forbid")
