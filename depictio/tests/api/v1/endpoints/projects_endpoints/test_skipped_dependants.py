"""A collection that can only be missing because an optional collection it reads is.

``POST /projects/from_run`` seeds a collection the preview found missing as an
already-terminal step: ``failed`` when the template requires it, ``skipped``
when it marks it optional (a route the run did not take). A required
collection whose own files are all there but which reads (``dc_ref``) such an
optional, absent collection cannot be built for that reason alone, so
``_dispatch_refresh_tasks`` skips it too, saying which collection it is
missing. One that misses a file of its own, or reads a collection that failed,
stays failed.

The pre-flight messages are built with ``from_run._skip_reason`` itself, so a
change of its wording shows up here rather than as a silent "failed" live.
"""

from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.projects_endpoints import from_run, manifest_ingest
from depictio.models.models.users import UserBase

OPTIONAL_PREFIX = "Skipped optional collection: "


def _missing(*sources: str) -> str:
    """The detail from_run seeds for a collection whose sources are missing."""
    return from_run._skip_reason(SimpleNamespace(missing_sources=list(sources), location=""))


def _collection(tag: str) -> str:
    return f"collection '{tag}'"


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


def _dispatch(db, *, failed, skipped, dispatched=()):
    """Run the dispatch for a project holding every tag named; returns the run's steps."""
    user = UserBase(id=ObjectId(), email="owner@example.com", is_admin=False)
    tags = [*failed, *skipped, *dispatched]
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
        preflight_failed=[(tag, ids[tag], message) for tag, message in failed.items()],
        preflight_skipped=[
            (tag, ids[tag], f"{OPTIONAL_PREFIX}{message}") for tag, message in skipped.items()
        ],
        command="from_run",
    )
    run_doc = db["ingestion_runs"].find_one({"run_id": run_id})
    steps = {step["name"]: step for step in run_doc["steps"]}
    return SimpleNamespace(run_id=run_id, user=user, steps=steps, results=results)


def test_a_required_collection_reading_an_absent_optional_one_is_skipped(db):
    run = _dispatch(
        db,
        failed={"ma_canonical": _missing(_collection("ancombc_results"))},
        skipped={"ancombc_results": _missing("qiime2/ancombc/*.tsv")},
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
    reason = _missing(_collection("summary_metrics"))
    run = _dispatch(
        db,
        failed={
            "summary_metrics": _missing("multiqc/summary_variants_metrics_mqc.csv"),
            "variants_canonical": reason,
        },
        skipped={},
    )

    assert run.steps["summary_metrics"]["status"] == "failed"
    assert run.steps["variants_canonical"]["status"] == "failed"
    assert run.steps["variants_canonical"]["detail"] == reason


def test_a_collection_missing_a_file_of_its_own_stays_failed(db):
    reason = _missing(_collection("ancombc_results"), "qiime2/ancombc/levels.tsv")
    run = _dispatch(
        db,
        failed={"ma_canonical": reason},
        skipped={"ancombc_results": _missing("qiime2/ancombc/*.tsv")},
    )

    assert run.steps["ma_canonical"]["status"] == "failed"
    assert run.steps["ma_canonical"]["detail"] == reason


def test_a_collection_reading_both_an_absent_and_a_failed_one_stays_failed(db):
    reason = _missing(_collection("ancombc_results"), _collection("summary_metrics"))
    run = _dispatch(
        db,
        failed={
            "summary_metrics": _missing("multiqc/summary_variants_metrics_mqc.csv"),
            "joined": reason,
        },
        skipped={"ancombc_results": _missing("qiime2/ancombc/*.tsv")},
    )

    assert run.steps["joined"]["status"] == "failed"
    assert run.steps["joined"]["detail"] == reason


def test_a_chain_built_on_one_absent_collection_is_skipped_whole(db):
    # The dependant comes first: settling must not depend on the order.
    run = _dispatch(
        db,
        failed={
            "ma_plot_ready": _missing(_collection("ma_canonical")),
            "ma_canonical": _missing(_collection("ancombc_results")),
        },
        skipped={"ancombc_results": _missing("qiime2/ancombc/*.tsv")},
    )

    assert run.steps["ma_canonical"]["status"] == "skipped"
    assert run.steps["ma_plot_ready"]["status"] == "skipped"
    assert run.steps["ma_plot_ready"]["detail"] == (
        "Not built: the collection 'ma_canonical' it reads is not built in this run either."
    )
    # Nothing was dispatched and nothing failed: the run is closed, clean.
    assert db["ingestion_runs"].find_one({"run_id": run.run_id})["status"] == "success"


def test_a_scan_collection_absent_from_the_root_stays_failed(db):
    reason = from_run._skip_reason(
        SimpleNamespace(missing_sources=[], location="s3://bucket/run42/samplesheet.csv")
    )
    run = _dispatch(
        db,
        failed={"samplesheet": reason},
        skipped={"ancombc_results": _missing("qiime2/ancombc/*.tsv")},
    )

    assert run.steps["samplesheet"]["status"] == "failed"


def test_several_absent_optional_collections_are_all_named():
    failed, skipped = manifest_ingest._skip_dependants_of_absent_collections(
        [("joined", "id-j", _missing(_collection("a"), _collection("b")))],
        [("a", "id-a", OPTIONAL_PREFIX), ("b", "id-b", OPTIONAL_PREFIX)],
    )

    assert failed == []
    assert skipped[-1] == (
        "joined",
        "id-j",
        "Not built: the optional collections 'a', 'b' it reads are absent from this run.",
    )
