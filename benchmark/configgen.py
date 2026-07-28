"""Generate the ``project.yaml`` and ``dashboard.yaml`` for a benchmark cell.

The generated configs are plain dicts serialized with PyYAML — no depictio
imports are required to *build* them (so this module unit-tests without the full
runtime stack). Validation against the Pydantic models happens at import time on
the server, and in the harness test via ``DashboardDataLite``.

Key decisions (mirroring known-good authored projects like ``penguins``):

- **Static ObjectIds** for project / workflow / each DC / each joined DC. Link
  references use the target DC's real id directly, because ``depictio run`` only
  auto-resolves ``tag:``-prefixed link ids in *template* mode (see run.py).
- **Recursive ``run_*`` scan** so the sharded CSVs from :mod:`benchmark.datagen`
  are picked up: ``data_location.structure: sequencing-runs`` + ``runs_regex``.
- **Explicit 12-column layout** consistent with the authored dashboards rather
  than ``auto_generate_layout`` (which targets a different grid width).
- **connect mode**:
  - ``joins``       -> one ``joins:`` entry per (dc_0, dc_i); components bind to
    the resulting ``joined_<name>`` tables.
  - ``links``       -> one ``links:`` entry from dc_0 to each dc_i.
  - ``independent`` -> components bind round-robin across the raw DCs.
- **filters**: every dashboard gets ``interactive`` components so filtering
  responsiveness is benchmarkable across all connect modes. The generic modes
  get two (a species MultiSelect + a body-mass RangeSlider) bound to the tag
  components render from (the joined table for joins; ``dc_0`` for
  links-adversarial, where link resolution propagates the filter to the linked
  DCs). The realistic ``links`` topology gets a full left panel — see
  :data:`_LINKED_FILTERS` — spread over all three collections, and every
  component on it is a distinct plot of the data (:data:`_LINKED_FIGURES` /
  :data:`_LINKED_TABLES`), so a filter's effect is visible tile by tile.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from benchmark.datagen import COLUMN_DESCRIPTIONS
from benchmark.datagen_linked import (
    FEATURES_TAG,
    JOIN_COLUMN,
    LINKED_COLUMN_DESCRIPTIONS,
    LINKED_TAGS,
    METADATA_TAG,
    METRICS_TAG,
)
from benchmark.matrix import (
    ADVANCED_VIZ_ROTATION,
    FIGURE_VISU_ROTATION,
    Cell,
    ConnectMode,
    DCKind,
    IngestCell,
    VisuType,
)

ENGINE_NAME = "python"


def static_id(*parts: str) -> str:
    """Deterministic 24-hex MongoDB-ObjectId-like id from the given parts."""
    digest = hashlib.md5("::".join(parts).encode()).hexdigest()
    return digest[:24]


@dataclass
class GeneratedConfigs:
    project_path: str
    dashboard_path: str
    project_name: str
    workflow_name: str
    workflow_tag: str
    project_id: str
    # tags a component may bind to (joined tables for joins mode, else raw DCs)
    bindable_dc_tags: list[str]


# ── project.yaml ────────────────────────────────────────────────────────────
def _dc_block(tag: str, dc_id: str, columns_description: dict[str, str] | None = None) -> dict:
    """One Table data collection scanning ``<tag>.csv`` under every ``run_*``.

    ``columns_description`` defaults to the symmetric generator's canonical
    schema; the linked topology passes its own, because its three collections
    have different schemas (that is the point of it).
    """
    return {
        "data_collection_tag": tag,
        "id": dc_id,
        "config": {
            "type": "Table",
            "metatype": "Aggregate",
            "scan": {
                "mode": "recursive",
                "scan_parameters": {"regex_config": {"pattern": f"{tag}.csv"}},
            },
            "dc_specific_properties": {
                "format": "CSV",
                "polars_kwargs": {"separator": ","},
                "columns_description": dict(columns_description or COLUMN_DESCRIPTIONS),
            },
        },
    }


# The realistic link topology, as (source, target) tags — every ordered pair of
# the three collections, i.e. a complete directed graph.
#
# Downstream routes (metadata -> metrics -> features) are the classic shape: the
# sample sheet narrows the QC table and the feature matrix. The *reverse* routes
# matter just as much and used to be missing: without ``features -> metadata`` a
# filter on ``feature_class`` narrowed only the components reading ``features``,
# and every card, figure and table on the other two collections stayed at their
# unfiltered value — a dashboard where half the tiles ignore the filter you just
# moved. Declaring both directions is what makes *every* left-panel filter reach
# *every* component.
#
# Reversing is affordable precisely because of the property this dataset holds:
# ``sample_id`` has ``n_samples`` distinct values, so resolving from the 17 M-row
# ``features`` collection back to ``metadata`` returns hundreds of values, not
# millions. The cycles are safe — ``filter_links._link_paths`` walks breadth-first
# and never revisits a collection within a path.
LINKED_ROUTES: tuple[tuple[str, str], ...] = (
    # downstream: sample sheet -> QC -> features (star + chain)
    (METADATA_TAG, METRICS_TAG),
    (METADATA_TAG, FEATURES_TAG),
    (METRICS_TAG, FEATURES_TAG),
    # upstream: a filter on a feature/QC attribute narrows the sample set too
    (METRICS_TAG, METADATA_TAG),
    (FEATURES_TAG, METADATA_TAG),
    (FEATURES_TAG, METRICS_TAG),
)


def dataset_slug(cell: Cell, n_samples: int | None = None) -> str:
    """Identity of the *data* a cell reads — not of its dashboard.

    The project (and every DC id in it) is keyed on this, so changing the
    dashboard — component count, visu mix — reuses the ingested data instead of
    creating a second project that has to be ingested from scratch. Anything
    that changes the bytes on disk is in the key: size tier, connect mode, DC
    count, and the join-key cardinality of the linked topology.
    """
    slug = f"bench_{cell.size}_dc{cell.n_dcs}_{cell.connect.value}"
    if cell.connect is ConnectMode.LINKS and n_samples:
        slug += f"_s{n_samples}"
    return slug


def linked_dc_ids(cell: Cell, n_samples: int | None = None) -> dict[str, str]:
    """Tag -> static DC id for the linked topology (same ids configgen emits)."""
    slug = dataset_slug(cell, n_samples)
    return {tag: static_id("dc", slug, tag) for tag in LINKED_TAGS}


def build_project(cell: Cell, dataset_dir: str | Path, n_samples: int | None = None) -> dict:
    """Build the project config dict for a cell.

    Named after :func:`dataset_slug`: two cells that read the same data share one
    project, so iterating on the dashboard costs an import rather than an ingest.
    """
    slug = dataset_slug(cell, n_samples)
    project_name = f"Benchmark {slug}"
    workflow_name = f"{slug}_wf"
    project_id = static_id("project", slug)
    workflow_id = static_id("workflow", slug)

    if cell.connect is ConnectMode.LINKS:
        data_collections = [
            _dc_block(tag, static_id("dc", slug, tag), LINKED_COLUMN_DESCRIPTIONS[tag])
            for tag in LINKED_TAGS
        ]
    else:
        dc_tags = [f"dc_{i}" for i in range(cell.n_dcs)]
        data_collections = [_dc_block(tag, static_id("dc", slug, tag)) for tag in dc_tags]

    project: dict = {
        "name": project_name,
        "project_type": "advanced",
        "is_public": True,
        "id": project_id,
        "workflows": [
            {
                "name": workflow_name,
                "id": workflow_id,
                "engine": {"name": ENGINE_NAME},
                "description": f"Benchmark workflow for {slug}",
                "data_location": {
                    "structure": "sequencing-runs",
                    "runs_regex": "run_*",
                    "locations": [str(Path(dataset_dir).resolve())],
                },
                "data_collections": data_collections,
            }
        ],
    }

    if cell.connect is ConnectMode.JOINS:
        project["joins"] = [
            {
                "id": static_id("join", slug, f"0_{i}"),
                "name": f"join_0_{i}",
                "left_dc": "dc_0",
                "right_dc": f"dc_{i}",
                "on_columns": ["individual_id"],
                "how": "inner",
                "workflow_name": workflow_name,
                "persist": True,
            }
            for i in range(1, cell.n_dcs)
        ]
    elif cell.connect is ConnectMode.LINKS_ADVERSARIAL:
        project["links"] = [
            {
                "source_dc_id": static_id("dc", slug, "dc_0"),
                "source_column": "individual_id",
                "target_dc_id": static_id("dc", slug, f"dc_{i}"),
                "target_type": "table",
                "link_config": {"resolver": "direct"},
                "description": f"Link dc_0 -> dc_{i}",
            }
            for i in range(1, cell.n_dcs)
        ]
    elif cell.connect is ConnectMode.LINKS:
        # Star + chain in one project: metadata reaches features directly AND
        # through metrics, so a filter on metadata exercises the 1-hop and the
        # 2-hop path against the same target.
        project["links"] = [
            {
                "id": static_id("link", slug, f"{source}_{target}"),
                "source_dc_id": static_id("dc", slug, source),
                "source_column": JOIN_COLUMN,
                "target_dc_id": static_id("dc", slug, target),
                "target_type": "table",
                "link_config": {"resolver": "direct"},
                "description": f"Link {source} -> {target}",
            }
            for source, target in LINKED_ROUTES
        ]

    return project


# ── ingestion-only project configs (table / multiqc / images) ───────────────
def _multiqc_dc_block(tag: str, dc_id: str) -> dict:
    return {
        "data_collection_tag": tag,
        "id": dc_id,
        "description": "Benchmark MultiQC report",
        "config": {
            "type": "MultiQC",
            "scan": {
                "mode": "recursive",
                "scan_parameters": {"regex_config": {"pattern": "multiqc_data/multiqc.parquet"}},
            },
            # Modules/plots are auto-extracted from the parquet at ingest; an empty
            # spec is fine for a throughput benchmark.
            "dc_specific_properties": {},
        },
    }


def _image_dc_block(
    tag: str, dc_id: str, metadata_csv: str, images_dir: str, s3_base_folder: str
) -> dict:
    return {
        "data_collection_tag": tag,
        "id": dc_id,
        "description": "Benchmark image collection",
        "config": {
            "type": "Image",
            "metatype": "Images",
            "scan": {
                "mode": "single",
                "scan_parameters": {"filename": str(metadata_csv)},
            },
            "dc_specific_properties": {
                "format": "csv",
                "columns_description": {
                    "sample_id": "Unique sample identifier",
                    "image_path": "Relative path to image file",
                    "category": "Sample category",
                    "quality_score": "Quality score 0-1",
                },
                "image_column": "image_path",
                "s3_base_folder": s3_base_folder,
                "local_images_path": str(images_dir),
                "supported_formats": [".png", ".jpg", ".jpeg"],
                "thumbnail_size": 150,
            },
        },
    }


def build_ingest_project(
    cell: IngestCell,
    dataset_dir: str | Path,
    *,
    s3_bucket: str = "depictio-bucket",
    metadata_csv: str | None = None,
    images_dir: str | None = None,
    run_tag: str = "",
) -> dict:
    """Build a minimal ingestion project for one :class:`IngestCell`.

    TABLE reuses the recursive ``run_*`` CSV scan; MULTIQC scans ``run_*`` for the
    staged parquet; IMAGES is a single-scan metadata table plus an ``image_column``
    whose ``s3_base_folder`` is where :func:`benchmark.runner` pushes the images.

    ``run_tag`` namespaces the project name *and* the derived static IDs. Without
    it, re-running a cell reuses the same project, and the files registered by
    earlier runs are still attached to the data collection — so each run
    aggregates its own data plus every previous run's, inflating row counts (a
    10 MB cell measured 137k rows, then 275k, then 413k) and silently
    invalidating any before/after comparison.
    """
    slug = cell.slug
    scope = f"{slug}-{run_tag}" if run_tag else slug
    project_name = f"Benchmark {scope}"
    workflow_name = f"{slug}_wf"
    resolved_dir = str(Path(dataset_dir).resolve())

    if cell.kind is DCKind.TABLE:
        dc_tags = [f"dc_{i}" for i in range(cell.n_dcs)]
        data_collections = [_dc_block(tag, static_id("dc", scope, tag)) for tag in dc_tags]
        data_location = {
            "structure": "sequencing-runs",
            "runs_regex": "run_*",
            "locations": [resolved_dir],
        }
    elif cell.kind is DCKind.MULTIQC:
        data_collections = [_multiqc_dc_block("multiqc_data", static_id("dc", scope, "multiqc"))]
        data_location = {
            "structure": "sequencing-runs",
            "runs_regex": "run_*",
            "locations": [resolved_dir],
        }
    else:  # IMAGES
        s3_base_folder = f"s3://{s3_bucket}/bench_images/{scope}/"
        data_collections = [
            _image_dc_block(
                "sample_images",
                static_id("dc", scope, "images"),
                metadata_csv=metadata_csv or str(Path(resolved_dir) / "images_data.csv"),
                images_dir=images_dir or str(Path(resolved_dir) / "images"),
                s3_base_folder=s3_base_folder,
            )
        ]
        data_location = {"structure": "flat", "locations": [resolved_dir]}

    return {
        "name": project_name,
        "project_type": "advanced",
        "is_public": True,
        "id": static_id("project", scope),
        "workflows": [
            {
                "name": workflow_name,
                "id": static_id("workflow", scope),
                "engine": {"name": ENGINE_NAME},
                "description": f"Benchmark ingestion workflow for {slug}",
                "data_location": data_location,
                "data_collections": data_collections,
            }
        ],
    }


def bindable_tags(cell: Cell) -> list[str]:
    """Tags a component may bind to for this connect mode."""
    if cell.connect is ConnectMode.JOINS:
        return [f"joined_join_0_{i}" for i in range(1, cell.n_dcs)]
    if cell.connect is ConnectMode.LINKS:
        # The heavy collection: the default binding, and where most of the timed
        # components sit. Individual components override it from the catalogues
        # (:data:`_LINKED_FIGURES` / :data:`_LINKED_TABLES`) so the dashboard also
        # renders its sample sheet and its QC table, as a real project would.
        return [FEATURES_TAG]
    return [f"dc_{i}" for i in range(cell.n_dcs)]


# Human-readable size labels for dashboard titles (SIZES keys -> display text).
_SIZE_LABELS: dict[str, str] = {
    "10mb": "10 MB",
    "100mb": "100 MB",
    "1gb": "1 GB",
    "5gb": "5 GB",
    "10gb": "10 GB",
}

# Short visu labels for the title's "figure+table+adv-viz" segment.
_VISU_LABELS: dict[str, str] = {
    "figure": "figure",
    "table": "table",
    "advanced_viz": "adv-viz",
}


def readable_title(cell: Cell) -> str:
    """Decode a cell's axes into a scannable title.

    e.g. ``10 MB · 5 comp · 2 DC · joins · figure+table+adv-viz`` — the raw
    ``cell.slug`` is kept as the project name (binding key) but is too cryptic
    for the dashboard list, so the display title spells every axis out.
    """
    size = _SIZE_LABELS.get(cell.size, cell.size)
    visu = "+".join(_VISU_LABELS.get(v.value, v.value) for v in cell.visu)
    return f"{size} · {cell.n_components} comp · {cell.n_dcs} DC · {cell.connect.value} · {visu}"


# ── dashboard.yaml ──────────────────────────────────────────────────────────
# Grid rhythm for every generated dashboard, expressed in the REACT VIEWER's
# grid — not Dash's 12-column one. The viewer splits a dashboard into two grids
# (packages/depictio-react-core/src/api.ts): the right panel is **8 columns**
# and the left panel, which holds the interactive filters, is a single column
# with the filters stacked. Emitting 12-column boxes here is what made three
# w=3 cards wrap after two, and two w=6 components take a row each.
#
#   - cards: 4 per row, short;
#   - figures / tables / advanced viz: 2 per row.
_RIGHT_PANEL_COLS = 8
_STRIP_PER_ROW = 4
_STRIP_H = 2
_BODY_PER_ROW = 2
_BODY_H = 5
# Left panel: one column, so a filter is full width and rows stack.
_FILTER_W = 1
_FILTER_H = 2


def _layout(
    index: int, w: int, h: int, per_row: int = 2, y_offset: int = 0, cols: int = _RIGHT_PANEL_COLS
) -> dict:
    """Flow layout on the right panel's grid.

    ``y_offset`` reserves the rows the cards occupy so figures/tables start below
    them instead of overlapping.
    """
    col = index % per_row
    row = index // per_row
    return {"x": col * (cols // per_row), "y": y_offset + row * h, "w": w, "h": h}


def _strip_layout(index: int) -> dict:
    """Position for the ``index``-th card, 4 per row on the 8-column panel."""
    return _layout(index, w=_RIGHT_PANEL_COLS // _STRIP_PER_ROW, h=_STRIP_H, per_row=_STRIP_PER_ROW)


def _filter_layout(index: int) -> dict:
    """Position for the ``index``-th interactive filter in the left panel.

    That panel is one column wide, so filters stack — giving them x/w from the
    right panel's grid would place them off it.
    """
    return {"x": 0, "y": index * _FILTER_H, "w": _FILTER_W, "h": _FILTER_H}


def _strip_height(n_items: int) -> int:
    """Grid rows a strip of ``n_items`` occupies, at 4 per row."""
    return math.ceil(n_items / _STRIP_PER_ROW) * _STRIP_H


def _linked_figure_kwargs(visu_type: str) -> dict:
    """Figure bindings for the ``features`` schema (linked topology).

    ``bar`` binds a low-cardinality categorical x (``feature_class``, 3 values)
    so the aggregation service's exact group-by stays tiny; ``line`` is a sampled
    mark-per-row plot. See ``matrix.FIGURE_VISU_ROTATION``.

    Used for the *symmetric-shaped* fallback only; the linked dashboard itself
    draws from :data:`_LINKED_FIGURES`, where each entry is a distinct plot.
    """
    return {
        "scatter": {"x": "mean_expression", "y": "expression", "color": "feature_class"},
        "box": {"x": "feature_class", "y": "expression"},
        "histogram": {"x": "expression"},
        "bar": {"x": "feature_class", "y": "expression"},
        "line": {"x": "mean_expression", "y": "expression"},
    }.get(visu_type, {"x": "mean_expression", "y": "expression"})


@dataclass(frozen=True)
class _LinkedFigure:
    """One figure in the linked dashboard, bound to a named plot."""

    dc_tag: str
    visu_type: str
    kwargs: dict
    title: str


@dataclass(frozen=True)
class _LinkedTable:
    """One table in the linked dashboard.

    ``columns`` is the display allowlist (``TableLiteComponent.columns``). The
    React grid restricts itself to those fields; the server still returns the
    whole row, so this changes what the user reads, not what the render costs.
    An empty list shows every column.
    """

    dc_tag: str
    columns: tuple[str, ...]
    title: str


# Every figure/table in the linked dashboard is a *different* plot of the
# project's data. Rotating a handful of visu types over one collection — which is
# what the generic path does — produced ten identical tables and each chart twice,
# so a dashboard of 30 components showed maybe 12 distinct things and no filter
# could be told apart from the next by looking at it.
#
# The bindings are spread across all three collections on purpose. Most of the
# heavy work stays on ``features`` (that is the render cost the tier is about),
# but a project that renders nothing from its sample sheet or its QC table is not
# a project — and with the complete link graph those small components are exactly
# where a filter's *propagation* shows up. Results are recorded per component with
# their ``dc_tag`` (``RenderResult``), so the grains stay separable in the report.
#
# Bar/box x-columns stay low-cardinality so the figure aggregation service's exact
# group-by stays under its ``_MAX_GROUPS`` ceiling (rank: 5, metric: 4, tool: 5).
_LINKED_FIGURES: tuple[_LinkedFigure, ...] = (
    _LinkedFigure(
        FEATURES_TAG,
        "scatter",
        {"x": "mean_expression", "y": "expression", "color": "feature_class"},
        "Expression vs mean expression",
    ),
    _LinkedFigure(
        FEATURES_TAG,
        "scatter",
        {"x": "effect_size", "y": "neg_log10_p", "color": "rank"},
        "Effect size vs significance",
    ),
    _LinkedFigure(
        FEATURES_TAG,
        "box",
        {"x": "feature_class", "y": "expression"},
        "Expression by feature class",
    ),
    _LinkedFigure(FEATURES_TAG, "histogram", {"x": "neg_log10_p"}, "Significance distribution"),
    _LinkedFigure(FEATURES_TAG, "bar", {"x": "rank", "y": "expression"}, "Expression by rank"),
    _LinkedFigure(
        FEATURES_TAG,
        "line",
        {"x": "position", "y": "frac_expressing"},
        "Detection along the position axis",
    ),
    _LinkedFigure(METRICS_TAG, "box", {"x": "tool", "y": "value"}, "Metric value by QC tool"),
    _LinkedFigure(METRICS_TAG, "histogram", {"x": "mapped_pct"}, "Mapped % distribution"),
    _LinkedFigure(
        METRICS_TAG,
        "bar",
        {"x": "metric", "y": "duplication_pct"},
        "Duplication % by metric",
    ),
    _LinkedFigure(METADATA_TAG, "histogram", {"x": "age"}, "Donor age distribution"),
)

_LINKED_TABLES: tuple[_LinkedTable, ...] = (
    _LinkedTable(METADATA_TAG, (), "Sample sheet"),
    _LinkedTable(METADATA_TAG, ("sample_id", "tissue", "sex", "age"), "Donor attributes"),
    _LinkedTable(METRICS_TAG, ("sample_id", "tool", "metric", "value"), "QC metric values"),
    _LinkedTable(
        METRICS_TAG,
        ("sample_id", "mapped_pct", "duplication_pct", "gc_pct"),
        "Alignment rates",
    ),
    _LinkedTable(FEATURES_TAG, (), "Feature matrix (every column)"),
    _LinkedTable(
        FEATURES_TAG,
        ("sample_id", "feature_id", "expression", "mean_expression"),
        "Expression per feature",
    ),
    _LinkedTable(
        FEATURES_TAG,
        ("feature_id", "effect_size", "neg_log10_p"),
        "Differential statistics",
    ),
    _LinkedTable(
        FEATURES_TAG,
        ("feature_id", "chr", "position", "feature_class"),
        "Genomic coordinates",
    ),
    _LinkedTable(
        FEATURES_TAG,
        ("sample_id", "rank", "feature_class", "expression"),
        "Taxonomic assignment",
    ),
    _LinkedTable(
        FEATURES_TAG,
        ("sample_id", "feature_id", "frac_expressing"),
        "Detection rate per feature",
    ),
)


def _figure_kwargs(visu_type: str) -> dict:
    return {
        "scatter": {"x": "bill_length_mm", "y": "body_mass_g", "color": "species"},
        "bar": {"x": "species", "y": "body_mass_g"},
        "box": {"x": "species", "y": "bill_length_mm", "color": "sex"},
        "histogram": {"x": "body_mass_g"},
    }.get(visu_type, {"x": "bill_length_mm", "y": "body_mass_g"})


def _advanced_viz_config(viz_kind: str, feature_id_col: str = "individual_id") -> dict:
    """Component config for one advanced-viz ``viz_kind``, bound to the linked
    ``features`` columns (see ``benchmark.datagen_linked``).

    Every kind here binds to a real column of the right dtype, so the render
    exercises the actual reduction path rather than a validation error. The
    column choices are the generator's, not biology's — ``chr``/``position`` are
    synthetic, ``qq`` reads the uniform ``frac_expressing`` as its p-value (so
    the QQ line is the ideal diagonal), and the taxonomy kinds treat
    ``feature_class`` as a taxon. The three sampling policies are all covered:
    tail (volcano/ma/manhattan), hash (qq/lollipop), none (the rest).
    """
    configs: dict[str, dict] = {
        # ── tail: keep the significant end whole, stride the middle ──────────
        "volcano": {
            "viz_kind": "volcano",
            "feature_id_col": feature_id_col,
            "effect_size_col": "effect_size",
            "significance_col": "neg_log10_p",
            "significance_is_neg_log10": True,
        },
        "ma": {
            "viz_kind": "ma",
            "feature_id_col": feature_id_col,
            "avg_log_intensity_col": "mean_expression",
            "log2_fold_change_col": "effect_size",
        },
        "manhattan": {
            "viz_kind": "manhattan",
            "chr_col": "chr",
            "pos_col": "position",
            "score_col": "neg_log10_p",
            "feature_col": feature_id_col,
            "effect_col": "effect_size",
        },
        # ── hash: uniform sample is faithful (mark-per-row) ──────────────────
        "qq": {
            "viz_kind": "qq",
            "p_value_col": "frac_expressing",
            "feature_id_col": feature_id_col,
            "category_col": "feature_class",
        },
        "lollipop": {
            "viz_kind": "lollipop",
            "feature_id_col": feature_id_col,
            "position_col": "position",
            "category_col": "feature_class",
            "effect_col": "effect_size",
        },
        # ── none: renderer aggregates client-side, never sample by default ───
        "da_barplot": {
            "viz_kind": "da_barplot",
            "feature_id_col": feature_id_col,
            "contrast_col": "feature_class",
            "lfc_col": "effect_size",
            "significance_col": "neg_log10_p",
        },
        "sunburst": {
            "viz_kind": "sunburst",
            "rank_cols": ["rank", "feature_class"],
            "abundance_col": "expression",
        },
        "sankey": {
            "viz_kind": "sankey",
            "step_cols": ["rank", "feature_class"],
        },
        "stacked_taxonomy": {
            "viz_kind": "stacked_taxonomy",
            "sample_id_col": "sample_id",
            "taxon_col": "feature_class",
            "rank_col": "rank",
            "abundance_col": "expression",
        },
        "dot_plot": {
            "viz_kind": "dot_plot",
            "cluster_col": "feature_class",
            "gene_col": feature_id_col,
            "mean_expression_col": "mean_expression",
            "frac_expressing_col": "frac_expressing",
        },
    }
    try:
        return configs[viz_kind]
    except KeyError:
        raise ValueError(f"Unsupported benchmark viz_kind {viz_kind!r}")


@dataclass(frozen=True)
class _LinkedFilter:
    """One interactive filter in the linked dashboard's left panel."""

    column: str
    dc_tag: str
    kind: str  # interactive_component_type
    column_type: str
    title: str
    group: str  # filters sharing a group render inside one card (max 3)
    icon: str  # Iconify name shown next to the filter's title


# One accent colour per group, so the left panel reads as four blocks rather
# than twelve identical rows — and the colour says which collection the filter
# starts on, which is the thing that differs between them.
_LINKED_FILTER_COLORS: dict[str, str] = {
    "Experiment": "#377EB8",  # blue   - metadata
    "Donor": "#984EA3",  # purple - metadata
    "Quality control": "#DD8452",  # orange - metrics
    "Features": "#8BC34A",  # green  - features (the heavy collection)
}


# The left panel, as it would be on a real project: filters on every collection,
# bucketed into cards by what they describe rather than by which table they
# happen to live on.
#
# Every one of them reaches every component, because ``LINKED_ROUTES`` is a
# complete graph — that is the point of the expansion. They also cover the three
# resolution costs that differ: a filter on ``metadata`` (500 rows) resolves off
# a tiny table, one on ``metrics`` (10 k rows) off a small one, and one on
# ``features`` (millions) has to scan the heavy collection to collect the sample
# set it corresponds to.
#
# Groups hold at most 3 members (``DashboardDataLite.validate_interactive_groups``),
# so the buckets are sized to that.
_LINKED_FILTERS: tuple[_LinkedFilter, ...] = (
    # ── the sample sheet ────────────────────────────────────────────────────
    _LinkedFilter(
        "condition", METADATA_TAG, "MultiSelect", "object", "Condition", "Experiment", "mdi:flask"
    ),
    _LinkedFilter(
        "timepoint",
        METADATA_TAG,
        "MultiSelect",
        "object",
        "Timepoint",
        "Experiment",
        "mdi:clock-outline",
    ),
    _LinkedFilter(
        "batch",
        METADATA_TAG,
        "MultiSelect",
        "object",
        "Batch",
        "Experiment",
        "mdi:layers-triple",
    ),
    _LinkedFilter(
        "tissue", METADATA_TAG, "MultiSelect", "object", "Tissue", "Donor", "mdi:heart-pulse"
    ),
    _LinkedFilter(
        "sex", METADATA_TAG, "MultiSelect", "object", "Sex", "Donor", "mdi:gender-male-female"
    ),
    _LinkedFilter(
        "age", METADATA_TAG, "RangeSlider", "int64", "Age", "Donor", "mdi:calendar-account"
    ),
    # ── QC, one hop away from the sample sheet ──────────────────────────────
    _LinkedFilter(
        "tool", METRICS_TAG, "MultiSelect", "object", "QC tool", "Quality control", "mdi:tools"
    ),
    _LinkedFilter(
        "metric", METRICS_TAG, "MultiSelect", "object", "Metric", "Quality control", "mdi:ruler"
    ),
    _LinkedFilter(
        "mapped_pct",
        METRICS_TAG,
        "RangeSlider",
        "float64",
        "Mapped %",
        "Quality control",
        "mdi:target",
    ),
    # ── the heavy collection: filters that apply natively there and travel
    #    *back* to the other two ─────────────────────────────────────────────
    _LinkedFilter(
        "feature_class",
        FEATURES_TAG,
        "MultiSelect",
        "object",
        "Feature class",
        "Features",
        "mdi:shape",
    ),
    _LinkedFilter(
        "chr", FEATURES_TAG, "MultiSelect", "object", "Chromosome", "Features", "mdi:dna"
    ),
    _LinkedFilter(
        "rank", FEATURES_TAG, "MultiSelect", "object", "Taxonomic rank", "Features", "mdi:file-tree"
    ),
)


@dataclass(frozen=True)
class _LinkedCard:
    """One metric card in the strip above the linked dashboard's components."""

    tag: str
    dc_tag: str
    column: str
    column_type: str
    aggregation: str
    title: str


# One card per collection plus a second QC metric, so the strip itself shows
# whether a filter reached every grain: with the complete link graph all four
# must move when any filter moves. Cards were the clearest symptom of the old
# one-directional topology — the metrics cards sat frozen through the whole
# ``features`` sweep.
_LINKED_CARDS: tuple[_LinkedCard, ...] = (
    _LinkedCard("card-samples", METADATA_TAG, "sample_id", "object", "nunique", "Samples"),
    _LinkedCard(
        "card-mean-metric", METRICS_TAG, "value", "float64", "average", "Mean metric value"
    ),
    _LinkedCard("card-mapped", METRICS_TAG, "mapped_pct", "float64", "average", "Mean mapped %"),
    _LinkedCard(
        "card-mean-expression", FEATURES_TAG, "expression", "float64", "average", "Mean expression"
    ),
)


def _linked_filter_components(workflow_tag: str) -> list[dict]:
    """The left panel + card strip for the linked topology.

    Filters sit on all three collections on purpose. Most of them still do NOT
    sit on the collection a given component reads — that is the topology being
    measured, and with the complete link graph it now runs in both directions: a
    filter on ``metadata`` travels down to ``metrics`` (1 hop) and ``features``
    (1 hop directly, 2 through metrics), and one on ``features`` travels back up
    the same edges.
    """
    # Filters and cards are laid out from y=0 *independently*: the dashboard
    # import splits them into two grids — interactives go to
    # ``left_panel_layout_data``, everything else to ``right_panel_layout_data``
    # — so reserving the filters' height in the components' panel would leave an
    # empty band at the top of it and push the cards down a row.
    components: list[dict] = [
        {
            "tag": f"filter-{f.column.replace('_', '-')}",
            "component_type": "interactive",
            "workflow_tag": workflow_tag,
            "data_collection_tag": f.dc_tag,
            "interactive_component_type": f.kind,
            "column_name": f.column,
            "column_type": f.column_type,
            "group": f.group,
            "title": f.title,
            # Colour by group (i.e. by originating collection), icon by what the
            # column means.
            "custom_color": _LINKED_FILTER_COLORS[f.group],
            "icon_name": f.icon,
            "layout": _filter_layout(i),
        }
        for i, f in enumerate(_LINKED_FILTERS)
    ]
    components += [
        {
            "tag": card.tag,
            "component_type": "card",
            "workflow_tag": workflow_tag,
            "data_collection_tag": card.dc_tag,
            "column_name": card.column,
            "column_type": card.column_type,
            "aggregation": card.aggregation,
            "title": card.title,
            "layout": _strip_layout(i),
        }
        for i, card in enumerate(_LINKED_CARDS)
    ]
    return components


def _filter_tag(cell: Cell) -> str:
    """The DC/joined tag the filters bind to so cross-filtering actually fires.

    - ``links``  : bind to ``metadata`` — the linked topology's filter origin.
    - ``links-adversarial`` : bind to the source ``dc_0`` — link resolution
      propagates the filter to the linked DCs the components render from.
    - ``joins``  : bind to the joined table the components themselves bind to, so
      the filter narrows the same frame (an interactive only filters components
      sharing its data collection).
    - ``independent`` : bind to ``dc_0`` (the first raw DC components round-robin).
    """
    if cell.connect is ConnectMode.LINKS:
        return METADATA_TAG
    if cell.connect is ConnectMode.LINKS_ADVERSARIAL:
        return "dc_0"
    return bindable_tags(cell)[0]


def _filter_components(cell: Cell, workflow_tag: str) -> list[dict]:
    """Two interactive filters (categorical + numeric range) to benchmark
    filtering responsiveness. Added to every dashboard regardless of connect
    mode. Laid out as a top strip so they don't overlap the figures/tables."""
    filter_tag = _filter_tag(cell)
    base = {"workflow_tag": workflow_tag, "data_collection_tag": filter_tag}
    return [
        {
            "tag": "filter-species",
            "component_type": "interactive",
            **base,
            "interactive_component_type": "MultiSelect",
            "column_name": "species",
            "column_type": "object",
            "title": "Species",
            "layout": _filter_layout(0),
        },
        {
            "tag": "filter-body-mass",
            "component_type": "interactive",
            **base,
            "interactive_component_type": "RangeSlider",
            "column_name": "body_mass_g",
            "column_type": "int64",
            "title": "Body mass",
            "layout": _filter_layout(1),
        },
        # Two metric cards sharing the filter DC. Cards were previously absent
        # from the matrix, which hid their worst case entirely: with no filters
        # they're answered from precomputed specs without touching Delta, but the
        # moment a filter is applied that shortcut is gone and the value has to be
        # computed against the (filtered) data. Both are timed — the unfiltered
        # pass and the filtered one — so the difference is visible.
        {
            "tag": "card-mean-mass",
            "component_type": "card",
            **base,
            "column_name": "body_mass_g",
            "column_type": "int64",
            # "average", not "mean": both reduce identically, but the card model
            # only accepts "average" for a numeric column.
            "aggregation": "average",
            "title": "Mean body mass",
            "layout": _strip_layout(0),
        },
        {
            "tag": "card-unique-species",
            "component_type": "card",
            **base,
            "column_name": "species",
            "column_type": "object",
            "aggregation": "nunique",
            "title": "Distinct species",
            "layout": _strip_layout(1),
        },
    ]


# What each advanced-viz kind is showing, in the linked dashboard's terms. The
# generic path keeps "Advanced viz N (kind)" — there the kind IS the identity.
_ADVANCED_VIZ_TITLES: dict[str, str] = {
    "volcano": "Volcano - effect size vs significance",
    "ma": "MA - fold change vs mean intensity",
    "manhattan": "Manhattan - significance along the genome",
    "qq": "QQ - observed vs expected p-values",
    "lollipop": "Lollipop - effect size by position",
    "da_barplot": "Differential abundance by feature class",
    "sunburst": "Sunburst - rank then feature class",
    "sankey": "Sankey - rank to feature class",
    "stacked_taxonomy": "Stacked taxonomy per sample",
    "dot_plot": "Dot plot - expression and detection",
}


def _timed_components(
    cell: Cell,
    workflow_tag: str,
    tags: list[str],
    *,
    linked: bool,
    y_offset: int,
) -> list[dict]:
    """The components whose render latency is measured, rotating through ``visu``.

    ``linked`` selects the column bindings: the linked topology's ``features``
    collection has its own schema, and its figures/tables come from the
    :data:`_LINKED_FIGURES` / :data:`_LINKED_TABLES` catalogues so that no two
    components on the dashboard show the same thing. Past the length of a
    catalogue (10 of each, i.e. 30 components with the full ``visu`` rotation)
    the entries repeat — a cell asking for more gets duplicates again, which is
    a size question, not a modelling one.

    ``y_offset`` is where the strip ends, so the timed components never overlap
    the filters however many there are.
    """
    figure_kwargs = _linked_figure_kwargs if linked else _figure_kwargs
    feature_id_col = "feature_id" if linked else "individual_id"

    components: list[dict] = []
    fig_i = tbl_i = av_i = 0
    for i in range(cell.n_components):
        visu = cell.visu[i % len(cell.visu)]
        base = {"workflow_tag": workflow_tag, "data_collection_tag": tags[i % len(tags)]}
        layout = _layout(
            i,
            w=_RIGHT_PANEL_COLS // _BODY_PER_ROW,
            h=_BODY_H,
            per_row=_BODY_PER_ROW,
            y_offset=y_offset,
        )

        if visu is VisuType.FIGURE:
            if linked:
                spec = _LINKED_FIGURES[fig_i % len(_LINKED_FIGURES)]
                visu_type, kwargs, title = spec.visu_type, dict(spec.kwargs), spec.title
                base = {"workflow_tag": workflow_tag, "data_collection_tag": spec.dc_tag}
            else:
                visu_type = FIGURE_VISU_ROTATION[fig_i % len(FIGURE_VISU_ROTATION)]
                kwargs = figure_kwargs(visu_type)
                title = f"Figure {i} ({visu_type})"
            fig_i += 1
            components.append(
                {
                    "tag": f"fig-{i}",
                    "component_type": "figure",
                    **base,
                    "visu_type": visu_type,
                    "dict_kwargs": kwargs,
                    "title": title,
                    "layout": layout,
                }
            )
        elif visu is VisuType.TABLE:
            table: dict = {
                "tag": f"tbl-{i}",
                "component_type": "table",
                **base,
                "title": f"Table {i}",
                "layout": layout,
            }
            if linked:
                spec_t = _LINKED_TABLES[tbl_i % len(_LINKED_TABLES)]
                table["data_collection_tag"] = spec_t.dc_tag
                table["title"] = spec_t.title
                if spec_t.columns:
                    table["columns"] = list(spec_t.columns)
            tbl_i += 1
            components.append(table)
        elif visu is VisuType.ADVANCED_VIZ:
            viz_kind = ADVANCED_VIZ_ROTATION[av_i % len(ADVANCED_VIZ_ROTATION)]
            av_i += 1
            components.append(
                {
                    "tag": f"av-{i}",
                    "component_type": "advanced_viz",
                    **base,
                    "viz_kind": viz_kind,
                    "config": _advanced_viz_config(viz_kind, feature_id_col=feature_id_col),
                    "title": (
                        _ADVANCED_VIZ_TITLES.get(viz_kind, viz_kind)
                        if linked
                        else f"Advanced viz {i} ({viz_kind})"
                    ),
                    "layout": layout,
                }
            )
    return components


def build_dashboard(cell: Cell, project: dict) -> dict:
    """Build the dashboard (lite) config dict for a cell."""
    workflow_name = project["workflows"][0]["name"]
    workflow_tag = f"{ENGINE_NAME}/{workflow_name}"
    linked = cell.connect is ConnectMode.LINKS

    # Interactive filters on every dashboard so filtering responsiveness is
    # benchmarkable across all connect modes (previously links-only).
    if linked:
        filters = _linked_filter_components(workflow_tag)
    else:
        filters = _filter_components(cell, workflow_tag)
    n_filters = sum(1 for c in filters if c["component_type"] == "interactive")

    return {
        "version": 1,
        "title": readable_title(cell),
        "subtitle": (
            f"size={cell.size} components={cell.n_components} "
            f"dcs={cell.n_dcs} connect={cell.connect.value} filters={n_filters}"
        ),
        "project_tag": project["name"],
        # Only the CARDS share the components' panel, so only their height is
        # reserved — the interactive filters are moved to the left panel at
        # import and their rows do not exist in this grid.
        "components": _timed_components(
            cell,
            workflow_tag,
            bindable_tags(cell),
            linked=linked,
            y_offset=_strip_height(sum(1 for c in filters if c["component_type"] == "card")),
        )
        + filters,
    }


@dataclass(frozen=True)
class FilterPlan:
    """One filter *origin* to time rounds against.

    The cost of a filter change depends on where the filter starts, not only on
    how big the target is: a filter on ``metadata`` must be translated through
    one or two links before ``features`` can be narrowed, while a filter on
    ``features`` itself applies natively. Reporting them together would average
    two different mechanisms.

    ``values`` are successive rounds, each using a value set none of the earlier
    rounds used — re-applying one is answered by the filtered frame cache and
    would time the cache instead of the filter. ``max_rounds`` is therefore a
    hard ceiling, not a suggestion: asking for more rounds than there are values
    would start timing the cache.

    ``sequential_value`` is reserved for the ``--cross-filter`` sequential pass,
    which runs *before* the rounds. It is deliberately absent from ``values``:
    reusing round 0's value there would make round 0 a cache hit.
    """

    dc_tag: str  # collection the filter originates on
    column: str
    values: tuple[tuple[str, ...], ...]
    hops: int  # link hops to the farthest component (0 = no propagation)
    label: str
    sequential_value: tuple[str, ...] = ()
    # Collections this filter can actually narrow: its own, plus every one
    # reachable from it through the declared links. A component outside this set
    # renders unfiltered, and counting it in a round's window would compare two
    # different amounts of work between origins.
    reachable_tags: frozenset[str] = frozenset()

    @property
    def max_rounds(self) -> int:
        return len(self.values)


_SPECIES_ROUNDS: tuple[tuple[str, ...], ...] = (
    ("Adelie",),
    ("Gentoo",),
    ("Chinstrap",),
    ("Adelie", "Gentoo"),
)
_CONDITION_ROUNDS: tuple[tuple[str, ...], ...] = (
    ("control",),
    ("treated",),
    ("recovery",),
    ("control", "treated"),
)
_FEATURE_CLASS_ROUNDS: tuple[tuple[str, ...], ...] = (
    ("protein_coding",),
    ("lncRNA",),
    ("pseudogene",),
    ("protein_coding", "lncRNA"),
)
# Panel-specific tools (see ``datagen_linked._TOOL_PANELS``): each selects the
# samples that ran it, so the translation back to the sample sheet narrows.
# ``fastqc`` / ``samtools`` are in every panel and would resolve to every sample.
_TOOL_ROUNDS: tuple[tuple[str, ...], ...] = (
    ("picard",),
    ("bcftools",),
    ("qualimap",),
    ("picard", "bcftools"),
)


def _reachable_tags(origin: str, routes: tuple[tuple[str, str], ...]) -> frozenset[str]:
    """``origin`` plus everything reachable from it by following ``routes``.

    Links are directed, so reachability has to be computed rather than assumed:
    ``metadata -> features`` alone would not let a filter on ``features`` narrow
    ``metadata``. :data:`LINKED_ROUTES` declares both directions precisely so
    that every origin reaches everything — but the adversarial topology does not,
    and a component outside the set renders unfiltered. Counting one of those in
    a round's window would compare two different amounts of work between origins.
    """
    reached = {origin}
    frontier = [origin]
    while frontier:
        current = frontier.pop()
        for source, target in routes:
            if source == current and target not in reached:
                reached.add(target)
                frontier.append(target)
    return frozenset(reached)


def filter_plans(cell: Cell) -> list[FilterPlan]:
    """Filter origins to time for this cell, in the order they should run."""
    if cell.connect is ConnectMode.LINKS:
        # One sweep per collection a filter can start on. With the complete link
        # graph all three reach the whole dashboard, so what differs between them
        # is no longer *how much* they narrow but what the translation costs:
        # resolving off a 500-row sample sheet, a 10 k-row QC table, or the
        # multi-million-row feature matrix. Averaging them would describe none of
        # the three, so they stay apart.
        #
        # ``hops`` is the longest route the resolver may walk to a component:
        # every pair is one hop apart directly, and ``_link_paths`` also returns
        # the 2-hop alternative through the third collection.
        return [
            FilterPlan(
                dc_tag=METADATA_TAG,
                column="condition",
                values=_CONDITION_ROUNDS,
                hops=2,
                label="metadata-origin",
                sequential_value=("treated", "recovery"),
                reachable_tags=_reachable_tags(METADATA_TAG, LINKED_ROUTES),
            ),
            FilterPlan(
                dc_tag=METRICS_TAG,
                column="tool",
                values=_TOOL_ROUNDS,
                hops=2,
                label="metrics-origin",
                sequential_value=("mosdepth",),
                reachable_tags=_reachable_tags(METRICS_TAG, LINKED_ROUTES),
            ),
            FilterPlan(
                dc_tag=FEATURES_TAG,
                column="feature_class",
                values=_FEATURE_CLASS_ROUNDS,
                hops=2,
                label="features-origin",
                sequential_value=("lncRNA", "pseudogene"),
                # Applies natively to the components on ``features`` and travels
                # back up the reverse links to narrow ``metrics`` and
                # ``metadata`` — the resolution that has to scan the heavy
                # collection to collect its sample set.
                reachable_tags=_reachable_tags(FEATURES_TAG, LINKED_ROUTES),
            ),
        ]
    origin = _filter_tag(cell)
    if cell.connect is ConnectMode.LINKS_ADVERSARIAL:
        routes = tuple(("dc_0", f"dc_{i}") for i in range(1, cell.n_dcs))
        reachable = _reachable_tags(origin, routes)
    else:
        # joins/independent: the filter applies natively to whatever shares its
        # data collection, which is what the components bind to.
        reachable = frozenset({origin, *bindable_tags(cell)})
    return [
        FilterPlan(
            dc_tag=origin,
            column="species",
            values=_SPECIES_ROUNDS,
            hops=1 if cell.connect is ConnectMode.LINKS_ADVERSARIAL else 0,
            label=cell.connect.value,
            sequential_value=("Gentoo", "Chinstrap"),
            reachable_tags=reachable,
        )
    ]


def write_configs(
    cell: Cell,
    dataset_dir: str | Path,
    out_dir: str | Path,
    n_samples: int | None = None,
) -> GeneratedConfigs:
    """Build + write both YAML files, returning their paths and key identifiers."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    project = build_project(cell, dataset_dir, n_samples)
    dashboard = build_dashboard(cell, project)

    project_path = out_dir / "project.yaml"
    dashboard_path = out_dir / "dashboard.yaml"
    project_path.write_text(yaml.safe_dump(project, sort_keys=False))
    dashboard_path.write_text(yaml.safe_dump(dashboard, sort_keys=False))

    return GeneratedConfigs(
        project_path=str(project_path),
        dashboard_path=str(dashboard_path),
        project_name=project["name"],
        workflow_name=project["workflows"][0]["name"],
        workflow_tag=f"{ENGINE_NAME}/{project['workflows'][0]['name']}",
        project_id=project["id"],
        bindable_dc_tags=bindable_tags(cell),
    )


@dataclass
class GeneratedIngestConfig:
    project_path: str
    project_name: str
    project_id: str
    # For IMAGES only: where the runner should ``depictio images push`` the PNGs
    # (must equal the DC's s3_base_folder so the DC resolves them at render time).
    s3_base_folder: str | None = None


def write_ingest_config(
    cell: IngestCell,
    dataset_dir: str | Path,
    out_dir: str | Path,
    *,
    s3_bucket: str = "depictio-bucket",
    metadata_csv: str | None = None,
    images_dir: str | None = None,
    run_tag: str = "",
) -> GeneratedIngestConfig:
    """Build + write the ingestion ``project.yaml`` for one cell.

    Pass a distinct ``run_tag`` per benchmark invocation to ingest into a fresh
    project — see :func:`build_ingest_project` on why sharing one accumulates
    rows across runs.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    project = build_ingest_project(
        cell,
        dataset_dir,
        s3_bucket=s3_bucket,
        metadata_csv=metadata_csv,
        images_dir=images_dir,
        run_tag=run_tag,
    )
    project_path = out_dir / "project.yaml"
    project_path.write_text(yaml.safe_dump(project, sort_keys=False))

    s3_base_folder = None
    if cell.kind is DCKind.IMAGES:
        dc = project["workflows"][0]["data_collections"][0]
        s3_base_folder = dc["config"]["dc_specific_properties"]["s3_base_folder"]

    return GeneratedIngestConfig(
        project_path=str(project_path),
        project_name=project["name"],
        project_id=project["id"],
        s3_base_folder=s3_base_folder,
    )
