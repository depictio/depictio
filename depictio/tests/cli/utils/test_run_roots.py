"""The runs a recipe and a single-file scan see (epic #1399)."""

from __future__ import annotations

from types import SimpleNamespace

import polars as pl

from depictio.cli.cli.utils.run_roots import (
    filter_frame_to_run,
    iter_run_roots,
    single_file_run_tag,
)


def _location(locations, structure="flat", runs_regex=None):
    return SimpleNamespace(locations=locations, structure=structure, runs_regex=runs_regex)


def test_flat_locations_are_one_run_each(tmp_path):
    athens = tmp_path / "run_athens"
    barcelona = tmp_path / "run_barcelona"
    athens.mkdir()
    barcelona.mkdir()
    runs = iter_run_roots(_location([str(athens), f"{barcelona}/"]))
    assert [r.tag for r in runs] == ["run_athens", "run_barcelona"]
    assert [r.location for r in runs] == [str(athens), f"{barcelona}/"]
    assert runs[0].root.location == str(athens)


def test_sequencing_runs_expand_every_location(tmp_path):
    first = tmp_path / "batch1"
    second = tmp_path / "batch2"
    for d in (first / "run_1", first / "run_2", first / "other", second / "run_3"):
        d.mkdir(parents=True)
    runs = iter_run_roots(_location([str(first), str(second)], "sequencing-runs", "run_.*"))
    assert [(r.tag, r.location) for r in runs] == [
        ("run_1", str(first)),
        ("run_2", str(first)),
        ("run_3", str(second)),
    ]
    assert runs[1].root.name == "run_2"


def test_sequencing_runs_location_without_run_folders_is_one_run(tmp_path):
    (tmp_path / "data").mkdir()
    runs = iter_run_roots(_location([str(tmp_path / "data")], "sequencing-runs", "run_.*"))
    assert [r.tag for r in runs] == ["data"]


def test_no_location_means_no_run():
    assert iter_run_roots(None) == []
    assert iter_run_roots(_location([])) == []


def test_single_file_tag_flat_is_the_location_run(tmp_path):
    loc = str(tmp_path / "run_athens")
    assert single_file_run_tag("metadata", f"{loc}/input/m.tsv", loc, "flat", None) == "run_athens"
    # A metadata file given with --var outside the run folder is still that run's.
    assert single_file_run_tag("metadata", "/elsewhere/m.tsv", loc, "flat", None) == "run_athens"


def test_single_file_tag_without_location_is_project_wide():
    assert single_file_run_tag("metadata", "/x/m.tsv", None, "flat", None) == (
        "metadata-single-file-scan"
    )


def test_single_file_tag_sequencing_runs(tmp_path):
    loc = tmp_path / "batch"
    (loc / "run_1").mkdir(parents=True)
    inside = str(loc / "run_1" / "samplesheet.csv")
    top = str(loc / "samplesheet.csv")
    args = (str(loc), "sequencing-runs", "run_.*")
    assert single_file_run_tag("samplesheet", inside, *args) == "run_1"
    assert single_file_run_tag("samplesheet", top, *args) == "samplesheet-single-file-scan"
    assert single_file_run_tag("samplesheet", "/elsewhere/s.csv", *args) == (
        "samplesheet-single-file-scan"
    )


def test_filter_keeps_this_run_and_project_wide_rows():
    df = pl.DataFrame(
        {
            "sample": ["a", "b", "c", "d"],
            "depictio_run_id": ["run_1", "run_2", "metadata-single-file-scan", None],
        }
    )
    out = filter_frame_to_run(df, "run_1", {"run_1", "run_2"})
    assert out["sample"].to_list() == ["a", "c", "d"]


def test_filter_single_run_and_missing_column_pass_whole():
    df = pl.DataFrame({"sample": ["a"], "depictio_run_id": ["run_1"]})
    assert filter_frame_to_run(df, "run_1", {"run_1"}).equals(df)
    bare = pl.DataFrame({"sample": ["a"]})
    assert filter_frame_to_run(bare, "run_1", {"run_1", "run_2"}).equals(bare)


def test_attach_scope_names_the_attached_runs_and_every_run(tmp_path):
    from types import SimpleNamespace

    from depictio.cli.cli.utils.run_roots import attach_scope

    athens, naples = tmp_path / "run_athens", tmp_path / "run_naples"
    athens.mkdir()
    naples.mkdir()
    wf = SimpleNamespace(
        data_location=SimpleNamespace(
            locations=[str(athens), str(naples)], structure="flat", runs_regex=None
        )
    )
    assert attach_scope(wf, None, {"attach_locations": [str(naples) + "/"]}) == (
        ["run_naples"],
        {"run_athens", "run_naples"},
    )
    assert attach_scope(wf, None, {}) is None
    assert attach_scope(None, None, {"attach_locations": [str(naples)]}) is None


def test_attached_run_tags_gathers_the_new_runs_of_every_workflow(tmp_path):
    """What the ingestion record names, so the Runs tab and the toast can tie
    a CLI --attach-run to its runs as they do an attach from the UI."""
    from depictio.cli.cli.utils.run_roots import attached_run_tags

    athens, naples = tmp_path / "run_athens", tmp_path / "run_naples"
    athens.mkdir()
    naples.mkdir()

    def wf(*locations):
        return SimpleNamespace(
            data_location=SimpleNamespace(
                locations=[str(p) for p in locations], structure="flat", runs_regex=None
            )
        )

    workflows = [wf(athens, naples), wf(athens, naples), wf(athens)]
    assert attached_run_tags(workflows, None, [str(naples)]) == ["run_naples"]
    assert attached_run_tags(workflows, None, []) == []
