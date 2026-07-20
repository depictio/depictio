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
  - ``links``       -> one ``links:`` entry from dc_0 to each dc_i, plus a couple
    of ``interactive`` components on dc_0 so cross-filter actually fires.
  - ``independent`` -> components bind round-robin across the raw DCs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from benchmark.datagen import COLUMN_DESCRIPTIONS
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
def _dc_block(tag: str, dc_id: str) -> dict:
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
                "columns_description": dict(COLUMN_DESCRIPTIONS),
            },
        },
    }


def build_project(cell: Cell, dataset_dir: str | Path) -> dict:
    """Build the project config dict for a cell."""
    slug = cell.slug
    project_name = f"Benchmark {slug}"
    workflow_name = f"{slug}_wf"
    project_id = static_id("project", slug)
    workflow_id = static_id("workflow", slug)

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
    elif cell.connect is ConnectMode.LINKS:
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
) -> dict:
    """Build a minimal ingestion project for one :class:`IngestCell`.

    TABLE reuses the recursive ``run_*`` CSV scan; MULTIQC scans ``run_*`` for the
    staged parquet; IMAGES is a single-scan metadata table plus an ``image_column``
    whose ``s3_base_folder`` is where :func:`benchmark.runner` pushes the images.
    """
    slug = cell.slug
    project_name = f"Benchmark {slug}"
    workflow_name = f"{slug}_wf"
    resolved_dir = str(Path(dataset_dir).resolve())

    if cell.kind is DCKind.TABLE:
        dc_tags = [f"dc_{i}" for i in range(cell.n_dcs)]
        data_collections = [_dc_block(tag, static_id("dc", slug, tag)) for tag in dc_tags]
        data_location = {
            "structure": "sequencing-runs",
            "runs_regex": "run_*",
            "locations": [resolved_dir],
        }
    elif cell.kind is DCKind.MULTIQC:
        data_collections = [_multiqc_dc_block("multiqc_data", static_id("dc", slug, "multiqc"))]
        data_location = {
            "structure": "sequencing-runs",
            "runs_regex": "run_*",
            "locations": [resolved_dir],
        }
    else:  # IMAGES
        s3_base_folder = f"s3://{s3_bucket}/bench_images/{slug}/"
        data_collections = [
            _image_dc_block(
                "sample_images",
                static_id("dc", slug, "images"),
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
        "id": static_id("project", slug),
        "workflows": [
            {
                "name": workflow_name,
                "id": static_id("workflow", slug),
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
    return [f"dc_{i}" for i in range(cell.n_dcs)]


# ── dashboard.yaml ──────────────────────────────────────────────────────────
def _layout(index: int, w: int, h: int, per_row: int = 2) -> dict:
    """Simple flow layout on a 12-column grid."""
    col = index % per_row
    row = index // per_row
    return {"x": col * (12 // per_row), "y": row * h, "w": w, "h": h}


def _figure_kwargs(visu_type: str) -> dict:
    return {
        "scatter": {"x": "bill_length_mm", "y": "body_mass_g", "color": "species"},
        "bar": {"x": "species", "y": "body_mass_g"},
        "box": {"x": "species", "y": "bill_length_mm", "color": "sex"},
        "histogram": {"x": "body_mass_g"},
    }.get(visu_type, {"x": "bill_length_mm", "y": "body_mass_g"})


def _advanced_viz_config(viz_kind: str) -> dict:
    if viz_kind == "volcano":
        return {
            "viz_kind": "volcano",
            "feature_id_col": "individual_id",
            "effect_size_col": "effect_size",
            "significance_col": "neg_log10_p",
            "significance_is_neg_log10": True,
        }
    if viz_kind == "ma":
        return {
            "viz_kind": "ma",
            "feature_id_col": "individual_id",
            "avg_log_intensity_col": "mean_expression",
            "log2_fold_change_col": "effect_size",
        }
    raise ValueError(f"Unsupported benchmark viz_kind {viz_kind!r}")


def build_dashboard(cell: Cell, project: dict) -> dict:
    """Build the dashboard (lite) config dict for a cell."""
    slug = cell.slug
    workflow_name = project["workflows"][0]["name"]
    workflow_tag = f"{ENGINE_NAME}/{workflow_name}"
    tags = bindable_tags(cell)

    components: list[dict] = []
    fig_i = av_i = 0
    for i in range(cell.n_components):
        visu = cell.visu[i % len(cell.visu)]
        dc_tag = tags[i % len(tags)]
        base = {"workflow_tag": workflow_tag, "data_collection_tag": dc_tag}

        if visu is VisuType.FIGURE:
            visu_type = FIGURE_VISU_ROTATION[fig_i % len(FIGURE_VISU_ROTATION)]
            fig_i += 1
            components.append(
                {
                    "tag": f"fig-{i}",
                    "component_type": "figure",
                    **base,
                    "visu_type": visu_type,
                    "dict_kwargs": _figure_kwargs(visu_type),
                    "title": f"Figure {i} ({visu_type})",
                    "layout": _layout(i, w=6, h=8),
                }
            )
        elif visu is VisuType.TABLE:
            components.append(
                {
                    "tag": f"tbl-{i}",
                    "component_type": "table",
                    **base,
                    "title": f"Table {i}",
                    "layout": _layout(i, w=6, h=8),
                }
            )
        elif visu is VisuType.ADVANCED_VIZ:
            viz_kind = ADVANCED_VIZ_ROTATION[av_i % len(ADVANCED_VIZ_ROTATION)]
            av_i += 1
            components.append(
                {
                    "tag": f"av-{i}",
                    "component_type": "advanced_viz",
                    **base,
                    "viz_kind": viz_kind,
                    "config": _advanced_viz_config(viz_kind),
                    "title": f"Advanced viz {i} ({viz_kind})",
                    "layout": _layout(i, w=6, h=8),
                }
            )

    # For links mode, add interactive filters on the source DC (dc_0) so that
    # cross-filtering actually exercises the link-resolution path at render time.
    if cell.connect is ConnectMode.LINKS:
        source = "dc_0"
        components.append(
            {
                "tag": "filter-species",
                "component_type": "interactive",
                "workflow_tag": workflow_tag,
                "data_collection_tag": source,
                "interactive_component_type": "MultiSelect",
                "column_name": "species",
                "column_type": "object",
                "title": "Species",
                "layout": {"x": 0, "y": 0, "w": 1, "h": 3},
            }
        )
        components.append(
            {
                "tag": "filter-body-mass",
                "component_type": "interactive",
                "workflow_tag": workflow_tag,
                "data_collection_tag": source,
                "interactive_component_type": "RangeSlider",
                "column_name": "body_mass_g",
                "column_type": "int64",
                "title": "Body mass",
                "layout": {"x": 0, "y": 3, "w": 1, "h": 3},
            }
        )

    return {
        "version": 1,
        "title": f"Benchmark {slug}",
        "subtitle": (
            f"size={cell.size} components={cell.n_components} "
            f"dcs={cell.n_dcs} connect={cell.connect.value}"
        ),
        "project_tag": project["name"],
        "components": components,
    }


def write_configs(cell: Cell, dataset_dir: str | Path, out_dir: str | Path) -> GeneratedConfigs:
    """Build + write both YAML files, returning their paths and key identifiers."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    project = build_project(cell, dataset_dir)
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
) -> GeneratedIngestConfig:
    """Build + write the ingestion ``project.yaml`` for one cell."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    project = build_ingest_project(
        cell, dataset_dir, s3_bucket=s3_bucket, metadata_csv=metadata_csv, images_dir=images_dir
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
