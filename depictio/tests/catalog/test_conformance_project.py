"""The catalog conformance project must stay in step with the catalog.

`depictio/projects/init/catalog_conformance/` is generated output, and the whole
point of generating it is that a newly authored catalog module lands in the e2e
suite without anyone editing the project. These tests are what makes that a
promise rather than a hope: they fail when the catalog has moved and the
generator has not been rerun.

Rebuild with:
    uv run python -m depictio.projects.init.catalog_conformance.scripts.generate_project
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from depictio.models.components.advanced_viz.catalog import load_catalog_entries, match_run_dir
from depictio.projects.init.catalog_conformance.scripts.generate_project import (
    MULTIQC_TAG,
    PROJECT_DIR,
    RUN_DIR,
    normalise_anchor,
    parquet_modules,
    raw_outputs,
    raw_relative_path,
    recipe_groups,
    static_id,
)

REGENERATE = (
    "Rerun: uv run python -m depictio.projects.init.catalog_conformance.scripts.generate_project"
)


@pytest.fixture(scope="module")
def entries():
    return load_catalog_entries()


@pytest.fixture(scope="module")
def project() -> dict:
    return yaml.safe_load((PROJECT_DIR / "template.yaml").read_text())


@pytest.fixture(scope="module")
def collections(project: dict) -> list[dict]:
    return project["workflows"][0]["data_collections"]


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((PROJECT_DIR / "manifest.json").read_text())


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_catalog_output_is_covered(entries, manifest) -> None:
    """No output may be left out — that silence is what this project removes."""
    declared = sorted(o.id for e in entries for o in e.outputs)
    assert manifest["outputs"] == declared, REGENERATE
    assert set(manifest["lanes"]) == set(declared), REGENERATE


def test_collections_match_the_catalog(entries, collections) -> None:
    """One collection per distinct recipe, per recipe-free output, plus the report."""
    expected = {min(outs, key=lambda o: o.id).id for outs in recipe_groups(entries).values()}
    expected |= {o.id for e, o in raw_outputs(entries) if e.id != "multiqc"}
    expected.add(MULTIQC_TAG)
    assert {c["data_collection_tag"] for c in collections} == expected, REGENERATE


def test_recipe_collections_carry_their_recipe(entries, collections) -> None:
    """Compose recognises these by recipe equality, so the string has to be exact."""
    declared = {
        c["config"].get("transform", {}).get("recipe")
        for c in collections
        if c["config"].get("source") == "transformed"
    }
    assert declared == set(recipe_groups(entries)), REGENERATE


def test_recipe_seeds_are_the_catalog_fixtures(entries) -> None:
    """The seed file must be the fixture itself, byte for byte.

    A copy is the one place this project can silently drift from the catalog:
    the render bindings are validated against the fixture, so a stale copy would
    mean the e2e suite renders something the catalog never checked.
    """
    stale = []
    for outputs in recipe_groups(entries).values():
        source = min(outputs, key=lambda o: o.id)
        fixture = source.fixture_file()
        seed = PROJECT_DIR / f"{source.id}.tsv"
        assert fixture is not None and fixture.exists(), f"{source.id}: no fixture"
        if not seed.exists():
            stale.append(f"{source.id}: no seed file")
        elif _digest(seed) != _digest(fixture):
            stale.append(f"{source.id}: seed differs from {fixture.name}")
    assert stale == [], f"{stale}\n{REGENERATE}"


def test_raw_files_are_staged_where_their_find_says(entries) -> None:
    stale = []
    for entry, output in raw_outputs(entries):
        if entry.id == "multiqc":
            continue
        staged = PROJECT_DIR / RUN_DIR / raw_relative_path(entry, output)
        fixture = output.fixture_file()
        assert fixture is not None and fixture.exists(), f"{output.id}: no fixture"
        if not staged.exists():
            stale.append(f"{output.id}: nothing staged at {staged.name}")
        elif _digest(staged) != _digest(fixture):
            stale.append(f"{output.id}: staged file differs from {fixture.name}")
    assert stale == [], f"{stale}\n{REGENERATE}"


def test_raw_staging_is_unambiguous(entries, manifest) -> None:
    """A staged path several outputs' patterns match would produce broken offers.

    Compose offers every output whose `find` matches, so one file recognised as
    two outputs means one of them binds to columns that frame does not have. Six
    qiime2 outputs already share a single `rel-table-*` glob, which is why this
    is checked rather than assumed.
    """
    found: dict[str, set[str]] = {}
    for match in match_run_dir(PROJECT_DIR / RUN_DIR, entries):
        found.setdefault(match.path, set()).add(match.output_id)

    problems = []
    for output_id, relative in manifest["staged_raw_files"].items():
        matched = found.get(relative, set())
        if matched != {output_id}:
            problems.append(
                f"{relative}: recognised as {matched or set()}, expected {{{output_id}}}"
            )
    assert problems == [], "\n".join(problems)


def test_file_matching_is_a_pure_function_of_the_tree(entries, tmp_path) -> None:
    """The same files must always yield the same catalog offers.

    File-driven matching (`find.filename` / `find.path_glob`) is a pure function
    of the paths present, so two projects holding the same run directory see the
    same catalog. This pins that.

    What it does *not* promise is one offer per file. Seven qiime2 outputs share
    `**/qiime2/rel_abundance_tables/rel-table-*.tsv` because each is a different
    reshape of that one raw table, so a project holding it is offered all seven
    and only the recipe signal tells them apart. That multiplicity is the reason
    the conformance project stages raw files only for recipe-free outputs, and
    the reason `verify_raw_lane` refuses an ambiguous staging.
    """
    table = tmp_path / "run_1" / "qiime2" / "rel_abundance_tables" / "rel-table-6.tsv"
    table.parent.mkdir(parents=True)
    table.write_text("sample\tPhylum\tabundance\n")
    root = tmp_path / "run_1"

    runs = [sorted(m.output_id for m in match_run_dir(root, entries)) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2], "matching is not deterministic"
    assert len(runs[0]) > 1, (
        "expected one raw rel-table to be claimed by several outputs; if this is "
        "now 1, the catalog changed and the raw-lane ambiguity guard can relax"
    )


def test_report_carries_every_declared_section(entries, manifest) -> None:
    """Checked on content, not bytes.

    MultiQC embeds a run timestamp and an order-unstable copy of its own config
    in the parquet, so byte equality would fail on a rebuild that changed
    nothing. What has to hold is that each section the catalog declares is
    actually in the report — anything the stubs could not produce is listed as a
    named exemption instead.
    """
    sections = {
        r.section
        for e in entries
        if e.id == "multiqc"
        for o in e.outputs
        for r in (o.renders_as or [])
        if getattr(r, "section", None)
    }
    parquet = PROJECT_DIR / RUN_DIR / "multiqc" / "multiqc_data" / "multiqc.parquet"
    assert parquet.exists(), f"no synthetic report — {REGENERATE}"

    present = {normalise_anchor(a) for a in parquet_modules(parquet)}
    exempt = {
        r.section
        for e in entries
        if e.id == "multiqc"
        for o in e.outputs
        if o.id in manifest["coverage_exemptions"]
        for r in (o.renders_as or [])
        if getattr(r, "section", None)
    }
    missing = sorted(sections - present - exempt)
    assert missing == [], (
        f"sections the report does not carry: {missing}. Either add a stub to "
        f"multiqc_stubs.STUB_BUILDERS, or {REGENERATE}"
    )


def test_static_ids_cover_every_collection(collections) -> None:
    """`reseed_project.py` cascade-deletes by these, so a gap orphans documents."""
    ids = json.loads((PROJECT_DIR / "static_ids.json").read_text())
    assert ids["data_collections"] == {c["data_collection_tag"]: c["id"] for c in collections}, (
        REGENERATE
    )
    assert ids["project"] == static_id("project")


def test_ids_are_derived_not_invented(collections) -> None:
    """Every id must be reproducible from what it identifies.

    This is what lets the project grow without a hand-maintained id table: a new
    collection gets a stable id nobody has to choose.
    """
    for collection in collections:
        assert collection["id"] == static_id("dc", collection["data_collection_tag"])
