"""The pre-built offline bundle a public project's visitors download (#1480).

A visitor never builds a bundle. The project's owner turns the download on
(``Project.public_offline_download``, public projects only); from then on a
worker keeps one bundle per dashboard family at the dashboard's default state,
and the download route hands out what is already there.

* **Cache.** One document per family in ``public_bundles``, ``_id`` = the main
  tab's id, so it needs no index (a deployment initialised before this release
  gets no new index at boot, #1482). It holds the bundle served now
  (``current``) and the one before it (``previous``); the files live under
  ``serverless-public/<main tab id>/``, outside the retention prune of
  ``serverless-exports/``. Nothing expires while the download stays on;
  everything goes when it is turned off, the project is made private, or the
  dashboard or project is deleted (:func:`drop`, :func:`drop_project`).
* **Key.** :func:`content_key` hashes what a bundle is drawn from, with Mongo
  reads only: the family's content hash (the one dashboard versioning uses), the
  newest aggregation of each of the project's collections, the MultiQC report
  set, and the static runtime the bundle is composed from.
* **Rebuild.** A save (``versioning.capture_dashboard_version``) and an
  ingestion call :func:`notify_dashboard_changed` / :func:`notify_data_changed`.
  They queue at most one build per family (``scheduled``), delayed by
  ``public_rebuild_delay_s`` so a burst of autosaves or a multi-collection
  ingestion costs one build. While it runs, ``current`` keeps being served and
  the status says ``rebuilding``.
* **What a public build is.** Producer A with ``public=True``: as the project's
  owner but without their email (``exported_by`` stays empty), without the
  Python runtime, without a state, code-mode figures frozen and their source
  left out.
* **The report.** Where the instance renders reports (the notebook export and
  its render on), each built bundle is followed by its report (``report`` in
  the same document): the combined report + dashboard file and its PDF, under
  the same key, rendered by Quarto as the owner without their email, at the
  report layer's state, without running an author's Python, with the public
  manifest. It is a separate task (:data:`REPORT_TASK`), since a render takes
  minutes and holds one of the deployment's report slots; until it is done
  the previous report is served.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger

#: Where public bundles live in S3, one folder per dashboard family.
PUBLIC_PREFIX = "serverless-public/"
#: Bumped when what the key covers changes, so every bundle is rebuilt once.
KEY_SCHEMA = 1
#: The Celery task that builds one family's bundle (``celery_tasks``).
BUILD_TASK = "depictio.serverless.build_public_bundle"
#: The Celery task that renders one family's report and PDF after its bundle.
REPORT_TASK = "depictio.serverless.build_public_report"


# ---------------------------------------------------------------------------
# Seams (patched by the tests)
# ---------------------------------------------------------------------------


def _db() -> Any:
    from depictio.api.v1 import db

    return db


def _s3() -> Any:
    from depictio.api.v1.s3 import s3_client

    return s3_client


def _export_static(dashboard_id: str, out_path: Path, **kwargs: Any) -> Any:
    from depictio.serverless.producer_a import export_static

    return export_static(dashboard_id, out_path=out_path, **kwargs)


def _dispatch(main_id: str, delay: int) -> None:
    from depictio.api.celery_app import celery_app

    celery_app.send_task(BUILD_TASK, args=[main_id], countdown=delay)


def _dispatch_report(main_id: str) -> None:
    from depictio.api.celery_app import celery_app

    celery_app.send_task(REPORT_TASK, args=[main_id])


def _render_report(main_id: str, owner_id: Any) -> tuple[bytes, bytes | None, str]:
    """The combined report + dashboard file, its PDF (``None`` when the PDF
    failed) and the report's file stem, rendered for a visitor's copy."""
    from depictio.serverless.public_report import render_public_report

    return render_public_report(main_id, owner_id)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _oid(value: Any) -> ObjectId | None:
    try:
        return ObjectId(str(value))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Who may have a public bundle
# ---------------------------------------------------------------------------


def enabled() -> bool:
    """Both switches: the static export and its public download."""
    return bool(settings.static_export.enabled and settings.static_export.public_download_enabled)


def report_enabled() -> bool:
    """Whether visitors' copies include the rendered report and its PDF."""
    nb = settings.notebook_export
    return bool(enabled() and nb.enabled and nb.render_enabled)


def eligible(project: dict[str, Any] | None) -> bool:
    """Whether ``project``'s visitors may download its dashboards' bundles."""
    return bool(
        enabled()
        and project
        and project.get("is_public")
        and project.get("public_offline_download")
    )


def main_tab_id(dashboard_id: Any) -> str | None:
    """The family's main tab id for any of its tabs, or ``None`` when unknown."""
    oid = _oid(dashboard_id)
    if oid is None:
        return None
    doc = _db().dashboards_collection.find_one(
        {"dashboard_id": oid}, {"is_main_tab": 1, "parent_dashboard_id": 1, "dashboard_id": 1}
    )
    if not doc:
        return None
    if doc.get("is_main_tab", True) is False and doc.get("parent_dashboard_id"):
        return str(doc["parent_dashboard_id"])
    return str(doc["dashboard_id"])


def project_of(main_id: str) -> dict[str, Any] | None:
    """The project document of a family's main tab."""
    doc = _db().dashboards_collection.find_one({"dashboard_id": _oid(main_id)}, {"project_id": 1})
    project_id = _oid((doc or {}).get("project_id"))
    if project_id is None:
        return None
    return _db().projects_collection.find_one({"_id": project_id})


def _owner_id(project: dict[str, Any]) -> Any:
    owners = (project.get("permissions") or {}).get("owners") or []
    for owner in owners:
        owner_id = owner.get("_id") or owner.get("id")
        if owner_id:
            return owner_id
    return None


# ---------------------------------------------------------------------------
# The content key
# ---------------------------------------------------------------------------


def _family_docs(main_id: str) -> list[dict[str, Any]]:
    dashboards = _db().dashboards_collection
    oid = _oid(main_id)
    main = dashboards.find_one({"dashboard_id": oid})
    if not main:
        return []
    children = list(dashboards.find({"parent_dashboard_id": oid}).sort("tab_order", 1))
    return [main, *children]


def _family_hash(main_id: str) -> str:
    """The family's content hash, as dashboard versioning computes it."""
    from depictio.api.v1.endpoints.dashboards_endpoints.versioning import (
        build_tab_snapshots,
        compute_content_hash,
    )

    docs = _family_docs(main_id)
    return compute_content_hash(build_tab_snapshots(docs)) if docs else ""


def _project_dc_ids(project: dict[str, Any]) -> list[ObjectId]:
    ids: list[ObjectId] = []
    for dc in project.get("data_collections") or []:
        if (oid := _oid(dc.get("_id") or dc.get("id"))) is not None:
            ids.append(oid)
    for workflow in project.get("workflows") or []:
        for dc in workflow.get("data_collections") or []:
            if (oid := _oid(dc.get("_id") or dc.get("id"))) is not None:
                ids.append(oid)
    return sorted(set(ids), key=str)


def _data_facts(project: dict[str, Any]) -> list[Any]:
    """The newest aggregation of each collection and each MultiQC report set."""
    db = _db()
    ids = _project_dc_ids(project)
    if not ids:
        return []
    facts: list[Any] = []
    for entry in db.deltatables_collection.find(
        {"data_collection_id": {"$in": ids}}, {"data_collection_id": 1, "aggregation": 1}
    ):
        last = (entry.get("aggregation") or [{}])[-1]
        facts.append(
            [
                str(entry.get("data_collection_id")),
                last.get("aggregation_version"),
                str(last.get("aggregation_time") or ""),
                last.get("aggregation_hash"),
            ]
        )
    reports: dict[str, list[str]] = {}
    for report in db.multiqc_collection.find(
        {"data_collection_id": {"$in": [str(i) for i in ids]}},
        {"data_collection_id": 1, "s3_location": 1, "processed_at": 1},
    ):
        reports.setdefault(str(report.get("data_collection_id")), []).append(
            f"{report.get('s3_location')}@{report.get('processed_at') or ''}"
        )
    facts.extend([dc, sorted(locations)] for dc, locations in reports.items())
    return sorted(facts, key=lambda f: json.dumps(f, default=str))


def _runtime_signature() -> str:
    """Which static runtime a build composes from: a new viewer means a new bundle."""
    from depictio.serverless.dist import runtime_path

    try:
        stat = runtime_path().stat()
        return f"{stat.st_size}:{int(stat.st_mtime)}"
    except OSError:
        return "missing"


def content_key(main_id: str, project: dict[str, Any]) -> str:
    """The hash of everything a public bundle of this family is drawn from."""
    from depictio.version import get_version

    payload = [
        KEY_SCHEMA,
        get_version(),
        _runtime_signature(),
        _family_hash(main_id),
        _data_facts(project),
    ]
    return hashlib.sha256(json.dumps(payload, default=str).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def schedule(main_id: str, project_id: Any = None, delay: int | None = None) -> bool:
    """Queue one build of ``main_id``'s bundle unless one is queued already.

    Returns whether this call queued it. A build that could not be queued
    leaves the family unscheduled, so the next change tries again.
    """
    coll = _db().public_bundles_collection
    countdown = settings.static_export.public_rebuild_delay_s if delay is None else int(delay)
    try:
        coll.find_one_and_update(
            {"_id": main_id, "scheduled": {"$ne": True}},
            {
                "$set": {"scheduled": True, "scheduled_at": _now()},
                "$setOnInsert": {"project_id": str(project_id or "")},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return False  # already queued: this change folds into that build
    try:
        _dispatch(main_id, countdown)
    except Exception as exc:  # noqa: BLE001 - a dead broker must not fail a save
        logger.warning(f"public bundle: could not queue the build of {main_id}: {exc}")
        coll.update_one({"_id": main_id}, {"$set": {"scheduled": False}})
        return False
    return True


def _main_tabs(project_id: Any) -> list[str]:
    oid = _oid(project_id)
    if oid is None:
        return []
    cursor = _db().dashboards_collection.find(
        {"project_id": oid, "is_main_tab": {"$ne": False}}, {"dashboard_id": 1}
    )
    return [str(doc["dashboard_id"]) for doc in cursor if doc.get("dashboard_id")]


def schedule_for_project(project_id: Any, delay: int | None = None) -> int:
    """Queue a build of every dashboard of an eligible project."""
    project = _db().projects_collection.find_one({"_id": _oid(project_id)})
    if not eligible(project):
        return 0
    return sum(schedule(main_id, project_id, delay) for main_id in _main_tabs(project_id))


def notify_dashboard_changed(dashboard_id: Any, project_id: Any) -> None:
    """A dashboard's content changed: queue its family's rebuild. Never raises."""
    try:
        if not enabled():
            return
        project = _db().projects_collection.find_one(
            {"_id": _oid(project_id)}, {"is_public": 1, "public_offline_download": 1}
        )
        if not eligible(project):
            return
        main_id = main_tab_id(dashboard_id)
        if main_id:
            schedule(main_id, project_id)
    except Exception as exc:  # noqa: BLE001 - a hook must never break a save
        logger.warning(f"public bundle: change of dashboard {dashboard_id} not handled: {exc}")


def notify_data_changed(dc_id: Any) -> None:
    """A collection's data changed: queue the rebuild of every dashboard of the
    projects holding it. Never raises."""
    try:
        if not enabled():
            return
        oid = _oid(dc_id)
        if oid is None:
            return
        projects = _db().projects_collection.find(
            {
                "$or": [{"data_collections._id": oid}, {"workflows.data_collections._id": oid}],
                "is_public": True,
                "public_offline_download": True,
            },
            {"_id": 1},
        )
        for project in projects:
            schedule_for_project(project["_id"])
    except Exception as exc:  # noqa: BLE001 - a hook must never break an ingestion
        logger.warning(f"public bundle: change of collection {dc_id} not handled: {exc}")


def pending_count() -> int:
    """Public builds queued or running, for the export queue cap."""
    try:
        return int(
            _db().public_bundles_collection.count_documents(
                {"$or": [{"scheduled": True}, {"status": "building"}]}
            )
        )
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def s3_key(main_id: str, key: str) -> str:
    return f"{PUBLIC_PREFIX}{main_id}/{key[:32]}.html"


def build(main_id: str) -> dict[str, Any]:
    """Build ``main_id``'s public bundle if its content key moved (the task body)."""
    from depictio.serverless.producer_a import ExportUser

    coll = _db().public_bundles_collection
    coll.update_one({"_id": main_id}, {"$set": {"scheduled": False}}, upsert=True)
    project = project_of(main_id)
    if not eligible(project):
        drop(main_id)
        return {"status": "skipped"}
    assert project is not None
    owner_id = _owner_id(project)
    if owner_id is None:
        return {"status": "skipped", "reason": "the project has no owner"}

    key = content_key(main_id, project)
    doc = coll.find_one({"_id": main_id}) or {}
    if (doc.get("current") or {}).get("key") == key:
        coll.update_one({"_id": main_id}, {"$set": {"status": "ready"}})
        schedule_report(main_id, key)
        return {"status": "unchanged"}

    coll.update_one(
        {"_id": main_id},
        {"$set": {"status": "building", "started_at": _now(), "project_id": str(project["_id"])}},
    )
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "bundle.html"
            _export_static(
                main_id,
                out,
                user=ExportUser(id=owner_id, email="", is_admin=False, is_anonymous=False),
                python_runtime="off",
                state=None,
                public=True,
            )
            html = out.read_bytes()
        object_key = s3_key(main_id, key)
        _s3().put_object(
            Bucket=settings.s3.bucket,
            Key=object_key,
            Body=html,
            ContentType="text/html; charset=utf-8",
        )
    except Exception as exc:
        logger.error(f"public bundle: build of {main_id} failed: {exc}")
        coll.update_one({"_id": main_id}, {"$set": {"status": "failed", "error": str(exc)[:500]}})
        raise

    entry = {
        "key": key,
        "s3_key": object_key,
        "size_bytes": len(html),
        "built_at": _now().isoformat(),
    }
    old = doc.get("current")
    coll.update_one(
        {"_id": main_id},
        {"$set": {"status": "ready", "error": None, "current": entry, "previous": old}},
    )
    _delete_others(main_id)
    # A change that landed while this build ran is in neither bundle.
    if content_key(main_id, project) != key:
        schedule(main_id, project["_id"])
    else:
        schedule_report(main_id, key)
    return {"status": "built", **entry}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def report_s3_key(main_id: str, key: str, ext: str) -> str:
    return f"{PUBLIC_PREFIX}{main_id}/{key[:32]}-report.{ext}"


def schedule_report(main_id: str, key: str) -> bool:
    """Queue the render of the report of the bundle built under ``key``,
    unless that report exists or a render is queued already."""
    if not report_enabled():
        return False
    coll = _db().public_bundles_collection
    try:
        queued = coll.find_one_and_update(
            {
                "_id": main_id,
                "report.scheduled": {"$ne": True},
                "report.current.key": {"$ne": key},
            },
            {"$set": {"report.scheduled": True, "report.scheduled_at": _now()}},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"public bundle: could not queue the report of {main_id}: {exc}")
        return False
    if queued is None:
        return False
    try:
        _dispatch_report(main_id)
    except Exception as exc:  # noqa: BLE001 - a dead broker must not fail the bundle
        logger.warning(f"public bundle: could not queue the report of {main_id}: {exc}")
        coll.update_one({"_id": main_id}, {"$set": {"report.scheduled": False}})
        return False
    return True


def build_report(main_id: str) -> dict[str, Any]:
    """Render ``main_id``'s report and PDF if its content key moved (the task body).

    Rendered after the bundle, under the same key: a report of other content
    than the bundle beside it is never offered as current.
    """
    coll = _db().public_bundles_collection
    coll.update_one({"_id": main_id}, {"$set": {"report.scheduled": False}}, upsert=True)
    project = project_of(main_id)
    if not eligible(project) or not report_enabled():
        _drop_report(main_id)
        return {"status": "skipped"}
    assert project is not None
    owner_id = _owner_id(project)
    if owner_id is None:
        return {"status": "skipped", "reason": "the project has no owner"}

    key = content_key(main_id, project)
    doc = coll.find_one({"_id": main_id}) or {}
    report = doc.get("report") or {}
    if (report.get("current") or {}).get("key") == key:
        coll.update_one({"_id": main_id}, {"$set": {"report.status": "ready"}})
        return {"status": "unchanged"}
    if (doc.get("current") or {}).get("key") != key:
        # The bundle is behind: its build renders the report once it is done.
        schedule(main_id, project["_id"], delay=0)
        return {"status": "waiting for the bundle"}

    coll.update_one(
        {"_id": main_id}, {"$set": {"report.status": "building", "report.started_at": _now()}}
    )
    try:
        html, pdf, stem = _render_report(main_id, owner_id)
        html_key = report_s3_key(main_id, key, "html")
        _s3().put_object(
            Bucket=settings.s3.bucket,
            Key=html_key,
            Body=html,
            ContentType="text/html; charset=utf-8",
        )
        pdf_key = None
        if pdf is not None:
            pdf_key = report_s3_key(main_id, key, "pdf")
            _s3().put_object(
                Bucket=settings.s3.bucket, Key=pdf_key, Body=pdf, ContentType="application/pdf"
            )
    except Exception as exc:
        logger.error(f"public bundle: report of {main_id} failed: {exc}")
        coll.update_one(
            {"_id": main_id},
            {"$set": {"report.status": "failed", "report.error": str(exc)[:500]}},
        )
        raise

    entry = {
        "key": key,
        "stem": stem,
        "s3_key": html_key,
        "size_bytes": len(html),
        "pdf_s3_key": pdf_key,
        "pdf_size_bytes": len(pdf) if pdf is not None else None,
        "built_at": _now().isoformat(),
    }
    coll.update_one(
        {"_id": main_id},
        {
            "$set": {
                "report.status": "ready",
                "report.error": None,
                "report.current": entry,
                "report.previous": report.get("current"),
            }
        },
    )
    _delete_others(main_id)
    if content_key(main_id, project) != key:
        schedule(main_id, project["_id"])
    return {"status": "built", **entry}


def _drop_report(main_id: str) -> None:
    """Forget a family's report while keeping its bundle (the render is off)."""
    coll = _db().public_bundles_collection
    coll.update_one({"_id": main_id}, {"$unset": {"report": ""}})
    _delete_others(main_id)


def _keys_under(main_id: str) -> list[str]:
    paginator = _s3().get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=settings.s3.bucket, Prefix=f"{PUBLIC_PREFIX}{main_id}/"):
        keys.extend(obj["Key"] for obj in page.get("Contents") or [])
    return keys


def _delete_keys(keys: list[str]) -> None:
    for start in range(0, len(keys), 1000):
        _s3().delete_objects(
            Bucket=settings.s3.bucket,
            Delete={"Objects": [{"Key": k} for k in keys[start : start + 1000]], "Quiet": True},
        )


def _referenced_keys(doc: dict[str, Any] | None) -> set[str]:
    """Every object a family's document still serves: the current and previous
    bundle, report and PDF."""
    doc = doc or {}
    entries = [doc.get("current"), doc.get("previous")]
    report = doc.get("report") or {}
    entries += [report.get("current"), report.get("previous")]
    keys: set[str] = set()
    for entry in entries:
        for field in ("s3_key", "pdf_s3_key"):
            if entry and entry.get(field):
                keys.add(entry[field])
    return keys


def _delete_others(main_id: str) -> None:
    """Delete the family's files its document no longer serves."""
    try:
        keep = _referenced_keys(_db().public_bundles_collection.find_one({"_id": main_id}))
        _delete_keys([k for k in _keys_under(main_id) if k not in keep])
    except Exception as exc:  # noqa: BLE001 - a stale file is harmless
        logger.warning(f"public bundle: could not prune old bundles of {main_id}: {exc}")


def drop(main_id: str) -> None:
    """Forget a family's public bundle: its document and its files."""
    try:
        _delete_keys(_keys_under(main_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"public bundle: could not delete the bundles of {main_id}: {exc}")
    _db().public_bundles_collection.delete_one({"_id": main_id})


def drop_project(project_id: Any) -> int:
    """Forget the public bundles of every dashboard of a project."""
    coll = _db().public_bundles_collection
    ids = {str(doc["_id"]) for doc in coll.find({"project_id": str(project_id)}, {"_id": 1})}
    ids.update(_main_tabs(project_id))
    for main_id in ids:
        drop(main_id)
    return len(ids)


# ---------------------------------------------------------------------------
# Serving
# ---------------------------------------------------------------------------


def served(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """The bundle a download hands out: the newest one built, else the one before."""
    if not doc:
        return None
    return doc.get("current") or doc.get("previous") or None


def rebuilding(doc: dict[str, Any]) -> bool:
    return bool(doc.get("scheduled") or doc.get("status") == "building")


def served_report(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """The report a download hands out: the newest one rendered, else the one
    before. ``None`` when the instance does not render reports."""
    if not doc or not report_enabled():
        return None
    report = doc.get("report") or {}
    return report.get("current") or report.get("previous") or None


def report_rebuilding(doc: dict[str, Any]) -> bool:
    """A newer report is on its way: the bundle or the report is being made."""
    report = (doc or {}).get("report") or {}
    current = report.get("current") or {}
    bundle = (doc or {}).get("current") or {}
    return bool(
        rebuilding(doc)
        or report.get("scheduled")
        or report.get("status") == "building"
        or (bundle.get("key") and current.get("key") != bundle.get("key"))
    )
