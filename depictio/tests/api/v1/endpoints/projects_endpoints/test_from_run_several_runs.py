# ruff: noqa: F811 - the fixtures imported from test_from_run are parameters here
"""A folder holding several runs of one pipeline, read as one project.

``folder_inspect`` names the sub-folders that are runs (``child_runs``) when the
folder itself is not one. ``POST /projects/from_run`` with ``runs`` previews and
creates the project from the first of them, then records the others on its
workflows the way ``attach_run`` does, before the one ingestion that reads them
all is dispatched: no second ingestion races the first on the same tables.
"""

from __future__ import annotations

import os
import shutil

import pytest
from bson import ObjectId
from pydantic import ValidationError

from depictio.api.v1.endpoints.projects_endpoints import from_run, run_folders
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import CodedHTTPException
from depictio.cli.cli.utils.template_preview import (
    DataCollectionPreview,
    RecipePreview,
    RecipeSourcePreview,
)
from depictio.project_builder.overlay import TemplateEdits
from depictio.tests.cli.s3_stubs import MEGATEST_TREE, S3_ROOT, write_tree

from .test_from_run import (  # noqa: F401 - fixtures
    TEMPLATE_ID,
    _ampliseq_info,
    _call,
    _detects,
    _dispatched_payloads,
    _request,
    _rows,
    _run_from_folder,
    _user,
    _verdicts,
    allowlisted_bucket,
    mock_db,
    no_bucket_lists,
    server_context,
)
from .test_from_run_template_edits import _additions

# The megatest tree with the versions file that names the pipeline, as a run of it writes.
RUN_TREE = MEGATEST_TREE | {
    "pipeline_info/nf_core_ampliseq_software_mqc_versions.yml": (
        b"Workflow:\n  Nextflow: 25.04.0\n  nf-core/ampliseq: 2.16.0\n"
    )
}
NO_TREE = {
    rel: body for rel, body in RUN_TREE.items() if rel != "qiime2/phylogenetic_tree/tree.nwk"
}
NO_MULTIQC = {rel: body for rel, body in RUN_TREE.items() if not rel.startswith("multiqc/")}


@pytest.fixture()
def two_runs(tmp_path, monkeypatch):
    """Local folders on; ``home/runs`` holds two megatest runs and a plain folder."""
    home = tmp_path / "home"
    write_tree(home / "runs" / "run_a", RUN_TREE)
    write_tree(home / "runs" / "run_b", RUN_TREE)
    (home / "runs" / "notes").mkdir()
    (home / "depictio-local").mkdir()
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(home))
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(home / "depictio-local"))
    return home / "runs"


def _local(**extra):
    return {"request": _request(), "user": _user(is_admin=True), **extra}


def test_a_folder_of_runs_names_them(two_runs):
    inspection = run_folders.inspect_folder(
        str(two_runs), request=_request(), current_user=_user(is_admin=True)
    )
    assert inspection.looks_like_run is False
    assert inspection.child_runs == ["run_a", "run_b"]


def test_a_run_names_no_child_runs(two_runs):
    inspection = run_folders.inspect_folder(
        str(two_runs / "run_a"), request=_request(), current_user=_user(is_admin=True)
    )
    assert inspection.looks_like_run is True
    assert inspection.child_runs == []


def test_the_preview_reads_the_first_run_and_names_them_all(mock_db, two_runs):
    report = _call(data_root=str(two_runs), dry_run=True, runs=["run_a", "run_b"], **_local())
    single = _call(data_root=str(two_runs / "run_a"), dry_run=True, **_local())

    assert report.runs == ["run_a", "run_b"]
    assert report.data_root == os.path.realpath(two_runs / "run_a")
    rows, alone = _rows(report), _rows(single)
    assert set(rows) == set(alone)
    for tag, row in rows.items():
        if row.kind == "scan" and (row.mode or "").lower() == "recursive":
            # The ingestion reads every run: the count says so.
            assert row.matched == 2 * alone[tag].matched, tag
        else:
            # A file, a URL or a recipe keeps the first run's.
            assert row.model_dump() == alone[tag].model_dump(), tag
    assert rows["multiqc_data"].matched == 2
    assert any("run_b/" in s for s in rows["multiqc_data"].samples)
    assert not any("run_b//" in s for s in rows["multiqc_data"].samples)
    assert mock_db["projects"].count_documents({}) == 0


def test_a_real_run_records_every_run_and_ingests_once(mock_db, two_runs):
    report, _user_, _importer, task = _run_from_folder(
        mock_db, data_root=str(two_runs), runs=["run_a", "run_b"], **_local()
    )
    assert report.project_id is not None and report.run_id is not None

    stored = mock_db["projects"].find_one({"_id": ObjectId(report.project_id)})
    (workflow,) = stored["workflows"]
    location = workflow["data_location"]
    run_a, run_b = (os.path.realpath(two_runs / name) for name in ("run_a", "run_b"))
    assert location["locations"] == [run_a, run_b]
    assert location["attached_locations"] == [run_b]
    # One ingestion, dispatched once, after both runs are recorded.
    assert len({p["run_id"] for p in _dispatched_payloads(task)}) == 1
    assert "multiqc_data" in {p["dc_tag"] for p in _dispatched_payloads(task)}
    # The run's steps count what every run holds.
    run_doc = mock_db["ingestion_runs"].find_one({"run_id": report.run_id})
    counts = {dc["tag"]: dc["file_count"] for dc in run_doc["data_collections"]}
    assert counts["multiqc_data"] == 2


@pytest.mark.parametrize(
    "runs", [["run_a"], ["run_a", "run_a"], ["../x", "run_a"], ["a/b", "run_a"]]
)
def test_runs_are_two_or_more_distinct_sub_folder_names(runs):
    with pytest.raises(ValidationError):
        from_run.FromRunRequest(data_root="/data/runs", runs=runs)


def test_a_run_that_is_not_there_is_refused(mock_db, two_runs):
    with pytest.raises(CodedHTTPException) as refused:
        _call(data_root=str(two_runs), dry_run=True, runs=["run_a", "run_z"], **_local())
    assert refused.value.status_code == 422


def test_several_runs_are_read_from_the_servers_disk_only(mock_db, allowlisted_bucket):
    with pytest.raises(CodedHTTPException) as refused:
        _call(data_root=S3_ROOT, dry_run=True, runs=["run_a", "run_b"])
    assert (refused.value.status_code, refused.value.code) == (422, "runs_need_local")


# ── the folder of runs is the project's origin ───────────────────────────────


def _runs_of(runs, run_a: dict[str, bytes], run_b: dict[str, bytes]) -> None:
    """The two runs of ``runs`` made of exactly these trees."""
    for name, tree in (("run_a", run_a), ("run_b", run_b)):
        shutil.rmtree(runs / name)
        write_tree(runs / name, tree)


def _stored(mock_db, report) -> dict:
    return mock_db["projects"].find_one({"_id": ObjectId(report.project_id)})


def _tags(stored: dict) -> set[str]:
    return {
        dc["data_collection_tag"] for wf in stored["workflows"] for dc in wf["data_collections"]
    }


def test_the_origin_is_the_folder_of_runs_with_their_names(mock_db, two_runs):
    report, *_ = _run_from_folder(
        mock_db, data_root=str(two_runs), runs=["run_a", "run_b"], **_local()
    )
    origin = _stored(mock_db, report)["template_origin"]
    assert origin["data_root"] == os.path.realpath(two_runs)
    assert origin["runs"] == ["run_a", "run_b"]
    run_doc = mock_db["ingestion_runs"].find_one({"run_id": report.run_id})
    assert run_doc["data_root"] == os.path.realpath(two_runs)
    # What the first run found is still what the preview reports.
    assert report.data_root == os.path.realpath(two_runs / "run_a")


def test_a_single_run_keeps_its_folder_as_the_origin(mock_db, two_runs):
    report, *_ = _run_from_folder(mock_db, data_root=str(two_runs / "run_a"), **_local())
    origin = _stored(mock_db, report)["template_origin"]
    assert origin["data_root"] == os.path.realpath(two_runs / "run_a")
    assert origin["runs"] is None


def test_a_refresh_reads_every_run_as_the_creation_did(mock_db, two_runs):
    """A collection whose files exist in the second run only counted at creation;
    the Data refresh must count it too, not judge the first run alone."""
    _runs_of(two_runs, NO_MULTIQC, RUN_TREE)
    created, user, _importer, created_task = _run_from_folder(
        mock_db, data_root=str(two_runs), runs=["run_a", "run_b"], **_local()
    )
    assert _rows(created)["multiqc_data"].matched == 1
    assert _rows(created)["multiqc_data"].status == "ok"

    stored = _stored(mock_db, created)
    location, split = from_run._refresh_preflight(stored)
    assert location == os.path.realpath(two_runs)
    dispatched = {tag: matched for tag, _dc_id, _wf, matched in split.to_dispatch}
    assert dispatched["multiqc_data"] == 1

    from .test_from_run import _refresh

    refreshed, refresh_task = _refresh(mock_db, created.project_id, _local()["user"])
    assert _verdicts(mock_db, refreshed.run_id) == _verdicts(mock_db, created.run_id)
    assert sorted(p["dc_tag"] for p in _dispatched_payloads(refresh_task)) == sorted(
        p["dc_tag"] for p in _dispatched_payloads(created_task)
    )


def test_a_refresh_skips_a_run_that_has_gone(mock_db, two_runs):
    created, *_ = _run_from_folder(
        mock_db, data_root=str(two_runs), runs=["run_a", "run_b"], **_local()
    )
    shutil.rmtree(two_runs / "run_b")
    _location, split = from_run._refresh_preflight(_stored(mock_db, created))
    dispatched = {tag: matched for tag, _dc_id, _wf, matched in split.to_dispatch}
    assert dispatched["multiqc_data"] == 1


# ── pruning is a union across runs ───────────────────────────────────────────


def test_an_optional_collection_pruned_in_the_first_run_is_kept_when_another_has_it(
    mock_db, two_runs
):
    _runs_of(two_runs, NO_TREE, RUN_TREE)
    report, *_ = _run_from_folder(
        mock_db, data_root=str(two_runs), runs=["run_a", "run_b"], **_local()
    )
    tag = "phylogenetic_tree_canonical"
    assert report.pruned_optional_dcs == []
    assert _rows(report)[tag].status == "ok"

    stored = _stored(mock_db, report)
    assert tag in _tags(stored)
    (dc,) = [
        dc
        for wf in stored["workflows"]
        for dc in wf["data_collections"]
        if dc["data_collection_tag"] == tag
    ]
    # The definition is the run's that kept it.
    filename = dc["config"]["scan"]["scan_parameters"]["filename"]
    assert filename.startswith(os.path.realpath(two_runs / "run_b"))
    expected = {
        e["data_collection_tag"]: e for e in stored["template_origin"]["expected_data_collections"]
    }
    assert expected[tag]["included"] is True and expected[tag]["removal_reason"] is None
    # Judged where its file is: the refresh dispatches it rather than failing it.
    _location, split = from_run._refresh_preflight(stored)
    assert tag in {entry[0] for entry in split.to_dispatch}
    assert tag not in {entry[0] for entry in split.skipped + split.failed}


def test_an_optional_collection_pruned_in_every_run_stays_pruned(mock_db, two_runs):
    _runs_of(two_runs, NO_TREE, NO_TREE)
    report, *_ = _run_from_folder(
        mock_db, data_root=str(two_runs), runs=["run_a", "run_b"], **_local()
    )
    assert report.pruned_optional_dcs == ["phylogenetic_tree_canonical"]
    assert "phylogenetic_tree_canonical" not in _tags(_stored(mock_db, report))


def test_a_collection_kept_by_the_first_run_only_is_unchanged(mock_db, two_runs):
    _runs_of(two_runs, RUN_TREE, NO_TREE)
    report, *_ = _run_from_folder(
        mock_db, data_root=str(two_runs), runs=["run_a", "run_b"], **_local()
    )
    assert report.pruned_optional_dcs == []
    assert "phylogenetic_tree_canonical" in _tags(_stored(mock_db, report))


# ── the merged rows ──────────────────────────────────────────────────────────


def _scan(tag: str, matched: int, status: str, mode: str = "recursive", **extra):
    return DataCollectionPreview(
        tag=tag, kind="scan", mode=mode, location="/x", matched=matched, status=status, **extra
    )


def _recipe(tag: str, reads: list[str], present: set[str], optional: bool = False):
    """A recipe row as one run's preview made it: ``reads`` found only if in ``present``."""
    sources = [
        RecipeSourcePreview(
            ref=dc, kind="collection", dc_ref=dc, matched=int(dc in present), found=dc in present
        )
        for dc in reads
    ]
    absent = [dc for dc in reads if dc not in present]
    return DataCollectionPreview(
        tag=tag,
        kind="recipe",
        mode=None,
        location="/x",
        matched=len(reads) - len(absent),
        missing_sources=[f"collection '{dc}'" for dc in absent],
        missing_collections=absent,
        optional=optional,
        status="missing" if absent else "ok",
        recipe=RecipePreview(name=tag, sources=sources),
    )


def test_a_recipe_reading_a_collection_found_in_a_later_run_is_ok():
    run_a = [
        _scan("counts", 0, "empty"),
        _recipe("derived", ["counts"], present=set()),
        _recipe("report", ["derived"], present=set()),
    ]
    run_b = [
        _scan("counts", 2, "ok"),
        _recipe("derived", ["counts"], present={"counts"}),
        _recipe("report", ["derived"], present={"derived"}),
    ]
    merged = {row.tag: row for row in from_run._merge_run_rows([run_a, run_b], ["run_a", "run_b"])}
    assert merged["counts"].status == "ok" and merged["counts"].matched == 2
    for tag in ("derived", "report"):
        assert merged[tag].status == "ok", tag
        assert merged[tag].missing_sources == [] and merged[tag].missing_collections == []
        assert all(source.found for source in merged[tag].recipe.sources)
    assert merged["derived"].matched == 1
    # The preview rows of the runs themselves are not changed.
    assert run_a[1].status == "missing" and run_a[1].recipe.sources[0].found is False

    # So the creation and the refresh dispatch it rather than failing it.
    project = {
        "workflows": [
            {
                "data_collections": [
                    {"data_collection_tag": tag, "_id": tag}
                    for tag in ("counts", "derived", "report")
                ]
            }
        ]
    }
    split = from_run._preflight_split(project, list(merged.values()))
    assert {entry[0] for entry in split.to_dispatch} == {"counts", "derived", "report"}
    assert split.failed == [] and split.skipped == []


def test_a_recipe_that_still_misses_a_collection_stays_missing():
    run_a = [
        _scan("counts", 0, "empty"),
        _scan("other", 0, "empty"),
        _recipe("derived", ["counts", "other"], present=set()),
    ]
    run_b = [_scan("counts", 2, "ok"), _scan("other", 0, "empty")]
    (derived,) = [
        row
        for row in from_run._merge_run_rows([run_a, run_b], ["run_a", "run_b"])
        if row.tag == "derived"
    ]
    assert derived.status == "missing"
    assert derived.missing_collections == ["other"]
    assert derived.missing_sources == ["collection 'other'"]
    assert derived.matched == 1


def test_a_single_file_is_judged_by_the_run_that_holds_it():
    unseen = _scan("tree", 0, "ok", mode="single")  # outside this run's folder
    seen = _scan("tree", 1, "ok", mode="single")
    gone = _scan("tree", 0, "missing", mode="single")
    assert from_run._merge_run_rows([[unseen], [seen]], ["a", "b"])[0].matched == 1
    assert from_run._merge_run_rows([[seen], [unseen]], ["a", "b"])[0].matched == 1
    assert from_run._merge_run_rows([[gone], [unseen]], ["a", "b"])[0].status == "missing"


def test_a_pruned_row_gives_way_to_a_run_that_kept_the_collection():
    pruned = _scan("tree", 0, "pruned", mode=None, optional=True)
    kept = _scan("tree", 1, "ok", mode="single", optional=True)
    assert from_run._merge_run_rows([[pruned], [kept]], ["a", "b"])[0].status == "ok"
    assert from_run._merge_run_rows([[pruned], [pruned]], ["a", "b"])[0].status == "pruned"


# ── detection of a folder of runs ────────────────────────────────────────────


def test_a_folder_of_runs_reports_the_detection_of_its_first_run(two_runs, monkeypatch):
    seen = _detects(monkeypatch, TEMPLATE_ID, _ampliseq_info())
    inspection = run_folders.inspect_folder(
        str(two_runs), request=_request(), current_user=_user(is_admin=True)
    )
    assert inspection.looks_like_run is False
    assert inspection.child_runs == ["run_a", "run_b"]
    assert inspection.detected is not None
    assert (inspection.detected.template_id, inspection.detected.pipeline) == (
        TEMPLATE_ID,
        "nf-core/ampliseq",
    )
    assert inspection.run_info is not None and inspection.run_info.engine == "nextflow"
    assert [root.location for root in seen] == [os.path.realpath(two_runs / "run_a")]


def test_a_folder_with_one_run_in_it_is_read_as_itself(two_runs, monkeypatch):
    solo = two_runs.parent / "solo"
    write_tree(solo / "run_a", RUN_TREE)
    seen = _detects(monkeypatch, TEMPLATE_ID, _ampliseq_info())
    inspection = run_folders.inspect_folder(
        str(solo), request=_request(), current_user=_user(is_admin=True)
    )
    assert inspection.child_runs == ["run_a"]
    assert [root.location for root in seen] in ([], [os.path.realpath(solo)])


def test_detection_without_a_template_reads_the_first_run(mock_db, two_runs, monkeypatch):
    seen = _detects(monkeypatch, TEMPLATE_ID, _ampliseq_info())
    report = _call(
        data_root=str(two_runs), template_id=None, dry_run=True, runs=["run_b", "run_a"], **_local()
    )
    assert report.detected_template.template_id == TEMPLATE_ID
    assert [root.location for root in seen] == [os.path.realpath(two_runs / "run_b")]


# ── a template named in the request ──────────────────────────────────────────


def test_a_named_template_still_reports_what_the_runs_records_say(mock_db, two_runs):
    report = _call(data_root=str(two_runs), dry_run=True, runs=["run_a", "run_b"], **_local())
    assert report.template_id == TEMPLATE_ID
    assert report.run_info is not None and report.run_info.engine == "nextflow"
    detected = report.detected_template
    assert detected is not None
    assert (detected.pipeline, detected.engine) == ("nf-core/ampliseq", "nextflow")
    assert detected.version
    # The template is the one asked for, whatever the run says.
    assert detected.match in ("exact", "closest")


@pytest.mark.parametrize(
    ("template_id", "match", "named"),
    [
        ("nf-core/ampliseq/2.16.0", "exact", "nf-core/ampliseq/2.16.0"),
        ("nf-core/ampliseq/2.17.0", "closest", "nf-core/ampliseq/2.17.0"),
        ("nf-core/rnaseq/3.14.0", "none", None),
    ],
)
def test_a_run_is_described_against_the_template_named(template_id, match, named):
    detected = from_run.describe_run(template_id, _ampliseq_info())
    assert (detected.match, detected.template_id) == (match, named)
    assert (detected.pipeline, detected.version) == ("nf-core/ampliseq", "2.16.0")
    assert from_run.describe_run(template_id, None) is None


# ── what several runs cannot do ──────────────────────────────────────────────


def test_collections_added_in_the_builder_are_refused_with_several_runs(mock_db, two_runs):
    edits = TemplateEdits(additions=_additions())
    with pytest.raises(CodedHTTPException) as refused:
        _call(
            data_root=str(two_runs),
            dry_run=True,
            runs=["run_a", "run_b"],
            edits=edits,
            **_local(),
        )
    assert (refused.value.status_code, refused.value.code) == (422, "runs_with_additions")
    assert "create the project from one run" in refused.value.detail
    assert mock_db["projects"].count_documents({}) == 0


def test_edits_other_than_additions_are_read_across_runs(mock_db, two_runs):
    edits = TemplateEdits(remove=["metadata"])
    report = _call(
        data_root=str(two_runs), dry_run=True, runs=["run_a", "run_b"], edits=edits, **_local()
    )
    assert "metadata" not in _rows(report)
    assert _rows(report)["multiqc_data"].matched == 2


def test_a_template_without_a_scan_of_runs_cannot_take_several(mock_db, two_runs):
    edits = TemplateEdits(remove=["multiqc_data"])
    with pytest.raises(CodedHTTPException) as refused:
        _call(
            data_root=str(two_runs),
            dry_run=True,
            runs=["run_a", "run_b"],
            edits=edits,
            **_local(),
        )
    assert (refused.value.status_code, refused.value.code) == (422, "runs_not_supported")


# ── samples shared across runs ───────────────────────────────────────────────
# One MultiQC collection reads every run's report. A sample named in two of
# them would be merged into one, as an upload of several reports refuses
# (``validate_multiqc_reports_uniform``): the preview says so, a creation stops.


def _multiqc_samples(run_folder, samples):
    """The run's report names ``samples`` (as the stubbed reader below lists them)."""
    path = run_folder / "multiqc" / "multiqc_data" / "multiqc.parquet"
    path.write_bytes(("\n".join(samples)).encode())


# The real reader, kept before the stub below replaces it in every test.
_READ_SAMPLES = from_run._multiqc_samples_of


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (
            {"samples": ["S1", "S1 - First read: Adapter 1", "S1_1"], "canonical_samples": ["S1"]},
            {"S1"},
        ),
        ({"samples": ["S1", "S2"], "canonical_samples": []}, {"S1", "S2"}),
    ],
    ids=["canonical-ids", "names-without-canonical-ids"],
)
def test_a_report_names_its_canonical_samples(monkeypatch, metadata, expected):
    from depictio.cli.cli.utils import multiqc_processor

    monkeypatch.setattr(multiqc_processor, "extract_multiqc_metadata", lambda _path: metadata)
    assert _READ_SAMPLES(b"report") == expected


@pytest.fixture(autouse=True)
def _samples_from_the_stub(monkeypatch):
    """MultiQC's own reader needs a real report; the stub lists one name per line."""
    monkeypatch.setattr(from_run, "_SAMPLES_READ", {})
    monkeypatch.setattr(
        from_run,
        "_multiqc_samples_of",
        lambda data: set(data.decode(errors="replace").splitlines()) - {"PAR1"},
    )


def test_runs_with_distinct_samples_share_none(mock_db, two_runs):
    _multiqc_samples(two_runs / "run_a", ["S1", "S2"])
    _multiqc_samples(two_runs / "run_b", ["S3", "S4"])
    report = _call(data_root=str(two_runs), dry_run=True, runs=["run_a", "run_b"], **_local())
    assert report.shared_samples == []


def test_the_preview_names_the_samples_two_runs_share(mock_db, two_runs):
    _multiqc_samples(two_runs / "run_a", ["S1", "S2", "S3"])
    _multiqc_samples(two_runs / "run_b", ["S2", "S3", "S4"])
    report = _call(data_root=str(two_runs), dry_run=True, runs=["run_a", "run_b"], **_local())
    (shared,) = report.shared_samples
    assert shared.data_collection_tag == "multiqc_data"
    assert shared.runs == ["run_a", "run_b"]
    assert shared.count == 2
    assert shared.samples == ["S2", "S3"]


def test_a_creation_stops_on_samples_two_runs_share(mock_db, two_runs):
    _multiqc_samples(two_runs / "run_a", ["S1", "S2"])
    _multiqc_samples(two_runs / "run_b", ["S2"])
    with pytest.raises(CodedHTTPException) as exc:
        _call(data_root=str(two_runs), runs=["run_a", "run_b"], **_local())
    assert exc.value.status_code == 422
    assert exc.value.code == "runs_share_samples"
    assert "S2" in str(exc.value.detail)
    assert mock_db["projects"].count_documents({}) == 0


def test_a_single_run_is_not_checked_for_shared_samples(mock_db, two_runs):
    _multiqc_samples(two_runs / "run_a", ["S1", "S1"])
    report = _call(data_root=str(two_runs / "run_a"), dry_run=True, **_local())
    assert report.shared_samples == []
