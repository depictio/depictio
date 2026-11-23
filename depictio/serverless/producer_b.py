"""Producer B — build a static dashboard bundle from a spec + local Parquet.

RFC §3.3: the backend-less producer. Input is a ``DashboardDataLite`` YAML/JSON
spec plus a directory of Parquet files (layout
``{data_dir}/{workflow_tag}/{data_collection_tag}.parquet``, overridable via an
optional ``data.yaml`` tag→path map in the data dir); output is one
self-contained HTML file (phase 1: ``single-file`` mode only).

Pipeline per data collection: read Parquet → prune columns (RFC §6) →
materialise companion columns (RFC §5 / errata #1) → re-export snappy Parquet
with 250k row groups (engine-spike builder rule) → inline as base64.

ui-mode figures are first offered to the bind-and-refill builder
(``binding.py``, RFC §4): a component that binds ships a *binding table* — the
real ``create_figure_from_data`` figure with its data arrays stripped, plus
per-trace group predicates and field→column bindings — and goes ``live``, with
the runtime re-projecting the arrays at every filter state. A component that
cannot be bound with certainty falls back to a *frozen* payload from the same
real figure service (errata #10) with reason ``binding_miss``.

code-mode figures take the same road since phase 6 (RFC §7): their data
prologue is compiled to the JSON IR (``prologue.py``), replayed here with
Polars (``prologue_exec.py``) to rebuild the frame the code handed to
plotly-express, and the figure the code itself produced becomes the scaffold —
so a transpilable, bindable code figure ships ``prologues[cid]`` +
``bindings[cid]`` and goes ``live`` too. Code the transpiler refuses stays
frozen with reason ``code_mode``. Everything the producer cannot compute at all
is *omitted* with a reason, surfaced by ``--check`` (see ``preflight.py``).

advanced_viz components are live since phase 4 for the tabular data-path kinds:
pruning keeps the columns their ``config`` binds, and the in-browser engine
recomputes the ``/advanced_viz/data`` payload from the bundled Parquet at every
filter state. The Celery-computed kinds and ``phylogenetic`` (whose Newick tree
DC producer B cannot read) are omitted — producer B has no frozen path for
either.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from depictio.models.models.dashboards import DashboardDataLite, strip_auto_category_colors
from depictio.models.models.serverless import (
    BindingTable,
    BundleManifest,
    BundleMode,
    ColumnSpec,
    ComponentTier,
    DashboardSection,
    DataRef,
    FrozenPayload,
    LinksSection,
    Producer,
    PrologueOp,
    RuntimeLimits,
    TierReason,
)
from depictio.serverless.binding import (
    BindingMiss,
    build_binding_with_reason,
    frozen_miss_detail,
    miss_tier_reason,
)
from depictio.serverless.companions import build_companions, filter_expr_targets
from depictio.serverless.dist import (  # noqa: F401 - re-exported
    RUNTIME_PATH,
    TEMPLATE_PATH_ENV,
    dist_static_dir,
    is_legacy_template,
    runtime_bytes,
    runtime_css_path,
    runtime_path,
)
from depictio.serverless.maps import freeze_map_payload
from depictio.serverless.preflight import (
    LINK_TIER_A,
    LINK_TIER_INERT,
    LinkRow,
    TierRow,
    classify_spec,
    tiers_from_rows,
)
from depictio.serverless.prologue import transpile_with_reason
from depictio.serverless.prologue_exec import execute_ops, terminal_px_call
from depictio.serverless.pruning import (
    advanced_viz_companion_tags,
    component_as_dict,
    compute_column_sets,
    dc_key,
    intersect_with_schema,
    link_join_columns,
    spec_links,
)

# Prebuilt static runtime (`cd depictio/viewer && pnpm run build:static`);
# where it lives is `serverless.dist`'s concern. The token is only for a legacy
# `.html` template named by DEPICTIO_SERVERLESS_TEMPLATE_PATH.
BUNDLE_TOKEN = "__BUNDLE_MANIFEST__"


# The static runtime is the floor under every single-file bundle: measured at
# ~7.7 MB of HTML/JS/CSS before a single row of data (RFC §8.1, v1.5.0). Used
# only when the runtime itself cannot be read — see :func:`runtime_floor_bytes`.
RUNTIME_FLOOR_FALLBACK_BYTES = int(7.7 * 1024 * 1024)


def runtime_floor_bytes() -> int:
    """What a bundle costs before any data: the built static runtime's size.

    Measured off the runtime this process would actually compose a bundle from
    (script + stylesheet), so the number tracks the runtime instead of lagging
    it. The fallback is only for when there is no runtime to measure — a
    preflight on a box with no Node build, or a container that mounts the
    runtime elsewhere without setting
    ``DEPICTIO_SERVERLESS_TEMPLATE_PATH``. It drifts whenever the runtime's own
    bundle does (new renderers, newly vendored libraries, a change to the CI
    byte budget of 3.20 MB gzip), which is exactly why it is the fallback and
    not the primary source.
    """
    try:
        return runtime_bytes()
    except OSError:
        return RUNTIME_FLOOR_FALLBACK_BYTES


# Engine-spike builder rule (docs/design/serverless-engine-spike.md §4): the
# runtime's bare hyparquet path decodes snappy; 250k-row groups match the
# measured kernel inputs and keep remote-mode Range requests reasonable.
PARQUET_COMPRESSION = "snappy"
PARQUET_ROW_GROUP_SIZE = 250_000

# Interactive component types whose filtered column is categorical (codebook
# companions) vs date-typed (__ts__ companions). RFC §5 / errata #1.
CATEGORICAL_INTERACTIVE_TYPES = frozenset({"Select", "MultiSelect", "SegmentedControl"})
DATE_INTERACTIVE_TYPES = frozenset({"DateRangePicker", "Timeline"})


class ProducerBError(Exception):
    """Raised when a spec + data dir cannot be turned into a bundle."""


# ---------------------------------------------------------------------------
# Inputs: spec + data resolution
# ---------------------------------------------------------------------------


def load_spec(path: str | Path) -> DashboardDataLite:
    """Parse a YAML or JSON spec file into a validated ``DashboardDataLite``."""
    spec_path = Path(path)
    if not spec_path.exists():
        raise ProducerBError(f"spec file not found: {spec_path}")
    if spec_path.suffix.lower() == ".json":
        try:
            data = json.loads(spec_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProducerBError(f"invalid JSON spec {spec_path}: {exc}") from exc
        return DashboardDataLite.model_validate(data)
    return DashboardDataLite.from_yaml_file(spec_path)


def synthetic_dc_id(workflow_tag: str, dc_tag: str) -> str:
    """Stable synthetic dc_id for a tag pair (no Mongo behind producer B)."""
    return hashlib.sha1(f"{workflow_tag}:{dc_tag}".encode()).hexdigest()[:24]


def synthetic_wf_id(workflow_tag: str) -> str:
    """Stable synthetic wf_id for a workflow tag (no Mongo behind producer B).

    Same 24-hex shape as :func:`synthetic_dc_id`, hashed from the workflow tag
    alone so every component of one workflow carries the same id. It exists
    because the renderers read it: every advanced_viz renderer gates its data
    fetch on a truthy ``metadata.wf_id`` and otherwise draws "missing data
    binding". The value is inert offline — the runtime keys its bundled tables
    on ``dc_id`` — but it has to be *there*, and it has to be the workflow's.
    """
    return hashlib.sha1(f"workflow:{workflow_tag}".encode()).hexdigest()[:24]


def _load_data_map(data_dir: Path) -> dict[str, str]:
    """Optional ``data.yaml`` in the data dir: ``"{wf_tag}:{dc_tag}"`` (or bare
    ``dc_tag``) → Parquet path, relative to the data dir or absolute."""
    map_path = data_dir / "data.yaml"
    if not map_path.exists():
        return {}
    loaded = yaml.safe_load(map_path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ProducerBError(f"{map_path} must contain a mapping of tag -> parquet path")
    return {str(k): str(v) for k, v in loaded.items()}


def resolve_parquet_path(data_dir: Path, workflow_tag: str, dc_tag: str) -> Path:
    """Locate the Parquet file backing one DC.

    Resolution order: explicit ``data.yaml`` entry (``wf:dc`` key first, then
    bare ``dc``), then the conventional layout
    ``{data_dir}/{workflow_tag}/{dc_tag}.parquet``.
    """
    data_map = _load_data_map(data_dir)
    for map_key in (dc_key(workflow_tag, dc_tag), dc_tag):
        if map_key in data_map:
            mapped = Path(data_map[map_key])
            return mapped if mapped.is_absolute() else data_dir / mapped
    return data_dir / workflow_tag / f"{dc_tag}.parquet"


# ---------------------------------------------------------------------------
# Dashboard document (DashboardDataLite-shaped, no Mongo — never to_full())
# ---------------------------------------------------------------------------


def text_value_workflows(spec: DashboardDataLite) -> dict[str, str]:
    """``dc_tag -> workflow_tag`` for the collections text live values name: the
    first spec component reading that collection (a value names its ``dc`` by
    tag alone, as an import resolves it within the project)."""
    out: dict[str, str] = {}
    for raw in spec.components:
        comp = component_as_dict(raw)
        wf, dc = comp.get("workflow_tag"), comp.get("data_collection_tag")
        if wf and dc:
            out.setdefault(str(dc), str(wf))
    return out


def _component_meta(
    comp: dict[str, Any],
    index: str,
    dc_id: str | None,
    value_workflows: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One ``stored_metadata`` entry: the spec component + runtime identifiers."""
    wf_tag = comp.get("workflow_tag") or ""
    meta = {k: v for k, v in comp.items() if k not in ("layout", "tag")}
    if meta.get("component_type") == "text" and isinstance(meta.get("values"), dict):
        # Each live value names its collection by tag; the runtime reads the
        # (synthetic) dc_id / wf_id an import would have resolved it to.
        values: dict[str, Any] = {}
        for name, value in meta["values"].items():
            value = dict(value) if isinstance(value, dict) else value
            if isinstance(value, dict) and value.get("dc"):
                wf = (value_workflows or {}).get(str(value["dc"]))
                if wf:
                    value.setdefault("dc_id", synthetic_dc_id(wf, str(value["dc"])))
                    value.setdefault("wf_id", synthetic_wf_id(wf))
            values[name] = value
        meta["values"] = values
    meta["index"] = index
    meta["component_type"] = comp.get("component_type", "figure")
    meta["wf_id"] = synthetic_wf_id(wf_tag) if wf_tag else None
    meta["dc_id"] = dc_id
    if meta["component_type"] == "advanced_viz" and isinstance(meta.get("config"), dict):
        # ``<base>_dc_tag`` names a companion table of the same workflow; the
        # renderer reads ``<base>_dc_id`` / ``<base>_wf_id`` (the real-id pair
        # an import resolves the tag into), so write the synthetic pair.
        config = dict(meta["config"])
        for key, value in list(config.items()):
            if key.endswith("_dc_tag") and isinstance(value, str) and value and wf_tag:
                base = key[: -len("_dc_tag")]
                config.setdefault(f"{base}_dc_id", synthetic_dc_id(wf_tag, value))
                config.setdefault(f"{base}_wf_id", synthetic_wf_id(wf_tag))
        meta["config"] = config
    if meta["component_type"] == "figure":
        meta["dict_kwargs"] = comp.get("figure_params") or comp.get("dict_kwargs") or {}
        meta.pop("figure_params", None)
        meta["mode"] = comp.get("mode", "ui")
    return meta


def build_dashboard_doc(spec: DashboardDataLite) -> dict[str, Any]:
    """The dashboard document the static runtime mounts.

    Mirrors the *shape* of ``DashboardDataLite.to_full()`` (stored_metadata +
    split-panel layouts) without calling it: producer B needs stable component
    indexes (the spec ``tag``) and synthetic dc_ids, not fresh UUIDs and Mongo
    defaults.
    """
    stored_metadata: list[dict[str, Any]] = []
    value_workflows = text_value_workflows(spec)
    left_layout: list[dict[str, Any]] = []
    right_layout: list[dict[str, Any]] = []
    left_y = 0
    right_y = 0

    for i, raw in enumerate(spec.components):
        comp = component_as_dict(raw)
        ctype = comp.get("component_type", "figure")
        index = comp.get("tag") or comp.get("index") or f"component-{i}"
        wf_tag = comp.get("workflow_tag") or ""
        dc_tag = comp.get("data_collection_tag") or ""
        dc_id = synthetic_dc_id(wf_tag, dc_tag) if wf_tag and dc_tag else None
        stored_metadata.append(_component_meta(comp, index, dc_id, value_workflows))

        layout = comp.get("layout") if isinstance(comp.get("layout"), dict) else {}
        if ctype == "interactive":
            item = {
                "i": f"box-{index}",
                "x": layout.get("x", 0),
                "y": layout.get("y", left_y),
                "w": layout.get("w", 1),
                "h": layout.get("h", 3),
                "static": False,
            }
            left_y += item["h"]
            if comp.get("placement") == "top":
                continue  # TopPanel components need no grid entry
            left_layout.append(item)
        else:
            item = {
                "i": f"box-{index}",
                "x": layout.get("x", 0),
                "y": layout.get("y", right_y),
                "w": layout.get("w", 6),
                "h": layout.get("h", 4),
                "static": ctype == "card",
            }
            if ctype != "card":
                item["resizeHandles"] = ["se", "s", "e", "sw", "w"]
            right_y += item["h"]
            right_layout.append(item)

    return {
        "title": spec.title,
        "subtitle": spec.subtitle,
        "stored_metadata": stored_metadata,
        "stored_layout_data": [],
        "left_panel_layout_data": left_layout,
        "right_panel_layout_data": right_layout,
    }


# ---------------------------------------------------------------------------
# Cross-DC links (RFC §8, phase 7)
# ---------------------------------------------------------------------------

# Emitted when a MultiQC sample_mapping link declares no inline ``mappings``.
# Server-side that is the signal to auto-fetch them from the MultiQC report
# (``links_endpoints/routes.py:718``); producer B has no report to read, and
# the resolver's documented behaviour for an empty mapping table is
# pass-through-with-unmapped (``resolvers.py:181``) — so the link stays honest
# but expands nothing.
SAMPLE_MAPPING_NO_INLINE_NOTE = (
    "sample_mapping without inline 'mappings': the server auto-fetches them from "
    "the MultiQC report, which the producer cannot replicate — the bundled "
    "resolver passes values through unexpanded"
)


def synthetic_link_id(source_tag: str, source_column: str, target_tag: str) -> str:
    """Stable synthetic link id for a spec link (no Mongo behind producer B).

    Hashed from the link's natural triple (source DC tag, join column, target
    DC tag), so the same spec always yields the same id — which is what lets
    ``manifest.links.tables`` key on it and a rebuilt bundle stay comparable.
    """
    natural = f"link:{source_tag}:{source_column}->{target_tag}"
    return hashlib.sha1(natural.encode()).hexdigest()[:24]


def _dc_ids_by_tag(spec: DashboardDataLite) -> dict[str, list[str]]:
    """``dc_tag -> [synthetic dc_id, ...]`` over the spec's components.

    A spec's link block names DCs by tag alone (the project-YAML convention);
    the manifest — and the browser core, which resolves link paths by dc *id* —
    needs ids. The same tag under two workflows is legal, so every match is
    kept and the link is emitted once per resolved pair.
    """
    by_tag: dict[str, list[str]] = {}
    for raw in spec.components:
        comp = component_as_dict(raw)
        wf_tag = comp.get("workflow_tag") or ""
        dc_tag = comp.get("data_collection_tag") or ""
        if not wf_tag or not dc_tag:
            continue
        dc_id = synthetic_dc_id(wf_tag, dc_tag)
        ids = by_tag.setdefault(dc_tag, [])
        if dc_id not in ids:
            ids.append(dc_id)
    return by_tag


def build_link_configs(spec: DashboardDataLite) -> tuple[list[dict[str, Any]], list[LinkRow]]:
    """``(manifest.links.configs, check rows)`` for a spec's ``links:`` block.

    Tags are resolved to the same synthetic dc_ids the data refs are keyed by;
    a link naming a tag no component references is dropped (there is no DC in
    the bundle for it to reach) and reported as an inert row. Disabled links
    ARE emitted — the runtime's graph walk skips them itself, and keeping them
    makes the bundle a faithful copy of the spec.

    Every source DC of an emitted link is a component DC, hence bundled, hence
    tier A: the browser runs the source-DC translation query against the
    bundled Parquet exactly like the server would. Producer B therefore needs
    no precomputed tables at all — that is producer A's tier-B problem.
    """
    by_tag = _dc_ids_by_tag(spec)
    configs: list[dict[str, Any]] = []
    rows: list[LinkRow] = []

    for link in spec_links(spec):
        source_tag = str(link.get("source_dc_tag") or "")
        target_tag = str(link.get("target_dc_tag") or "")
        source_column = str(link.get("source_column") or "")
        link_config = dict(link.get("link_config") or {})
        resolver = str(link_config.get("resolver") or "direct")
        link_id = synthetic_link_id(source_tag, source_column, target_tag)
        enabled = bool(link.get("enabled", True))

        source_ids = by_tag.get(source_tag, [])
        target_ids = by_tag.get(target_tag, [])
        if not source_column or not source_ids or not target_ids:
            missing = [
                label
                for label, ok in (
                    (f"source_dc_tag '{source_tag}'", bool(source_ids)),
                    (f"target_dc_tag '{target_tag}'", bool(target_ids)),
                    ("source_column", bool(source_column)),
                )
                if not ok
            ]
            rows.append(
                LinkRow(
                    link_id=link_id,
                    source=source_tag or "?",
                    target=target_tag or "?",
                    resolver=resolver,
                    tier=LINK_TIER_INERT,
                    enabled=enabled,
                    note=f"unresolvable in this spec ({', '.join(missing)}); link dropped",
                )
            )
            continue

        note = None
        if resolver == "sample_mapping" and not link_config.get("mappings"):
            note = SAMPLE_MAPPING_NO_INLINE_NOTE

        for source_id in source_ids:
            for target_id in target_ids:
                config = {k: v for k, v in link.items() if k != "id"}
                config["id"] = link_id
                config["source_dc_id"] = source_id
                config["target_dc_id"] = target_id
                config["source_column"] = source_column
                config["target_type"] = link.get("target_type") or "table"
                config["link_config"] = dict(link_config)
                config["enabled"] = enabled
                configs.append(config)

        rows.append(
            LinkRow(
                link_id=link_id,
                source=source_tag,
                target=target_tag,
                resolver=resolver,
                tier=LINK_TIER_A,
                enabled=enabled,
                note=note,
            )
        )

    return configs, rows


# ---------------------------------------------------------------------------
# Frozen payloads
# ---------------------------------------------------------------------------


def _freeze_ui_figure(comp: dict[str, Any], df: pl.DataFrame) -> tuple[dict[str, Any], bool]:
    """Freeze a ui-mode figure with the real figure service on the unfiltered
    frame (errata #10). Returns ``(payload, was_sampled)``."""
    from depictio.api.v1.services.figure.figure_builder import create_figure_from_data

    visu_type = comp.get("visu_type") or "scatter"
    dict_kwargs = comp.get("figure_params") or comp.get("dict_kwargs") or {}
    stats: dict[str, Any] = {}
    fig = create_figure_from_data(
        df,
        visu_type,
        dict_kwargs,
        theme="light",
        max_points=comp.get("max_points"),
        render_stats=stats,
    )
    from depictio.serverless.inject import json_safe

    payload = {
        # ``to_plotly_json`` leaves object-dtype (text) arrays as numpy arrays —
        # a categorical histogram's x — which the manifest cannot serialise.
        "figure": json_safe(fig.to_plotly_json()),
        "metadata": {
            "visu_type": visu_type,
            "filter_applied": False,
            "displayed_data_count": stats.get("displayed", df.height),
            "total_data_count": df.height,
            "was_sampled": bool(stats.get("sampled", False)),
        },
    }
    return payload, bool(stats.get("sampled", False))


def _spec_render_kwargs(spec: DashboardDataLite, comp: dict[str, Any]) -> dict[str, Any]:
    """A ui-mode figure's kwargs with the spec's brand and category colours
    merged in, the way ``render_figure_endpoint`` merges the dashboard's (and
    producer A's ``render_kwargs``): a figure colouring by a column the spec
    pins draws those colours, the component's own map winning value by value.
    """
    from depictio.api.v1.services.figure.figure_builder import (
        merge_category_colors,
        merge_dashboard_brand_theme,
    )

    kwargs = comp.get("figure_params") or comp.get("dict_kwargs") or {}
    brand = getattr(spec, "brand_theme", None)
    if brand is not None:
        kwargs = merge_dashboard_brand_theme(brand, kwargs)
    colors = strip_auto_category_colors(getattr(spec, "category_colors", None) or {})
    return merge_category_colors(colors, kwargs)


def _run_code_figure(comp: dict[str, Any], df: pl.DataFrame) -> Any:
    """Run a code-mode figure's Python and return the Plotly ``fig`` OBJECT.

    Producer B runs on the spec author's own machine against their own code, so
    a plain ``exec`` is the policy here (RestrictedPython sandboxing is producer
    A's concern). Raises ``ProducerBError`` when the code does not yield a
    Plotly ``fig`` — the caller downgrades the component to ``omitted``.

    The object (not its JSON) is what the caller needs: a transpilable figure
    hands it to the binding builder as the authoritative scaffold, and freezing
    is then just ``_code_figure_payload`` on the same object.
    """
    import numpy as np
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go

    code = comp.get("code_content") or ""
    if not code.strip():
        raise ProducerBError("code-mode figure has no code_content")
    ns: dict[str, Any] = {
        "df": df,
        "px": px,
        "go": go,
        "pd": pd,
        "pl": pl,
        "np": np,
        # The names every server code figure runs with (groups.code_group_globals),
        # at the ungrouped default state the bundle is built at.
        "depictio_group_kwargs": {},
        "depictio_group_by": [],
        "depictio_category_colors": dict(comp.get("__category_colors__") or {}),
    }
    try:
        exec(code, ns)  # noqa: S102 — trusted, author-supplied spec code on the author's machine
    except Exception as exc:
        raise ProducerBError(f"figure code failed: {exc}") from exc
    fig = ns.get("fig")
    if fig is None or not hasattr(fig, "to_plotly_json"):
        raise ProducerBError("figure code did not define a Plotly 'fig'")
    if "template=" not in code:
        from depictio.api.v1.services.figure.mantine_templates import ensure_mantine_templates

        ensure_mantine_templates()
        fig.update_layout(template="mantine_light")
    return fig


def _code_figure_payload(fig: Any) -> dict[str, Any]:
    """The frozen payload shape for a code-mode figure.

    Through ``to_json`` like the server (``build_figure_preview``):
    ``to_plotly_json`` keeps numpy arrays in the traces (any px call over a
    frame), which the manifest cannot serialise.
    """
    return {
        "figure": json.loads(fig.to_json()),
        "metadata": {"visu_type": "code", "filter_applied": False},
    }


def _freeze_code_figure(comp: dict[str, Any], df: pl.DataFrame) -> dict[str, Any]:
    """Run a code-mode figure and freeze it at the default filter state."""
    return _code_figure_payload(_run_code_figure(comp, df))


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


@dataclass
class BuildResult:
    """A validated manifest plus the tier table that produced it."""

    manifest: BundleManifest
    tier_rows: list[TierRow]
    link_rows: list[LinkRow] = field(default_factory=list)


def _companion_targets(
    components: list[dict[str, Any]], df: pl.DataFrame
) -> tuple[list[str], list[str]]:
    """Categorical / datetime companion columns for one DC's pruned frame."""
    categorical: list[str] = []
    datetime_cols: list[str] = []
    for comp in components:
        if comp.get("component_type") != "interactive":
            continue
        column = comp.get("column_name")
        if not column or column not in df.columns:
            continue
        itype = comp.get("interactive_component_type") or ""
        if itype in CATEGORICAL_INTERACTIVE_TYPES and column not in categorical:
            categorical.append(column)
        elif (
            itype in DATE_INTERACTIVE_TYPES or comp.get("column_type") == "datetime"
        ) and column not in datetime_cols:
            datetime_cols.append(column)
    return categorical, datetime_cols


def _runtime_limits() -> RuntimeLimits:
    """The building instance's sampling ceilings, pinned into the manifest.

    The static runtime has no settings of its own: the advanced_viz data path
    it serves in the browser must reduce frames with the SAME ceilings the
    server would have used, or a live component would disagree with the
    instance it was cut from. Imported lazily (and defensively): the model's
    defaults mirror ``PerformanceConfig``'s, so a build without loadable server
    settings still pins the documented behaviour.
    """
    try:
        from depictio.api.v1.configs.config import settings

        perf = settings.performance
        return RuntimeLimits(
            figure_max_points=perf.figure_max_points,
            advanced_viz_no_sample_max_rows=perf.advanced_viz_no_sample_max_rows,
            advanced_viz_tail_p_threshold=perf.advanced_viz_tail_p_threshold,
            advanced_viz_tail_effect_threshold=perf.advanced_viz_tail_effect_threshold,
        )
    except Exception:
        return RuntimeLimits()


def _depictio_version() -> str:
    try:
        from depictio.version import get_version

        return get_version()
    except Exception:
        try:
            from importlib.metadata import version

            return version("depictio")
        except Exception:
            return "unknown"


def _freeze_group_compare_b(
    comp: dict[str, Any], parquet_path: Path
) -> tuple[dict[str, Any] | None, str]:
    """The opening pair of a group_compare tile, computed from the local Parquet.

    Same request the live tile opens with (``computes``) and the same function
    the Celery task runs (``group_compare_from_frame``), over the whole table
    (the features are inferred from its schema). ``(None, reason)`` when it
    cannot run — scipy missing on a CLI-only install, fewer than two labels, a
    refusal from the function itself.
    """
    from depictio.serverless.computes import (
        frozen_detail,
        group_compare_opening_pair,
        group_compare_settings,
        selectors,
    )

    config = comp.get("config") or {}
    group_col = str(config.get("group_col") or "")
    try:
        from depictio.api.v1.services.group_compare import group_compare_from_frame

        df = pl.read_parquet(parquet_path)
        labels = sorted({str(v) for v in df.get_column(group_col).to_list() if v is not None})
        pair = group_compare_opening_pair(
            labels, config.get("default_group_a"), config.get("default_group_b")
        )
        if pair is None:
            return None, f"group_col '{group_col}' has fewer than two values"
        settings = group_compare_settings(config)
        request = {**settings, **selectors(group_col, pair)}
        result = group_compare_from_frame(
            df,
            index_col=str(settings["index_col"]),
            group_a=request["group_a"],
            group_b=request["group_b"],
            test=str(settings["test"]),
            log_transform=settings["log_transform"],
            max_features=settings["max_features"],
            min_observations=settings["min_observations"],
            fdr_threshold=settings["fdr_threshold"],
            log2fc_threshold=settings["log2fc_threshold"],
            top_n_labels=settings["top_n_labels"],
        )
    except Exception as exc:
        return None, f"advanced_viz 'group_compare' could not be computed at build time: {exc}"
    return {"result": {**result, "load_ms": 0}, "request": request}, frozen_detail(
        "group_compare", request
    )


def _settle_python_b(
    components: list[dict[str, Any]],
    tier_by_id: dict[str, TierRow],
    bindings: dict[str, Any],
    data_refs: dict[str, DataRef],
    candidates: dict[str, tuple[str, set[str]]],
    mode: str,
    spec: DashboardDataLite,
) -> tuple[dict[str, Any], Any]:
    """Producer B's half of ``producer_a.settle_python_jobs`` (same rules)."""
    from depictio.models.models.serverless import PythonComponent, RuntimeAddon
    from depictio.serverless.pyodide import plan
    from depictio.serverless.pyodide.assets import estimate_bytes, version

    jobs: dict[str, PythonComponent] = {}
    feats_by: dict[str, set[str]] = {}
    features: set[str] = set()
    colors = getattr(spec, "category_colors", None) or {}
    for comp in components:
        cid = comp["tag"]
        if cid not in candidates or cid in bindings:
            continue
        row = tier_by_id[cid]
        dc_id = synthetic_dc_id(
            comp.get("workflow_tag") or "", comp.get("data_collection_tag") or ""
        )
        if dc_id not in data_refs:
            continue
        if row.tier is ComponentTier.OMITTED and row.reason is not TierReason.CELERY_COMPUTE:
            continue
        job, feats = candidates[cid]
        spec_in: dict[str, Any] = {}
        if job == "code_figure":
            spec_in = {"code": comp.get("code_content") or "", "category_colors": colors}
        jobs[cid] = PythonComponent(
            job=job,  # type: ignore[arg-type]
            dc_id=dc_id,
            spec=spec_in,
            max_rows=plan.max_rows(job, feats),
            table_uri=f"inline:ipc_{dc_id}",
        )
        feats_by[cid] = feats
        features |= feats
    embedded = bool(jobs) if mode == "auto" else mode == "on"
    if not embedded:
        return {}, None
    if not features:
        features = {"code_figure"}
    missing = plan.unavailable_reason(features)
    if missing:
        if mode == "on":
            raise ProducerBError(f"the Python runtime could not be embedded: {missing}")
        return {}, None
    for cid, job in jobs.items():
        tier_by_id[cid].tier = ComponentTier.LIVE
        tier_by_id[cid].reason = None
        tier_by_id[cid].detail = plan.live_detail(job.job, feats_by[cid])
    addon = RuntimeAddon(
        name="pyodide",
        version=version(),
        packages=plan.addon_packages(features),
        bytes=estimate_bytes(features),
        reason="Python-live tiles: " + ", ".join(sorted(jobs)),
    )
    return dict(jobs), addon


def _collect_objects_b(
    components: list[dict[str, Any]],
    tier_by_id: dict[str, TierRow],
    data_path: Path,
    inline_blobs: dict[str, str],
) -> tuple[dict[str, Any], list[Any]]:
    """Ship the object files of live protein tiles from ``{data_dir}/{wf}/{dc_tag}/``.

    Producer B's convention for an ``indexed_file`` collection: a directory
    named after the tag, one file per entity (the file name without its
    extensions is the entity, ``demo_protein.pae.tsv`` → ``demo_protein``).
    Resolve-mode structure tiles need the resolver, which producer B never
    calls: their residue table stays live and the structure says it is absent.
    """
    from depictio.serverless.addons import addon_entry
    from depictio.serverless.objects import (
        THREE_DMOL_KINDS,
        ObjectBudget,
        build_collection,
        collection_detail,
        local_sources,
        object_dc_tags,
        object_kind,
        resolve_mode,
    )

    budget = ObjectBudget()
    objects: dict[str, Any] = {}
    three_dmol: list[str] = []
    for comp in components:
        row = tier_by_id[comp["tag"]]
        if comp.get("component_type") != "advanced_viz" or row.tier is ComponentTier.OMITTED:
            continue
        kind = object_kind(comp)
        tags = object_dc_tags(comp)
        if not tags and not resolve_mode(comp):
            continue
        wf_tag = comp.get("workflow_tag") or ""
        notes: list[str] = []
        shipped = False
        for _base, tag in tags:
            dc_id = synthetic_dc_id(wf_tag, tag)
            if dc_id not in objects:
                directory = data_path / wf_tag / tag
                objects[dc_id] = build_collection(
                    local_sources(directory), "", budget, inline_blobs
                )
                if not objects[dc_id].total:
                    notes.append(f"no files under {directory}")
            shipped = shipped or bool(objects[dc_id].files)
            note = collection_detail(objects[dc_id])
            if note:
                notes.append(note)
        if resolve_mode(comp):
            notes.append("producer B does not call the structure resolver")
        if kind in THREE_DMOL_KINDS and shipped:
            three_dmol.append(str(comp.get("title") or comp["tag"]))
        if not shipped:
            row.tier = ComponentTier.PARTIAL
            row.reason = TierReason.UNSUPPORTED
            row.detail = (
                f"advanced_viz '{kind}': the residue table is live, but no file it draws "
                f"from was shipped ({'; '.join(notes) or 'none found'})"
            )
        elif notes:
            row.detail = f"advanced_viz '{kind}': live; " + "; ".join(notes)
    addons = []
    if three_dmol:
        entry = addon_entry("3dmol", "3D structure tiles: " + ", ".join(three_dmol))
        if entry is not None:
            addons.append(entry)
    return objects, addons


def _freeze_component(
    comp: dict[str, Any],
    row: TierRow,
    spec: Any,
    data_path: Path,
    pruned_frames: dict[str, pl.DataFrame],
    frozen: dict[str, FrozenPayload],
    bindings: dict[str, BindingTable],
    prologues: dict[str, list[PrologueOp]],
    opened: dict[str, dict[str, Any]],
) -> None:
    """Settle one FROZEN-planned component, in place: its frozen payload, or a
    binding when the build can make it live after all, and its tier row.

    ``opened`` collects the request a frozen group comparison answers (the
    tile opens on that pair).
    """
    if row.tier is not ComponentTier.FROZEN:
        return
    if comp.get("component_type") == "map":
        parquet_path = resolve_parquet_path(
            data_path, comp.get("workflow_tag") or "", comp.get("data_collection_tag") or ""
        )
        if not parquet_path.exists():
            row.tier = ComponentTier.OMITTED
            row.reason = TierReason.UNSUPPORTED
            row.detail = f"no Parquet for the map's data collection: expected {parquet_path}"
            return
        colors = strip_auto_category_colors(getattr(spec, "category_colors", None) or {})
        frozen[row.component_id] = FrozenPayload(
            kind="map",
            payload=freeze_map_payload(
                comp, pl.read_parquet(parquet_path), colors if colors else None
            ),
        )
        return
    key = dc_key(comp.get("workflow_tag") or "", comp.get("data_collection_tag") or "")
    df = pruned_frames.get(key)
    if df is None:
        row.tier = ComponentTier.OMITTED
        row.reason = TierReason.UNSUPPORTED
        row.detail = "component references no resolvable data collection"
        return
    if comp.get("component_type") == "advanced_viz":
        payload, detail = _freeze_group_compare_b(
            comp,
            resolve_parquet_path(data_path, comp["workflow_tag"], comp["data_collection_tag"]),
        )
        row.detail = detail
        if payload is None:
            row.tier = ComponentTier.OMITTED
        else:
            frozen[row.component_id] = FrozenPayload(kind="compute", payload=payload)
            opened[row.component_id] = payload["request"]
        return
    # Tables never reach this loop: preflight classifies them LIVE (phase
    # 3) whenever their data collection resolves. Like a bound figure, a
    # live table ships NO frozen payload — the runtime recomputes every
    # page (filter → sort → slice) from the bundled Parquet, so a frozen
    # snapshot would only be a second copy of data the bundle already has.
    ctype = comp.get("component_type")
    if ctype == "figure" and comp.get("mode", "ui") == "code":
        # Code mode (RFC §7, phase 6). The author's Python always runs — it
        # is both the frozen fallback and, for a transpilable figure, the
        # authoritative scaffold. Then: compile the data prologue to IR,
        # read the terminal `px` call for the binder's kwargs, replay the IR
        # to rebuild the derived frame, and bind against it. A figure that
        # binds ships IR + binding and NO frozen payload — the runtime
        # re-derives it at every filter state from the bundled base table.
        from depictio.serverless.context_fold import fold_context

        colors = getattr(spec, "category_colors", None) or {}
        comp["__category_colors__"] = colors
        code = fold_context(comp.get("code_content") or "", colors, df.columns)
        ops, refusal = transpile_with_reason(code)
        call = terminal_px_call(code) if ops is not None else None
        if ops is not None and call is None:
            refusal = "figure call not analyzable"
        try:
            fig = _run_code_figure(comp, df)
        except ProducerBError as exc:
            row.tier = ComponentTier.OMITTED
            row.reason = TierReason.CODE_MODE
            row.detail = f"code-mode figure not locally computable: {exc}"
            return
        binding = None
        miss: BindingMiss | None = None
        if call is not None:
            assert ops is not None
            try:
                derived = execute_ops(ops, df)
                binding, miss = build_binding_with_reason(
                    {"visu_type": call[0], "dict_kwargs": call[1]}, derived, fig=fig
                )
            except Exception:
                # any executor/builder failure freezes below
                binding, miss = None, None
        if binding is not None:
            bindings[row.component_id] = binding
            if ops:
                # A code that needs no reshape binds to the base table, and
                # the contract omits empty op lists from the manifest.
                prologues[row.component_id] = ops
            row.tier = ComponentTier.LIVE
            row.reason = None
            row.detail = None
            return
        if call is None:
            row.reason = TierReason.CODE_MODE
            row.detail = f"code-mode figure not transpilable: {refusal}"
        else:
            # The binder names which bail-out fired; that sentence is the
            # badge tooltip, so it has to be the true one.
            row.reason = miss_tier_reason(miss)
            row.detail = frozen_miss_detail(miss, "prologue transpiled, but ")
        frozen[row.component_id] = FrozenPayload(kind="figure", payload=_code_figure_payload(fig))
    elif ctype == "figure":
        # Bind-and-refill first (RFC §4): a bound figure re-renders live in
        # the browser at every filter state — including the default, empty
        # one — so it ships NO frozen payload. The scaffold already carries
        # the authentic layout, and the runtime refills the arrays from the
        # bundled Parquet, so a frozen snapshot would only be a second copy
        # of data the bundle already has.
        # The kwargs the render endpoint hands the worker: the spec's brand
        # defaults, then its category colours as `color_discrete_map`.
        comp = {**comp, "dict_kwargs": _spec_render_kwargs(spec, comp)}
        comp.pop("figure_params", None)
        binding, miss = build_binding_with_reason(comp, df)
        if binding is not None:
            bindings[row.component_id] = binding
            if binding.sampled:
                row.tier = ComponentTier.PARTIAL
                row.reason = TierReason.MAX_POINTS
                row.detail = (
                    "the server samples above FIGURE_MAX_POINTS after filtering; "
                    "the bound figure refills every selected row instead — exact, "
                    "but heavier than the server's default view"
                )
            else:
                row.tier = ComponentTier.LIVE
                row.reason = None
                row.detail = None
            return
        payload, sampled = _freeze_ui_figure(comp, df)
        row.reason = miss_tier_reason(miss)
        row.detail = frozen_miss_detail(miss)
        if sampled:
            row.tier = ComponentTier.PARTIAL
            row.reason = TierReason.MAX_POINTS
            row.detail = (
                "build-time sampling before filtering (FIGURE_MAX_POINTS); "
                "the frozen figure shows a downsampled default view"
            )
        frozen[row.component_id] = FrozenPayload(kind="figure", payload=payload)


def build_manifest(
    spec: DashboardDataLite,
    data_dir: str | Path,
    mode: BundleMode = BundleMode.SINGLE_FILE,
    python_runtime: str = "off",
) -> BuildResult:
    """Assemble and validate the full ``BundleManifest`` (no HTML involved).

    ``python_runtime`` (auto / on / off) embeds the optional Pyodide runtime
    for the tiles it can make live (``serverless/pyodide/plan.py``).
    """
    if mode is not BundleMode.SINGLE_FILE:
        raise ProducerBError(f"phase 1 supports only single-file mode, got {mode.value!r}")
    data_path = Path(data_dir)
    if not data_path.is_dir():
        raise ProducerBError(f"data dir not found: {data_path}")

    tier_rows = classify_spec(spec)
    tier_by_id = {row.component_id: row for row in tier_rows}
    components = [component_as_dict(c) for c in spec.components]
    for i, comp in enumerate(components):
        comp.setdefault("tag", comp.get("index") or f"component-{i}")

    # Cross-DC links (RFC §8): resolved to synthetic dc_ids, and their join
    # columns folded into both endpoints' column sets by ``compute_column_sets``.
    link_configs, link_rows = build_link_configs(spec)
    join_columns = link_join_columns(spec)

    # DCs needed = referenced by at least one component that ships data.
    column_sets = compute_column_sets(spec)
    needed: dict[str, tuple[str, str]] = {}
    consumers: dict[str, list[dict[str, Any]]] = {}
    for comp in components:
        row = tier_by_id[comp["tag"]]
        if row.tier is ComponentTier.OMITTED:
            continue
        if comp.get("component_type") == "map":
            # A frozen map reads its whole table at build time and ships only the
            # figure; its collection is bundled only if a live component reads it.
            continue
        wf_tag = comp.get("workflow_tag") or ""
        dc_tag = comp.get("data_collection_tag") or ""
        if not wf_tag or not dc_tag:
            continue
        key = dc_key(wf_tag, dc_tag)
        needed.setdefault(key, (wf_tag, dc_tag))
        consumers.setdefault(key, []).append(comp)

    # The collections text live values read (``values: {name: {dc: ...}}``).
    value_workflows = text_value_workflows(spec)
    for comp in components:
        if comp.get("component_type") != "text":
            continue
        for value in (comp.get("values") or {}).values():
            tag = value.get("dc") if isinstance(value, dict) else None
            wf = value_workflows.get(str(tag)) if tag else None
            if wf:
                needed.setdefault(dc_key(wf, str(tag)), (wf, str(tag)))
                consumers.setdefault(dc_key(wf, str(tag)), []).append(comp)

    # Companion tables of the live advanced_viz components (``*_dc_tag``):
    # bundled when their Parquet exists — a missing one costs that lane, not
    # the build — with the over-collected columns, or whole when none match.
    companion_cols: dict[str, set[str]] = {}
    for comp in components:
        if tier_by_id[comp["tag"]].tier is ComponentTier.OMITTED:
            continue
        wf_tag = comp.get("workflow_tag") or ""
        for tag, cols in advanced_viz_companion_tags(comp).items():
            key = dc_key(wf_tag, tag)
            if not resolve_parquet_path(data_path, wf_tag, tag).exists():
                continue
            needed.setdefault(key, (wf_tag, tag))
            consumers.setdefault(key, [])
            companion_cols[key] = companion_cols.get(key, set()) | cols

    # Python-runtime candidates ship their whole table (the server code they
    # run reads any column); which of them the runtime serves is settled below.
    python_candidates: dict[str, tuple[str, set[str]]] = {}
    if python_runtime != "off":
        from depictio.serverless.pyodide.plan import candidate

        for comp in components:
            row = tier_by_id[comp["tag"]]
            wf_tag = comp.get("workflow_tag") or ""
            dc_tag = comp.get("data_collection_tag") or ""
            if not wf_tag or not dc_tag:
                continue
            # An omitted Celery kind (a computed embedding) is a candidate too:
            # producer B cannot freeze it, but the runtime can compute it.
            if row.tier is ComponentTier.OMITTED and row.reason is not TierReason.CELERY_COMPUTE:
                continue
            key = dc_key(wf_tag, dc_tag)
            plan = candidate({**comp, "dc_id": key})
            if plan is None:
                continue
            python_candidates[comp["tag"]] = plan
            needed.setdefault(key, (wf_tag, dc_tag))
            consumers.setdefault(key, [])
            column_sets[key] = None

    data_refs: dict[str, DataRef] = {}
    inline_blobs: dict[str, str] = {}
    pruned_frames: dict[str, pl.DataFrame] = {}

    for key, (wf_tag, dc_tag) in needed.items():
        parquet_path = resolve_parquet_path(data_path, wf_tag, dc_tag)
        if not parquet_path.exists():
            raise ProducerBError(
                f"no Parquet for data collection '{dc_tag}' (workflow '{wf_tag}'): "
                f"expected {parquet_path} — lay data out as "
                f"{{data_dir}}/{{workflow_tag}}/{{data_collection_tag}}.parquet or map it "
                f"explicitly in {data_path / 'data.yaml'}"
            )
        df = pl.read_parquet(parquet_path)

        if key in companion_cols and key not in column_sets:
            wanted = companion_cols[key] & set(df.columns)
            column_sets[key] = wanted or None
        elif key in companion_cols and column_sets.get(key) is not None:
            column_sets[key] = (column_sets[key] or set()) | (companion_cols[key] & set(df.columns))
        kept, missing = intersect_with_schema(column_sets.get(key), df.columns)
        # A link's join column absent from this DC's real schema is dropped, not
        # fatal — the same schema-guard the server applies in ``_project_scan``
        # (test_column_projection.py::TestCrossDcLinkProjection). Only columns a
        # *component* asked for are a hard error.
        missing -= join_columns.get(key, set())
        if missing:
            raise ProducerBError(
                f"data collection '{dc_tag}' ({parquet_path.name}) is missing column(s) "
                f"referenced by the spec: {sorted(missing)} — available: {df.columns}"
            )
        df = df.select(kept)
        pruned_frames[key] = df

        categorical_cols, datetime_cols = _companion_targets(consumers[key], df)
        # This DC's component filter_exprs (a card's row scoping) plus every
        # interactive scope, which travels with its filter (``__fe__``, RFC §5).
        result = build_companions(
            df,
            categorical_cols,
            datetime_cols,
            filter_expr_targets(
                [
                    *consumers[key],
                    *(c for c in components if c.get("component_type") == "interactive"),
                ]
            ),
        )

        buf = io.BytesIO()
        result.df.write_parquet(
            buf, compression=PARQUET_COMPRESSION, row_group_size=PARQUET_ROW_GROUP_SIZE
        )
        parquet_bytes = buf.getvalue()

        dc_id = synthetic_dc_id(wf_tag, dc_tag)
        blob_key = f"dc_{dc_id}"
        inline_blobs[blob_key] = base64.b64encode(parquet_bytes).decode("ascii")
        data_refs[dc_id] = DataRef(
            uri=f"inline:{blob_key}",
            rows=result.df.height,
            size_bytes=len(parquet_bytes),
            columns=[
                ColumnSpec(name=name, dtype=str(dtype)) for name, dtype in result.df.schema.items()
            ],
            companions=result.companions,
            codebooks=result.codebooks,
            aggregation_hash=hashlib.sha256(parquet_bytes).hexdigest(),
        )

    # Bindings and frozen payloads (+ data-dependent tier refinements).
    frozen: dict[str, FrozenPayload] = {}
    bindings: dict[str, BindingTable] = {}
    prologues: dict[str, list[PrologueOp]] = {}
    # Frozen group comparisons, by component: the tile opens on that pair.
    opened: dict[str, dict[str, Any]] = {}
    for comp in components:
        _freeze_component(
            comp,
            tier_by_id[comp["tag"]],
            spec,
            data_path,
            pruned_frames,
            frozen,
            bindings,
            prologues,
            opened,
        )

    objects, addons = _collect_objects_b(components, tier_by_id, data_path, inline_blobs)
    # Gene tables for the genome tiles (``gene_assets``): file:// cannot fetch
    # `./assets/genomes/...`, so the bundle carries the ones its tiles name.
    from depictio.serverless.gene_assets import gene_blobs

    genes, _ = gene_blobs(components, dist_static_dir())
    inline_blobs.update(genes)
    python_components, python_addon = _settle_python_b(
        components, tier_by_id, bindings, data_refs, python_candidates, python_runtime, spec
    )
    if python_addon is not None:
        from depictio.serverless.pyodide.plan import ipc_blob

        addons.append(python_addon)
        frames_by_id = {
            synthetic_dc_id(wf, dc): pruned_frames[key]
            for key, (wf, dc) in needed.items()
            if key in pruned_frames
        }
        for job in python_components.values():
            if f"ipc_{job.dc_id}" not in inline_blobs:
                inline_blobs[f"ipc_{job.dc_id}"] = ipc_blob(frames_by_id[job.dc_id])

    dashboard_doc = build_dashboard_doc(spec)
    if opened:
        from depictio.serverless.computes import open_on_frozen_request

        for meta in dashboard_doc.get("stored_metadata") or []:
            request = opened.get(str(meta.get("index")))
            if request is not None:
                meta["config"] = dict(meta.get("config") or {})
                open_on_frozen_request(meta["config"], request)

    dashboard_id = hashlib.sha1(f"dashboard:{spec.title}".encode()).hexdigest()[:24]
    manifest = BundleManifest(
        mode=mode,
        producer=Producer.BUILD_FROM_SPEC,
        built_at=datetime.now(timezone.utc).isoformat(),
        depictio_version=_depictio_version(),
        dashboard=DashboardSection(id=dashboard_id, title=spec.title, doc=dashboard_doc),
        data_refs=data_refs,
        tiers=tiers_from_rows(tier_rows),
        frozen=frozen,
        bindings=bindings,
        prologues=prologues,
        # No tables: every emitted link's source DC is a component DC, hence
        # bundled, hence resolvable in the browser (tier A).
        links=LinksSection(configs=link_configs),
        limits=_runtime_limits(),
        inline_blobs=inline_blobs,
        objects=objects,
        addons=addons,
        python_components=python_components,
    )
    # A link whose source DC did not end up bundled (its only components were
    # omitted) has no data to translate through and no precomputed table — the
    # runtime's walk finds no usable chain and the filter does not propagate.
    for row in link_rows:
        if row.tier != LINK_TIER_A:
            continue
        sources = {c["source_dc_id"] for c in link_configs if c["id"] == row.link_id}
        if not sources & set(data_refs):
            row.tier = LINK_TIER_INERT
            row.note = "source data collection not bundled; link inert in this bundle"
    return BuildResult(manifest=manifest, tier_rows=tier_rows, link_rows=link_rows)


def render_bundle_html(manifest: BundleManifest) -> str:
    """The self-contained page for a manifest, from the prebuilt static runtime.

    Composed from ``combined-runtime.js`` + ``.css`` (``serverless.bundle_html``).
    ``DEPICTIO_SERVERLESS_TEMPLATE_PATH`` may instead name a legacy ``.html``
    template, which the manifest is injected into by token.
    """
    from depictio.serverless.addons import addons_html, apply_addons
    from depictio.serverless.bundle_html import compose_bundle_html
    from depictio.serverless.inject import inject

    path = runtime_path()
    legacy = is_legacy_template(path)
    css_path = runtime_css_path(path)
    if not path.exists() or (not legacy and not css_path.exists()):
        missing = path if not path.exists() else css_path
        raise ProducerBError(
            f"static-runtime bundle not built: {missing} is missing — run "
            f"`cd depictio/viewer && pnpm run build:static`, or point "
            f"{TEMPLATE_PATH_ENV} at a prebuilt combined-runtime.js"
        )
    names = [a.name for a in manifest.addons]
    pyodide = next((a for a in manifest.addons if a.name == "pyodide"), None)
    packages = list(pyodide.packages) if pyodide else None
    payload = manifest.model_dump(mode="json")
    if legacy:
        html = apply_addons(path.read_text(), names, packages)
        return inject(html, BUNDLE_TOKEN, payload)
    return compose_bundle_html(
        payload,
        js=path.read_text(encoding="utf-8"),
        css=css_path.read_text(encoding="utf-8"),
        title=manifest.dashboard.title,
        addons=addons_html(names, packages),
    )


def build_static(
    spec_path: str | Path,
    data_dir: str | Path,
    out_path: str | Path,
    mode: BundleMode = BundleMode.SINGLE_FILE,
    python_runtime: str = "off",
) -> BuildResult:
    """End-to-end: spec file + data dir → self-contained HTML at ``out_path``."""
    spec = load_spec(spec_path)
    result = build_manifest(spec, data_dir, mode=mode, python_runtime=python_runtime)
    html = render_bundle_html(result.manifest)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return result
