"""A collection that can only be missing because an optional collection it reads is.

``POST /projects/from_run`` seeds a collection the preview found missing as an
already-terminal step: ``failed`` when the template requires it, ``skipped``
when it marks it optional (a route the run did not take). A required
collection whose own files are all there but which reads (``dc_ref``) such an
optional, absent collection cannot be built for that reason alone, so
``_dispatch_refresh_tasks`` skips it too, saying which collection it is
missing. One that misses a file of its own, or reads a collection that failed,
stays failed.

The decision is structural: from_run hands the dispatch the collections each
failure misses, from the preview rows' ``missing_collections``
(``from_run._missing_collections_only``). The step details are display only,
so rewording them changes nothing.
"""

from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.projects_endpoints import from_run, manifest_ingest
from depictio.cli.cli.utils.template_preview import DataCollectionPreview
from depictio.models.models.users import UserBase

OPTIONAL_PREFIX = "Skipped optional collection: "


def _row(
    tag: str,
    *,
    files=(),
    collections=(),
    optional: bool = False,
    location: str = "",
    labels=None,
) -> DataCollectionPreview:
    """The preview row of a collection that misses ``files`` of its own and the
    other ``collections``; ``labels`` is how those collections are shown."""
    shown = labels if labels is not None else [f"collection '{ref}'" for ref in collections]
    return DataCollectionPreview(
        tag=tag,
        kind="recipe",
        mode=None,
        location=location,
        matched=0,
        missing_sources=[*shown, *files],
        missing_collections=list(collections),
        optional=optional,
        status="missing",
    )


@pytest.fixture()
def db():
    from depictio.api.v1.monitoring import store as monitoring_store

    database = mongomock.MongoClient()["depictio_test"]
    with (
        patch.object(manifest_ingest, "projects_collection", database["projects"]),
        patch.object(monitoring_store, "ingestion_runs_collection", database["ingestion_runs"]),
        patch("depictio.api.v1.celery_tasks.manifest_refresh_dc_task"),
    ):
        yield database


def _dispatch(db, *rows: DataCollectionPreview, dispatched=()):
    """Seed the missing ``rows`` as from_run does and dispatch; returns the run's steps."""
    user = UserBase(id=ObjectId(), email="owner@example.com", is_admin=False)
    tags = [*(row.tag for row in rows), *dispatched]
    ids = {tag: str(ObjectId()) for tag in tags}
    project = {
        "_id": ObjectId(),
        "name": "run42",
        "permissions": {"owners": [{"_id": user.id}]},
        "workflows": [
            {"data_collections": [{"_id": ids[tag], "data_collection_tag": tag} for tag in tags]}
        ],
    }
    db["projects"].insert_one(project)
    run_id, _all_dispatched, results = manifest_ingest._dispatch_refresh_tasks(
        project_dict=project,
        to_dispatch=[(tag, ids[tag], 0, 1) for tag in dispatched],
        current_user=user,
        preflight_failed=[
            (row.tag, ids[row.tag], from_run._skip_reason(row)) for row in rows if not row.optional
        ],
        preflight_skipped=[
            (row.tag, ids[row.tag], f"{OPTIONAL_PREFIX}{from_run._skip_reason(row)}")
            for row in rows
            if row.optional
        ],
        missing_collections=from_run._missing_collections_only(rows),
        command="from_run",
    )
    run_doc = db["ingestion_runs"].find_one({"run_id": run_id})
    steps = {step["name"]: step for step in run_doc["steps"]}
    return SimpleNamespace(run_id=run_id, user=user, steps=steps, results=results)


def test_a_required_collection_reading_an_absent_optional_one_is_skipped(db):
    run = _dispatch(
        db,
        _row("ma_canonical", collections=["ancombc_results"]),
        _row("ancombc_results", files=["qiime2/ancombc/*.tsv"], optional=True),
        dispatched=["taxonomy"],
    )

    step = run.steps["ma_canonical"]
    assert step["status"] == "skipped"
    assert step["detail"] == (
        "Not built: the optional collection 'ancombc_results' it reads is absent from this run."
    )
    assert run.steps["ancombc_results"]["status"] == "skipped"
    assert {r.data_collection_tag: r.status for r in run.results}["ma_canonical"] == "skipped"

    # Once the dispatched collection is in, the run closes clean around both.
    from depictio.api.v1.celery_tasks import _finalize_manifest_refresh_run
    from depictio.api.v1.monitoring import store as monitoring_store

    monitoring_store.set_ingestion_step(
        run.run_id, step={"name": "taxonomy", "status": "success"}, current_step=None
    )
    _finalize_manifest_refresh_run(run.run_id)
    assert db["ingestion_runs"].find_one({"run_id": run.run_id})["status"] == "success"
    polled = manifest_ingest._get_refresh_run_report(run.run_id, run.user)
    assert polled.success is True
    assert {r.data_collection_tag: r.status for r in polled.refreshed}["ma_canonical"] == "skipped"


def test_a_collection_reading_a_failed_required_one_stays_failed(db):
    reading = _row("variants_canonical", collections=["summary_metrics"])
    run = _dispatch(
        db, _row("summary_metrics", files=["multiqc/summary_variants_metrics_mqc.csv"]), reading
    )

    assert run.steps["summary_metrics"]["status"] == "failed"
    assert run.steps["variants_canonical"]["status"] == "failed"
    assert run.steps["variants_canonical"]["detail"] == from_run._skip_reason(reading)


def test_a_collection_missing_a_file_of_its_own_stays_failed(db):
    own_file = _row(
        "ma_canonical", collections=["ancombc_results"], files=["qiime2/ancombc/levels.tsv"]
    )
    run = _dispatch(
        db, own_file, _row("ancombc_results", files=["qiime2/ancombc/*.tsv"], optional=True)
    )

    assert run.steps["ma_canonical"]["status"] == "failed"
    assert run.steps["ma_canonical"]["detail"] == from_run._skip_reason(own_file)


def test_a_collection_reading_both_an_absent_and_a_failed_one_stays_failed(db):
    joined = _row("joined", collections=["ancombc_results", "summary_metrics"])
    run = _dispatch(
        db,
        _row("summary_metrics", files=["multiqc/summary_variants_metrics_mqc.csv"]),
        joined,
        _row("ancombc_results", files=["qiime2/ancombc/*.tsv"], optional=True),
    )

    assert run.steps["joined"]["status"] == "failed"
    assert run.steps["joined"]["detail"] == from_run._skip_reason(joined)


def test_a_chain_built_on_one_absent_collection_is_skipped_whole(db):
    # The dependant comes first: settling must not depend on the order.
    run = _dispatch(
        db,
        _row("ma_plot_ready", collections=["ma_canonical"]),
        _row("ma_canonical", collections=["ancombc_results"]),
        _row("ancombc_results", files=["qiime2/ancombc/*.tsv"], optional=True),
    )

    assert run.steps["ma_canonical"]["status"] == "skipped"
    assert run.steps["ma_plot_ready"]["status"] == "skipped"
    assert run.steps["ma_plot_ready"]["detail"] == (
        "Not built: the collection 'ma_canonical' it reads is not built in this run either."
    )
    # Nothing was dispatched and nothing failed: the run is closed, clean.
    assert db["ingestion_runs"].find_one({"run_id": run.run_id})["status"] == "success"


def test_a_scan_collection_absent_from_the_root_stays_failed(db):
    run = _dispatch(
        db,
        _row("samplesheet", location="s3://bucket/run42/samplesheet.csv"),
        _row("ancombc_results", files=["qiime2/ancombc/*.tsv"], optional=True),
    )

    assert run.steps["samplesheet"]["status"] == "failed"


def test_several_absent_optional_collections_are_all_named():
    failed, skipped = manifest_ingest._skip_dependants_of_absent_collections(
        [("joined", "id-j", "Not ingested.")],
        [("a", "id-a", OPTIONAL_PREFIX), ("b", "id-b", OPTIONAL_PREFIX)],
        {"joined": ["a", "b"]},
    )

    assert failed == []
    assert skipped[-1] == (
        "joined",
        "id-j",
        "Not built: the optional collections 'a', 'b' it reads are absent from this run.",
    )


def test_only_a_required_collection_missing_nothing_but_collections_is_named():
    rows = [
        _row("reads_only", collections=["a", "b"]),
        _row("own_file_too", collections=["a"], files=["x.tsv"]),
        _row("optional_reader", collections=["a"], optional=True),
        _row("files_only", files=["y.tsv"]),
    ]
    assert from_run._missing_collections_only(rows) == {"reads_only": ["a", "b"]}


def test_the_wording_of_a_detail_decides_nothing(db):
    """The structure decides: a reworded label still skips, and a detail in the
    exact wording an older release parsed does not skip without it."""
    reworded = _row("ma_canonical", collections=["ancombc_results"], labels=["the ANCOM table"])
    run = _dispatch(
        db, reworded, _row("ancombc_results", files=["qiime2/ancombc/*.tsv"], optional=True)
    )
    assert run.steps["ma_canonical"]["status"] == "skipped"

    old_wording = "Not ingested: source(s) not found under the data root: collection 'a'."
    failed, skipped = manifest_ingest._skip_dependants_of_absent_collections(
        [("joined", "id-j", old_wording), ("other", "id-o", "anything at all")],
        [("a", "id-a", OPTIONAL_PREFIX)],
        {"other": ["a"]},
    )
    assert failed == [("joined", "id-j", old_wording)]
    assert [tag for tag, _dc_id, _detail in skipped] == ["a", "other"]
