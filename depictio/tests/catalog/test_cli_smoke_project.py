"""The CLI smoke project must stay runnable without a server to run it against.

`depictio/projects/test/catalog_cli_smoke/` exists to be ingested by
`depictio-cli run`, and everything that can go wrong in that ingest — a recipe's
input moving, a recipe's output schema changing, a collection the catalog stops
recognising — goes wrong silently until someone stands the stack up.

These tests do the same work offline: they execute every recipe against the
staged raw files, run the catalog matcher over the collections the way the
compose endpoint does, and hold the dashboard to what the catalog actually offers
for the collections it binds. What they cannot cover is the CLI itself (S3, delta
writes, the API sync) — that is what running the project is for.

Regenerate the staged raw files with:
    uv run python -m depictio.projects.test.catalog_cli_smoke.scripts.generate_fixtures
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import pytest
import yaml

from depictio.api.v1.endpoints.catalog_endpoints.routes import (
    _dc_match_inputs,
    _match_dc_to_catalog,
)
from depictio.models.components.advanced_viz.catalog import load_catalog_entries
from depictio.recipes import execute_recipe

PROJECT_DIR = Path(__file__).resolve().parents[2] / "projects" / "test" / "catalog_cli_smoke"
DATA_DIR = PROJECT_DIR / "run_1"

# The catalog output each collection is expected to be recognised as. Written out
# rather than derived: the point of the project is that these specific
# collections reach the picker, so a change here should be a deliberate edit.
EXPECTED_MATCHES = {
    "taxonomy_rel_abundance": "qiime2_rel_abundance",
    "bray_curtis_canonical": "qiime2_bray_curtis",
    "taxonomy_composition": "qiime2_taxonomy_composition",
    "variants_long": "ivar_variants_long",
    "pangolin_lineages": "pangolin_report",
    "mosdepth_amplicon_coverage": "mosdepth_amplicon_coverage",
}

# The one collection with no recipe is recognised from the path of the file the
# scan registers, so the matcher needs that path the way `files` would hold it.
SCANNED_FILES = {
    "mosdepth_amplicon_coverage": (
        DATA_DIR / "variants/bowtie2/mosdepth/amplicon/all_samples.mosdepth.coverage.tsv"
    ),
}

# bray_curtis reads another collection rather than a file, so its upstream has to
# be computed first and handed in — the same thing `depictio-cli run` does by
# reading the upstream's delta table.
DC_REF_UPSTREAM = {"bray_curtis_canonical": {"rel_abundance": "taxonomy_rel_abundance"}}


@pytest.fixture(scope="module")
def entries():
    return load_catalog_entries()


@pytest.fixture(scope="module")
def collections() -> dict[str, dict[str, Any]]:
    project = yaml.safe_load((PROJECT_DIR / "project.yaml").read_text())
    return {c["data_collection_tag"]: c for c in project["workflows"][0]["data_collections"]}


@pytest.fixture(scope="module")
def dashboard() -> dict[str, Any]:
    return yaml.safe_load((PROJECT_DIR / "dashboards" / "overview.yaml").read_text())


@pytest.fixture(scope="module")
def frames(collections) -> dict[str, pl.DataFrame]:
    """What each collection holds once the CLI has ingested it.

    Recipes are executed in declaration order because that is the order the CLI
    processes them in, which is what makes a `dc_ref` upstream available.
    """
    computed: dict[str, pl.DataFrame] = {}
    for tag, collection in collections.items():
        config = collection["config"]
        transform = config.get("transform")
        if not transform:
            scanned = SCANNED_FILES[tag]
            computed[tag] = pl.read_csv(scanned, separator="\t")
            continue
        extra = {ref: computed[upstream] for ref, upstream in DC_REF_UPSTREAM.get(tag, {}).items()}
        computed[tag] = execute_recipe(transform["recipe"], DATA_DIR, extra_sources=extra or None)
    return computed


def test_every_recipe_runs_on_the_staged_files(frames, collections) -> None:
    """Executing is the assertion: `execute_recipe` validates its own output schema."""
    assert set(frames) == set(collections)
    empty = sorted(tag for tag, frame in frames.items() if frame.is_empty())
    assert empty == [], f"collections that computed to nothing: {empty}"


def test_every_collection_is_recognised_by_the_catalog(entries, collections) -> None:
    """The picker's whole input is what the compose endpoint matches here."""
    matched = {}
    for tag, collection in collections.items():
        recipe, scan_mode, _ = _dc_match_inputs(collection["config"])
        hits = []
        if recipe:
            hits += _match_dc_to_catalog(entries, recipe=recipe)
        if scan_mode == "recursive":
            path = str(SCANNED_FILES[tag])
            hits += _match_dc_to_catalog(entries, basename=Path(path).name, full_path=path)
        matched[tag] = {hit["output_id"] for hit in hits}

    assert matched == {tag: {output} for tag, output in EXPECTED_MATCHES.items()}


def test_dashboard_only_draws_renders_the_catalog_offers(entries, dashboard) -> None:
    """A tile the picker would never offer means the board has drifted from the catalog."""
    outputs = {output.id: output for entry in entries for output in entry.outputs}
    problems = []
    for component in dashboard["components"]:
        tag = component["tag"]
        source = component.get("catalog_source")
        if not source:
            problems.append(f"{tag}: no catalog_source")
            continue
        output = outputs.get(source["outputId"])
        if output is None:
            problems.append(f"{tag}: unknown output {source['outputId']!r}")
            continue
        wanted = component["component_type"]
        variants = {
            (
                render.component,
                getattr(render, "kind", None) or getattr(render, "visu_type", None),
            )
            for render in output.renders_as or []
        }
        kind = component.get("viz_kind") or component.get("visu_type")
        if (wanted, kind) not in variants:
            problems.append(f"{tag}: {output.id} offers {sorted(variants)}, not {(wanted, kind)}")
    assert problems == [], "\n".join(problems)


def _bound_columns(component: dict[str, Any]) -> set[str]:
    """Every column name a component's config pins, whatever its type calls it."""
    if component["component_type"] == "card":
        return {component["column_name"]}
    if component["component_type"] == "figure":
        return {str(v) for v in component.get("dict_kwargs", {}).values()}
    if component["component_type"] == "advanced_viz":
        config = component.get("config", {})
        bound = {str(v) for key, v in config.items() if key.endswith("_col") and v}
        for key, value in config.items():
            if key.endswith("_cols") and isinstance(value, list):
                bound |= {str(v) for v in value}
        return bound
    return set()


def test_dashboard_binds_columns_the_data_has(dashboard, frames) -> None:
    """The one thing pass-2 validation would catch, minus the server it needs."""
    problems = []
    for component in dashboard["components"]:
        frame = frames.get(component["data_collection_tag"])
        if frame is None:
            problems.append(f"{component['tag']}: no such collection")
            continue
        missing = sorted(_bound_columns(component) - set(frame.columns))
        if missing:
            problems.append(f"{component['tag']}: {missing} not in {frame.columns}")
    assert problems == [], "\n".join(problems)
