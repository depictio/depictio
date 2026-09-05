"""Generate the catalog conformance project from the catalog itself.

    uv run python -m depictio.projects.init.catalog_conformance.scripts.generate_project

The project exists so the catalog e2e suite has a target that covers *every*
output the catalog declares, independently of the two nf-core reference
projects. Its whole point is that nothing in it is maintained per output: adding
a tool to `depictio/catalog/` and rerunning this script is the entire workflow.

Everything under the project directory except `dashboards/` is generated output
and should never be hand-edited — `depictio/tests/catalog/test_conformance_project.py`
fails when it drifts from the catalog.

Two lanes, chosen by the same rule the catalog already draws for itself
(`depictio/catalog/SCHEMA.md`, "schema ownership"):

* **recipe lane** — the output declares a `recipe`, so the recipe's schema owns
  the columns and the bundled fixture *is* that recipe's output. The collection
  declares `source: transformed` + the recipe string, and the fixture is copied
  to `{dc_tag}.tsv` at the project root, which is where the init resolver looks
  for a pre-computed seed. Compose recognises it by recipe equality.
* **raw lane** — no recipe, so the file the catalog's `find` block describes is
  itself the frame the renders bind to. The fixture is staged inside a fake run
  directory at a path derived from that `find` block, and the collection scans
  it recursively. Compose recognises it by `find.filename` / `find.path_glob`,
  and the scan puts a real document in `files_collection`, which is the only
  code path in compose that neither other lane reaches.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from depictio.dev_scripts.multiqc_reprocess import pin_creation_date
from depictio.models.components.advanced_viz.catalog import (
    CatalogEntry,
    CatalogOutput,
    load_catalog_entries,
    match_run_dir,
)

PROJECT_DIR = Path(__file__).resolve().parents[1]
PROJECT_NAME = "Catalog Conformance"
DATASET_NAME = "catalog_conformance"
WORKFLOW_NAME = "catalog_conformance"
# The project ships a `template.yaml`, not a `project.yaml`, and the difference
# matters: `create_reference_project` runs `resolve_template_for_init` only on a
# template. That resolver is what turns a `source: transformed` collection into a
# scan of its pre-computed `{dc_tag}.tsv` seed — without it every recipe
# collection is persisted with `scan: null` and never yields a delta table.
# `{DATA_ROOT}` is substituted by the same resolver with the in-container project
# path, so nothing here hardcodes /app.
DATA_ROOT = "{DATA_ROOT}"
RUN_DIR = "run_1"
# The collection that carries the synthetic MultiQC report. Not derived from an
# output id: one report backs all twelve MultiQC section outputs.
MULTIQC_TAG = "multiqc_report"


def static_id(*parts: str) -> str:
    """A stable 24-hex ObjectId derived from what it identifies.

    Every other reference dataset carries a hand-picked id table in
    `db_init_reference_datasets.STATIC_IDS`. That does not survive a project
    whose collections come and go with the catalog, so ids are derived instead:
    a new catalog output gets a new, stable id with nobody choosing it.
    """
    key = ":".join((DATASET_NAME, *parts))
    return hashlib.sha1(key.encode()).hexdigest()[:24]


# --------------------------------------------------------------------------
# Lanes
# --------------------------------------------------------------------------


def recipe_groups(entries: tuple[CatalogEntry, ...]) -> dict[str, list[CatalogOutput]]:
    """Recipe string → the outputs it backs, in catalog order.

    Grouped rather than one collection per output because compose matches on
    recipe *equality*: two outputs sharing a recipe are both offered on the one
    collection that declares it (pinned by `test_one_recipe_may_back_several_outputs`),
    so a collection each would only duplicate every offer.
    """
    groups: dict[str, list[CatalogOutput]] = {}
    for entry in entries:
        for output in entry.outputs:
            if output.recipe:
                groups.setdefault(output.recipe, []).append(output)
    return groups


def raw_outputs(entries: tuple[CatalogEntry, ...]) -> list[tuple[CatalogEntry, CatalogOutput]]:
    return [(e, o) for e in entries for o in e.outputs if not o.recipe]


def fixture_columns(output: CatalogOutput) -> set[str]:
    path = output.fixture_file()
    if path is None or not path.exists():
        return set()
    return set(pl.read_csv(path, separator="\t", n_rows=1).columns)


def pick_group_fixture(outputs: list[CatalogOutput]) -> CatalogOutput:
    """The output whose fixture backs a shared-recipe collection.

    One frame has to stand in for the group. Deterministic (lowest id) so the
    generated tree is stable, but checked rather than assumed: if the chosen
    fixture cannot satisfy every grouped output's bindings, the outputs do not
    actually share a frame and grouping them would produce offers that cannot
    render. Today `qiime2/stacked_taxonomy_canonical.py` is the only shared
    recipe and its two fixtures are schema-identical.
    """
    chosen = min(outputs, key=lambda o: o.id)
    available = fixture_columns(chosen)
    if not available:
        return chosen
    for output in outputs:
        bound: set[str] = set()
        for render in output.renders_as or []:
            bound |= render.bound_columns()
        missing = bound - available
        if missing:
            raise SystemExit(
                f"Recipe {output.recipe!r} backs outputs that do not share a frame: "
                f"{output.id} binds {sorted(missing)}, absent from {chosen.id}'s fixture. "
                "Give them separate collections, or reconcile the fixtures."
            )
    return chosen


# --------------------------------------------------------------------------
# Raw-lane path derivation
# --------------------------------------------------------------------------


def raw_relative_path(entry: CatalogEntry, output: CatalogOutput) -> str:
    """Where to stage a recipe-free output's fixture inside the run directory.

    Derived from the output's own `find` block so the staged tree is whatever
    the catalog says the tool writes: a `path_glob` keeps its directory shape
    with the leading `**` dropped, a bare `filename` is placed under the tool's
    own folder. Any `*` left over is filled with a sample name, since a glob
    cannot be a path.
    """
    find = output.find
    if find.path_glob:
        parts = [p for p in find.path_glob.split("/") if p not in ("", "**")]
    elif find.filename:
        parts = [entry.id, find.filename]
    else:  # unreachable: CatalogFind requires at least one clause
        raise SystemExit(f"{output.id}: no find clause to derive a path from")
    parts[-1] = parts[-1].replace("*", "sample_01")
    return "/".join(parts)


def multiqc_report_path(entries: tuple[CatalogEntry, ...]) -> str:
    """Where the MultiQC report is staged, or "" when the catalog has none."""
    for entry, output in raw_outputs(entries):
        if entry.id == "multiqc":
            return raw_relative_path(entry, output)
    return ""


def scan_pattern(relative_path: str) -> str:
    """A recursive-scan regex matching exactly one staged file."""
    import re

    return re.escape(relative_path)


# --------------------------------------------------------------------------
# The synthetic MultiQC report
# --------------------------------------------------------------------------


def parquet_modules(parquet: Path) -> set[str]:
    """The MultiQC module anchors a report carries.

    Read straight off the parquet so "which sections does this report have" can
    be answered without a MultiQC run — used both to skip a needless rebuild and
    by the drift test.
    """
    if not parquet.exists():
        return set()
    frame = pl.read_parquet(parquet, columns=["modules"])
    found: set[str] = set()
    for raw in frame["modules"].drop_nulls().to_list():
        # A JSON list of module descriptors; `anchor` is what `multiqc.list_modules()`
        # returns and therefore what ingestion persists and compose compares against.
        for module in json.loads(raw) if isinstance(raw, str) else raw:
            anchor = module.get("anchor") if isinstance(module, dict) else module
            if anchor:
                found.add(str(anchor))
    return found


def normalise_anchor(anchor: str) -> str:
    """An anchor reduced to the module it belongs to.

    The same normalisation the compose endpoint applies before comparing an
    anchor to a catalog `section`: a module that ran more than once is anchored
    per run (`samtools_bowtie2`), while the catalog names the module itself.
    """
    return anchor.lower().replace("-", "_").split("_")[0]


def report_covers(parquet: Path, sections: list[str]) -> bool:
    """Does the committed report already carry exactly these sections?

    Rebuilding is skipped when it does. MultiQC embeds a run timestamp and an
    order-unstable copy of its own config inside the parquet, so an unnecessary
    rerun would rewrite 70 KB for no change in content — and the common reason
    to regenerate this project is a new *table* output, which does not touch the
    report at all.
    """
    present = {normalise_anchor(a) for a in parquet_modules(parquet)}
    return bool(present) and all(section in present for section in sections)


def build_multiqc_report(sections: list[str], destination: Path) -> tuple[list[str], list[str]]:
    """Run MultiQC over stub logs and write the parquet. Returns (anchors, missing).

    Nothing in the repo can be reused here: the only two `multiqc.parquet` files
    belong to the reference projects this one exists to be independent of, and
    viralrecon's is 24 MB. Synthesising one costs ~70 KB and makes the section
    filter (`_multiqc_sections` in the compose endpoint) meaningful, because the
    report genuinely carries only the modules the stubs produced.
    """
    import multiqc
    from multiqc.core.update_config import ClConfig

    from depictio.projects.init.catalog_conformance.scripts import multiqc_stubs

    if report_covers(destination, sections):
        anchors = sorted(parquet_modules(destination))
        return anchors, []

    # A fixed path, not mkdtemp: MultiQC bakes the absolute path of every input
    # file into the report's `data_sources` and `config` columns, so a random
    # temp directory would put one developer's machine into a committed artifact
    # and change 70 KB of it on every rerun.
    inputs = Path("/tmp/depictio-catalog-conformance-multiqc/in")
    outputs = Path("/tmp/depictio-catalog-conformance-multiqc/out")
    shutil.rmtree(inputs.parent, ignore_errors=True)
    inputs.mkdir(parents=True)
    outputs.mkdir(parents=True)
    try:
        for relative, content in multiqc_stubs.build_inputs(sections).items():
            path = inputs / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

        multiqc.reset()
        multiqc.run(
            str(inputs),
            cfg=ClConfig(
                output_dir=str(outputs),
                force=True,
                quiet=True,
                make_report=False,
                no_megaqc_upload=True,
            ),
        )
        anchors = sorted(multiqc.list_modules())
        parquet = outputs / "multiqc_data" / "multiqc.parquet"
        if not parquet.exists():
            raise SystemExit("MultiQC produced no parquet — cannot build the report collection")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(parquet, destination)
        pin_creation_date(destination)
    finally:
        shutil.rmtree(inputs.parent, ignore_errors=True)

    # Compose normalises an anchor to its leading `[-_]` token before comparing
    # it to a catalog `section` (a module that ran twice is anchored per run).
    # Mirror that here so "did the section land" is asked the same way.
    present = {anchor.lower().replace("-", "_").split("_")[0] for anchor in anchors}
    missing = [section for section in sections if section not in present]
    return anchors, missing


def multiqc_plots(anchors: list[str], parquet: Path) -> dict[str, list[str]]:
    """Plot names per anchor, for the collection's `dc_specific_properties`.

    Always read the registry back from the parquet the collection points at.
    `build_multiqc_report` skips MultiQC when the committed parquet already
    covers every section, and on that path the in-memory registry is empty, so
    asking `list_plots()` directly would silently collapse `plots:` to `{}`.
    """
    import multiqc

    multiqc.reset()
    multiqc.parse_logs(str(parquet))
    plots: dict[str, list[str]] = {}
    for anchor, names in (multiqc.list_plots() or {}).items():
        flat = [n if isinstance(n, str) else next(iter(n)) for n in names]
        if flat:
            plots[anchor] = flat
    return {a: plots[a] for a in anchors if a in plots}


# --------------------------------------------------------------------------
# Collection builders
# --------------------------------------------------------------------------


def table_properties(output: CatalogOutput) -> dict[str, Any]:
    """Read options plus whatever column documentation the catalog already has.

    Only columns the output declares are described. Inventing a line per column
    would bury the real documentation, and one of these frames is a coverage
    matrix with a hundred amplicon columns.
    """
    properties: dict[str, Any] = {
        "format": "TSV",
        "polars_kwargs": {"separator": "\t"},
    }
    if output.columns:
        properties["columns_description"] = {k: str(v) for k, v in output.columns.items()}
    return properties


def recipe_collection(
    recipe: str, outputs: list[CatalogOutput], fixture_source: CatalogOutput
) -> dict:
    tag = fixture_source.id
    names = ", ".join(o.name or o.id for o in outputs)
    return {
        "id": static_id("dc", tag),
        "data_collection_tag": tag,
        "description": f"{names} — recipe output ({recipe}), seeded from the catalog fixture",
        "config": {
            "type": "Table",
            "metatype": "Aggregate",
            "source": "transformed",
            "transform": {"recipe": recipe},
            "dc_specific_properties": table_properties(fixture_source),
        },
    }


def raw_table_collection(entry: CatalogEntry, output: CatalogOutput, relative: str) -> dict:
    return {
        "id": static_id("dc", output.id),
        "data_collection_tag": output.id,
        "description": f"{output.name or output.id} — raw {entry.name} output, recognised by find",
        "config": {
            "type": "Table",
            "metatype": "Aggregate",
            "scan": {
                "mode": "recursive",
                "scan_parameters": {"regex_config": {"pattern": scan_pattern(relative)}},
            },
            "dc_specific_properties": table_properties(output),
        },
    }


def multiqc_collection(relative: str, anchors: list[str], plots: dict[str, list[str]]) -> dict:
    return {
        "id": static_id("dc", MULTIQC_TAG),
        "data_collection_tag": MULTIQC_TAG,
        "description": "Synthetic MultiQC report carrying every section the catalog declares",
        "config": {
            "type": "MultiQC",
            "scan": {
                "mode": "recursive",
                "scan_parameters": {"regex_config": {"pattern": scan_pattern(relative)}},
            },
            "dc_specific_properties": {
                "s3_location": None,
                "modules": anchors,
                "plots": plots,
            },
        },
    }


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------

HEADER = """\
# GENERATED FILE — do not edit by hand.
#
# Rebuild with:
#   uv run python -m depictio.projects.init.catalog_conformance.scripts.generate_project
#
# A template rather than a plain project config: only a template.yaml goes
# through `resolve_template_for_init`, which is what converts each recipe
# collection below into a scan of its bundled {dc_tag}.tsv seed.
#
# Every data collection below is derived from depictio/catalog/: one per distinct
# recipe, one per recipe-free output, plus a single synthetic MultiQC report that
# backs all of that tool's section outputs. Adding a catalog output and rerunning
# the generator is the whole procedure for extending this project.
"""


def clean_generated(keep: Path) -> None:
    """Drop previously generated data so a removed output leaves no orphan.

    `keep` (the MultiQC report) survives: rebuilding it is both slow and
    diff-noisy, and `build_multiqc_report` decides on its own whether the
    committed one still carries the sections the catalog asks for.
    """
    for stale in PROJECT_DIR.glob("*.tsv"):
        stale.unlink()
    run_root = PROJECT_DIR / RUN_DIR
    for path in sorted(run_root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_file() and path != keep:
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def generate() -> None:
    entries = load_catalog_entries()
    # Derived before cleaning: the report is the one generated file worth keeping.
    multiqc_report = PROJECT_DIR / RUN_DIR / multiqc_report_path(entries)
    clean_generated(multiqc_report)

    collections: list[dict] = []
    lanes: dict[str, str] = {}

    # --- recipe lane ---------------------------------------------------
    for recipe, outputs in sorted(recipe_groups(entries).items()):
        source = pick_group_fixture(outputs)
        fixture = source.fixture_file()
        if fixture is None or not fixture.exists():
            raise SystemExit(f"{source.id}: declares recipe {recipe!r} but has no readable fixture")
        shutil.copyfile(fixture, PROJECT_DIR / f"{source.id}.tsv")
        collections.append(recipe_collection(recipe, outputs, source))
        for output in outputs:
            lanes[output.id] = "recipe"

    # --- raw lane ------------------------------------------------------
    run_root = PROJECT_DIR / RUN_DIR
    multiqc_sections: list[str] = []
    multiqc_relative = ""
    staged: dict[str, str] = {}

    for entry, output in raw_outputs(entries):
        relative = raw_relative_path(entry, output)
        if entry.id == "multiqc":
            # All twelve section outputs share one report and one collection.
            multiqc_relative = relative
            multiqc_sections.extend(
                r.section for r in (output.renders_as or []) if getattr(r, "section", None)
            )
            lanes[output.id] = "raw"
            continue
        fixture = output.fixture_file()
        if fixture is None or not fixture.exists():
            raise SystemExit(f"{output.id}: recipe-free but has no readable fixture to stage")
        target = run_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture, target)
        staged[output.id] = relative
        collections.append(raw_table_collection(entry, output, relative))
        lanes[output.id] = "raw"

    exemptions: list[str] = []
    if multiqc_sections:
        sections = sorted(set(multiqc_sections))
        parquet = run_root / multiqc_relative
        anchors, missing = build_multiqc_report(sections, parquet)
        collections.append(
            multiqc_collection(multiqc_relative, anchors, multiqc_plots(anchors, parquet))
        )
        # A section MultiQC could not be made to emit is recorded by name. The
        # coverage spec reads this list, so a gap stays visible instead of
        # quietly shrinking what the suite claims to cover.
        by_section = {
            r.section: o.id
            for e in entries
            if e.id == "multiqc"
            for o in e.outputs
            for r in (o.renders_as or [])
            if getattr(r, "section", None)
        }
        exemptions = sorted(by_section[s] for s in missing if s in by_section)

    verify_raw_lane(entries, run_root, staged)

    write_project(collections)
    write_static_ids(collections)
    write_manifest(entries, lanes, exemptions, staged)

    print(f"{len(collections)} collections covering {len(lanes)} catalog outputs")
    if exemptions:
        print(f"coverage exemptions: {', '.join(exemptions)}")


def verify_raw_lane(
    entries: tuple[CatalogEntry, ...], run_root: Path, staged: dict[str, str]
) -> None:
    """Every staged file must be recognised as exactly the output it stages.

    The raw lane's hazard is a staged path that several outputs' `find` patterns
    match: compose would offer all of them on the one collection, and every
    offer but one would bind to columns that frame does not have. Six qiime2
    outputs already share a single `rel-table-*` glob, so this is checked rather
    than assumed — a future recipe-free output that collides fails here, loudly,
    instead of surfacing as a broken tile in a much later e2e run.
    """
    found: dict[str, set[str]] = {}
    for match in match_run_dir(run_root):
        found.setdefault(match.path, set()).add(match.output_id)

    problems = []
    for output_id, relative in staged.items():
        matched = found.get(relative, set())
        if matched != {output_id}:
            problems.append(
                f"{relative}: expected to be recognised as {{{output_id}}}, got {matched or '{}'}"
            )
    if problems:
        raise SystemExit("Raw-lane staging is ambiguous:\n  " + "\n  ".join(problems))


def write_project(collections: list[dict]) -> None:
    project = {
        # Parsed and stripped before Project validation. Only DATA_ROOT is
        # declared: reference seeding supplies that one variable, and a template
        # variable left unresolved would silently prune the collections using it.
        "template": {
            "template_id": f"init/{DATASET_NAME}",
            "description": "Every catalog output, staged from the catalog's own fixtures",
            "version": "1.0.0",
            "variables": [
                {
                    "name": "DATA_ROOT",
                    "description": "Project directory holding the recipe seeds and the run tree",
                    "required": True,
                }
            ],
            "dashboards": ["dashboards/overview.yaml"],
        },
        "id": static_id("project"),
        "name": PROJECT_NAME,
        "project_type": "advanced",
        "is_public": True,
        "workflows": [
            {
                "id": static_id("workflow"),
                "name": WORKFLOW_NAME,
                "engine": {"name": "python", "version": "3.12"},
                "description": "Every catalog output, staged from the catalog's own fixtures",
                "data_location": {
                    "structure": "sequencing-runs",
                    "runs_regex": "run_.*",
                    "locations": [DATA_ROOT],
                },
                "data_collections": collections,
            }
        ],
    }
    body = yaml.safe_dump(project, sort_keys=False, width=100, allow_unicode=True)
    (PROJECT_DIR / "template.yaml").write_text(HEADER + "\n" + body)


def write_static_ids(collections: list[dict]) -> None:
    """The `STATIC_IDS` entry, as data rather than as a hand-edited dict.

    `db_init_reference_datasets` loads this at import time and
    `reseed_project.py` cascade-deletes by the same ids, so both stay correct
    across a regeneration without anyone touching Python.
    """
    payload = {
        "project": static_id("project"),
        "workflows": {WORKFLOW_NAME: static_id("workflow")},
        "data_collections": {c["data_collection_tag"]: c["id"] for c in collections},
        "dashboards": {"catalog_conformance_overview": static_id("dashboard", "overview")},
    }
    (PROJECT_DIR / "static_ids.json").write_text(json.dumps(payload, indent=2) + "\n")


def write_manifest(
    entries: tuple[CatalogEntry, ...],
    lanes: dict[str, str],
    exemptions: list[str],
    staged: dict[str, str],
) -> None:
    """What the project claims to cover, for the e2e coverage spec to check against."""
    all_outputs = sorted(o.id for e in entries for o in e.outputs)
    uncovered = [o for o in all_outputs if o not in lanes]
    if uncovered:
        raise SystemExit(f"Outputs assigned to no lane: {uncovered}")
    payload = {
        "generated_from": "depictio/catalog",
        "project_id": static_id("project"),
        "outputs": all_outputs,
        "lanes": dict(sorted(lanes.items())),
        "staged_raw_files": dict(sorted(staged.items())),
        "coverage_exemptions": exemptions,
    }
    (PROJECT_DIR / "manifest.json").write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    generate()
