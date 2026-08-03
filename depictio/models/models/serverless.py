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
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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
    axes: dict[str, str] = Field(
        default_factory=dict,
        description="Facet-cell disambiguation: 'xaxis'/'yaxis' -> plotly axis id",
    )

    model_config = ConfigDict(extra="forbid")


class TrendlineBinding(BaseModel):
    """A trendline trace refit client-side via closed-form 1-predictor OLS."""

    i: int = Field(ge=0, description="Trendline trace index in the scaffold")
    on: int = Field(ge=0, description="Index of the raw-data trace it is fit against")

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
    traces: list[TraceBinding]
    trendlines: list[TrendlineBinding] = Field(default_factory=list)
    sampled: bool = Field(
        default=False,
        description="True when the build sampled before filtering (FIGURE_MAX_POINTS) -> partial tier",
    )

    model_config = ConfigDict(extra="forbid")


class PrologueOp(BaseModel):
    """One op of a code-mode figure's data prologue IR (RFC §7).

    ``op`` is a closed allowlist: filter | unpivot | pivot | group_by | sort |
    rename. Arguments are op-specific; predicates are compiled server-side to
    JSON nodes so the runtime never parses Python.
    """

    op: str = Field(description="filter | unpivot | pivot | group_by | sort | rename")
    args: dict[str, Any] = Field(default_factory=dict, description="Op-specific arguments")

    model_config = ConfigDict(extra="forbid")


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


class BundleManifest(BaseModel):
    """The serverless bundle contract (RFC §3.1). manifest_version 1."""

    manifest_version: int = Field(default=MANIFEST_VERSION)
    mode: BundleMode
    producer: Producer
    built_at: str = Field(description="ISO 8601 build timestamp")
    depictio_version: str = Field(description="Depictio version that built the bundle")

    dashboard: DashboardSection
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
        default_factory=dict, description="component_id -> code-mode prologue IR (phase 6)"
    )
    links: LinksSection = Field(default_factory=LinksSection)
    allow_network_tiles: bool = Field(
        default=False,
        description="Permit MapLibre tile fetches (static-dir/remote); single-file freezes maps unless style is white-bg",
    )
    inline_blobs: dict[str, str] = Field(
        default_factory=dict,
        description="single-file only: 'dc_<id>' -> base64 Parquet bytes referenced by inline: URIs",
    )

    model_config = ConfigDict(extra="forbid")
