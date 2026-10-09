"""What a preview row names besides its counts: the rule, the files, the recipe.

The run-folder dialog shows, for each data collection, what it looks for as
the template wrote it (``rule``), the first files it matched (``samples``, as
absolute locations) and, for a recipe collection, what each of the recipe's
sources found (``recipe``). The counts stay what they were: every match is
counted, only the names are capped at ``PREVIEW_SAMPLES``.
"""

from __future__ import annotations

from types import ModuleType

import pytest

import depictio.recipes as recipes_pkg
from depictio.cli.cli.utils.data_root import LocalDataRoot
from depictio.cli.cli.utils.template_preview import (
    PREVIEW_SAMPLES,
    RecipePreview,
    RecipeSourcePreview,
    _preview_recipe_dc,
    _preview_scan_dc,
)
from depictio.models.models.transforms import RecipeSource
from depictio.tests.cli.s3_stubs import S3_ROOT, s3_data_root, write_tree


@pytest.fixture(autouse=True)
def cli_context(monkeypatch):
    """The CLI, reading its own disk: no local-data policy confines the root."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS", raising=False)
    monkeypatch.delenv("DEPICTIO_AUTH_SINGLE_USER_MODE", raising=False)


def _recursive(pattern: str) -> dict:
    return {
        "scan": {"mode": "recursive", "scan_parameters": {"regex_config": {"pattern": pattern}}}
    }


def _single(filename: str) -> dict:
    return {"scan": {"mode": "single", "scan_parameters": {"filename": filename}}}


# ── scanning collections ─────────────────────────────────────────────────────


def test_a_recursive_scan_counts_every_match_and_names_the_first_five(tmp_path):
    names = [f"sample_{index}.counts.tsv" for index in range(7)]
    base = write_tree(
        tmp_path / "run",
        {**{f"counts/{name}": b"x\n" for name in names}, "counts/notes.txt": b"x\n"},
    )
    root = LocalDataRoot(str(base))

    row = _preview_scan_dc("counts", _recursive(r".*\.counts\.tsv"), root, [], False)

    assert (row.status, row.matched) == ("ok", 7)
    # The pattern as the template wrote it, not the regex the scan builds from it.
    assert row.rule == r".*\.counts\.tsv"
    assert row.samples == [str(base / "counts" / name) for name in sorted(names)[:PREVIEW_SAMPLES]]
    assert all(sample.startswith("/") for sample in row.samples)


def test_a_recursive_scan_names_its_samples_run_by_run(tmp_path):
    tree = {
        f"{run}/qc/{run}_{index}.csv": b"x\n" for run in ("run_1", "run_2") for index in (1, 2, 3)
    }
    base = write_tree(tmp_path / "runs", tree)
    root = LocalDataRoot(str(base))

    row = _preview_scan_dc("qc", _recursive(r".*\.csv"), root, ["run_1", "run_2"], False)

    assert row.matched == 6
    assert row.samples == [
        str(base / "run_1" / "qc" / "run_1_1.csv"),
        str(base / "run_1" / "qc" / "run_1_2.csv"),
        str(base / "run_1" / "qc" / "run_1_3.csv"),
        str(base / "run_2" / "qc" / "run_2_1.csv"),
        str(base / "run_2" / "qc" / "run_2_2.csv"),
    ]


def test_a_scan_that_matches_nothing_names_nothing(tmp_path):
    base = write_tree(tmp_path / "run", {"notes.txt": b"x\n"})
    row = _preview_scan_dc("counts", _recursive(r".*\.tsv"), LocalDataRoot(str(base)), [], False)
    assert (row.status, row.matched, row.samples, row.rule) == ("empty", 0, [], r".*\.tsv")


def test_a_single_file_names_its_one_location(tmp_path):
    base = write_tree(tmp_path / "run", {"input/samplesheet.csv": b"sample\nS1\n"})
    filename = str(base / "input" / "samplesheet.csv")

    row = _preview_scan_dc("samplesheet", _single(filename), LocalDataRoot(str(base)), [], False)

    assert (row.status, row.matched) == ("ok", 1)
    assert row.rule == filename
    assert row.samples == [filename]


def test_a_single_file_that_is_gone_names_no_sample(tmp_path):
    base = write_tree(tmp_path / "run", {"notes.txt": b"x\n"})
    filename = str(base / "input" / "samplesheet.csv")

    row = _preview_scan_dc("samplesheet", _single(filename), LocalDataRoot(str(base)), [], False)

    assert (row.status, row.rule, row.samples) == ("missing", filename, [])


def test_a_single_file_outside_the_root_keeps_its_rule(tmp_path):
    base = write_tree(tmp_path / "run", {"notes.txt": b"x\n"})
    url = "https://data.example.org/sheet.csv"
    row = _preview_scan_dc("sheet", _single(url), LocalDataRoot(str(base)), [], False)
    assert (row.status, row.matched, row.rule, row.samples) == ("ok", 0, url, [])


def test_an_s3_prefix_scan_names_s3_urls(monkeypatch):
    root = s3_data_root(
        monkeypatch, {f"tables/t{index}.csv": b"x\n" for index in range(6)} | {"README": b"x"}
    )
    dc_config = {
        "scan": {
            "mode": "s3_prefix",
            "scan_parameters": {"prefix": f"{S3_ROOT}/tables/", "pattern": "*.csv"},
        }
    }

    row = _preview_scan_dc("tables", dc_config, root, [], False)

    assert (row.matched, row.rule) == (6, "*.csv")
    assert row.samples == [f"{S3_ROOT}/tables/t{index}.csv" for index in range(5)]


def test_a_manifest_scan_names_its_manifest(tmp_path):
    url = "https://data.example.org/manifest.csv"
    dc_config = {"scan": {"mode": "manifest", "scan_parameters": {"manifest_url": url}}}
    row = _preview_scan_dc("files", dc_config, LocalDataRoot(str(tmp_path)), [], False)
    assert (row.rule, row.samples, row.recipe) == (url, [], None)


# ── recipe collections ───────────────────────────────────────────────────────


RECIPE = "vendor/pipe/summary.py"


def _install_recipe(monkeypatch, sources: list[RecipeSource], doc: str | None) -> None:
    module = ModuleType("fake_recipe", doc)
    module.SOURCES = sources  # type: ignore[attr-defined]
    monkeypatch.setattr(recipes_pkg, "load_recipe", lambda name, *args: module)


def _recipe_dc(**transform) -> dict:
    return {"source": "transformed", "transform": {"recipe": RECIPE, **transform}}


@pytest.fixture()
def run_folder(tmp_path):
    return write_tree(
        tmp_path / "run",
        {
            **{f"qiime2/diversity/d{index}.tsv": b"x\n" for index in range(6)},
            "input/samplesheet.csv": b"sample\nS1\n",
        },
    )


def test_a_recipe_row_names_each_source_and_what_it_found(monkeypatch, run_folder):
    _install_recipe(
        monkeypatch,
        [
            RecipeSource(ref="diversity", glob_pattern="qiime2/diversity/*.tsv", format="tsv"),
            RecipeSource(ref="metadata", dc_ref="metadata"),
            RecipeSource(ref="taxonomy", dc_ref="taxonomy", optional=True),
            RecipeSource(ref="extras", path="qiime2/extras.tsv", format="tsv", optional=True),
            RecipeSource(ref="remote", path="https://data.example.org/ref.tsv", format="tsv"),
        ],
        doc="\n    Summarise the diversity tables.\n\n    Longer text that is not shown.\n",
    )
    root = LocalDataRoot(str(run_folder))

    row = _preview_recipe_dc("summary", _recipe_dc(), root, False, frozenset({"metadata"}))

    # The counts and the verdict are what they always were.
    assert (row.status, row.matched, row.missing_sources) == ("ok", 7, [])
    assert row.rule is None
    assert row.recipe is not None
    assert (row.recipe.name, row.recipe.summary) == (RECIPE, "Summarise the diversity tables.")
    diversity, metadata, taxonomy, extras, remote = row.recipe.sources
    assert diversity == RecipeSourcePreview(
        ref="diversity",
        kind="file",
        pattern="qiime2/diversity/*.tsv",
        matched=6,
        samples=[str(run_folder / "qiime2" / "diversity" / f"d{index}.tsv") for index in range(5)],
        found=True,
    )
    assert metadata == RecipeSourcePreview(
        ref="metadata", kind="collection", dc_ref="metadata", matched=1, found=True
    )
    assert taxonomy == RecipeSourcePreview(
        ref="taxonomy", kind="collection", dc_ref="taxonomy", optional=True, found=False
    )
    assert extras == RecipeSourcePreview(
        ref="extras", kind="file", pattern="qiime2/extras.tsv", optional=True, found=False
    )
    assert remote == RecipeSourcePreview(
        ref="remote", kind="url", pattern="https://data.example.org/ref.tsv", found=None
    )


def test_a_recipe_source_is_described_as_its_override_binds_it(monkeypatch, run_folder):
    _install_recipe(
        monkeypatch,
        [RecipeSource(ref="samplesheet", path="samplesheet.csv")],
        doc="Read the samplesheet.",
    )
    sheet = str(run_folder / "input" / "samplesheet.csv")
    dc_config = _recipe_dc(source_overrides={"samplesheet": {"path": sheet}})

    row = _preview_recipe_dc("samplesheet", dc_config, LocalDataRoot(str(run_folder)), False)

    assert row.recipe is not None
    (source,) = row.recipe.sources
    assert (source.kind, source.pattern, source.matched, source.found) == ("file", sheet, 1, True)
    assert source.samples == [sheet]


def test_a_missing_required_source_is_described_and_still_missing(monkeypatch, run_folder):
    _install_recipe(
        monkeypatch,
        [
            RecipeSource(ref="faith", path="qiime2/alpha-rarefaction/faith_pd.csv"),
            RecipeSource(ref="rel", dc_ref="rel_abundance"),
        ],
        doc=None,
    )

    row = _preview_recipe_dc("alpha", _recipe_dc(), LocalDataRoot(str(run_folder)), False)

    assert row.status == "missing"
    assert row.missing_sources == [
        "qiime2/alpha-rarefaction/faith_pd.csv",
        "collection 'rel_abundance'",
    ]
    assert row.missing_collections == ["rel_abundance"]
    assert row.recipe is not None
    assert row.recipe.summary is None
    assert [(s.kind, s.found, s.samples) for s in row.recipe.sources] == [
        ("file", False, []),
        ("collection", False, []),
    ]


def test_a_recipe_found_on_s3_names_s3_urls(monkeypatch):
    root = s3_data_root(monkeypatch, {"qiime2/barplot/level-2.csv": b"x\n"})
    _install_recipe(
        monkeypatch,
        [RecipeSource(ref="barplot", glob_pattern="qiime2/barplot/level-*.csv")],
        doc="Barplot.",
    )

    row = _preview_recipe_dc("barplot", _recipe_dc(), root, False)

    assert row.recipe is not None
    assert row.recipe.sources[0].samples == [f"{S3_ROOT}/qiime2/barplot/level-2.csv"]


def test_a_recipe_that_names_no_module_is_described_empty(tmp_path):
    row = _preview_recipe_dc("x", {"source": "transformed"}, LocalDataRoot(str(tmp_path)), False)
    assert row.status == "empty"
    assert row.recipe == RecipePreview(name="", summary=None, sources=[])


def test_a_recipe_that_fails_to_load_is_described_by_name(monkeypatch, tmp_path):
    def _broken(name, *args):
        raise RuntimeError("syntax error in recipe")

    monkeypatch.setattr(recipes_pkg, "load_recipe", _broken)

    row = _preview_recipe_dc("x", _recipe_dc(), LocalDataRoot(str(tmp_path)), False)

    assert row.status == "empty"
    assert row.recipe == RecipePreview(name=RECIPE, summary=None, sources=[])
