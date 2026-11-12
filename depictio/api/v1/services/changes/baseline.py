"""Snapshots of what a dashboard family or a project is at, for reader marks.

Every read here is Mongo only, never the object store: a baseline is taken on
each viewer open, so it must cost a handful of indexed queries.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from bson import ObjectId

from depictio.api.v1.db import (
    comment_threads_collection,
    dashboard_versions_collection,
    deltatables_collection,
    ingestion_runs_collection,
    multiqc_collection,
    projects_collection,
    runs_collection,
)
from depictio.api.v1.endpoints.dashboards_endpoints import schema_integrity, version_store
from depictio.models.models.reader_marks import (
    MAX_TRACKED_COLLECTIONS,
    MAX_TRACKED_REPORTS,
    MAX_TRACKED_RUN_TAGS,
    DcSeenState,
    ReaderBaseline,
)
from depictio.models.timestamps import utc_now_naive


def _oid(value: Any) -> ObjectId | None:
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


# ── what a family / project references ──────────────────────────────────────


def family_components(family_docs: Iterable[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Every component of a family with the id of the tab it sits on."""
    out: list[tuple[str, dict[str, Any]]] = []
    for doc in family_docs:
        tab_id = str(doc.get("dashboard_id") or doc.get("_id"))
        for component in doc.get("stored_metadata") or []:
            if isinstance(component, dict):
                out.append((tab_id, component))
    return out


def project_collections(project_id: Any) -> dict[str, dict[str, Any]]:
    """``dc_id -> {type, workflow_id, workflow_tag, data_collection_tag}`` for a project."""
    oid = _oid(project_id)
    if oid is None:
        return {}
    project = projects_collection.find_one(
        {"_id": oid},
        {
            "workflows._id": 1,
            "workflows.workflow_tag": 1,
            "workflows.name": 1,
            "workflows.data_collections._id": 1,
            "workflows.data_collections.data_collection_tag": 1,
            "workflows.data_collections.config.type": 1,
        },
    )
    out: dict[str, dict[str, Any]] = {}
    for workflow in (project or {}).get("workflows") or []:
        wf_tag = workflow.get("workflow_tag") or workflow.get("name") or ""
        for dc in workflow.get("data_collections") or []:
            dc_id = str(dc.get("_id") or "")
            if not dc_id:
                continue
            out[dc_id] = {
                "type": str(((dc.get("config") or {}).get("type")) or "").lower(),
                "workflow_id": str(workflow.get("_id") or ""),
                "workflow_tag": wf_tag,
                "data_collection_tag": dc.get("data_collection_tag") or "",
            }
    return out


# ── per-collection state ────────────────────────────────────────────────────


def aggregations_of(dc_id: str) -> list[dict[str, Any]]:
    oid = _oid(dc_id)
    if oid is None:
        return []
    doc = deltatables_collection.find_one({"data_collection_id": oid}, {"aggregation": 1})
    return list((doc or {}).get("aggregation") or [])


def multiqc_reports_of(dc_id: str) -> list[dict[str, Any]]:
    return list(
        multiqc_collection.find(
            {"data_collection_id": str(dc_id)},
            {
                "processed_at": 1,
                "run_tag": 1,
                "ingestion_run_id": 1,
                "original_file_path": 1,
                "metadata.samples": 1,
                "report_name": 1,
            },
        ).limit(MAX_TRACKED_REPORTS)
    )


def dc_state(dc_id: str, dc_type: str) -> DcSeenState:
    """What one collection is at now."""
    state = DcSeenState(dc_type=dc_type or "")
    if dc_type == "multiqc":
        reports = multiqc_reports_of(dc_id)
        state.multiqc_reports = {str(r["_id"]): _iso(r.get("processed_at")) for r in reports}
        state.run_tags = sorted({r["run_tag"] for r in reports if r.get("run_tag")})[
            :MAX_TRACKED_RUN_TAGS
        ]
        return state

    aggregations = aggregations_of(dc_id)
    if aggregations:
        latest = aggregations[-1]
        state.delta_version = latest.get("delta_version")
        state.aggregation_version = latest.get("aggregation_version")
        state.row_count = latest.get("rows_total")
        tags: set[str] = set()
        for agg in aggregations:
            tags.update(t for t in agg.get("run_tags") or [] if t)
        state.run_tags = sorted(tags)[:MAX_TRACKED_RUN_TAGS]
    return state


def data_token(state: DcSeenState | None) -> str | None:
    """A short value that changes whenever the collection's data does."""
    if state is None:
        return None
    if state.multiqc_reports:
        return "mqc:" + "|".join(f"{k}@{v}" for k, v in sorted(state.multiqc_reports.items()))
    if state.delta_version is not None:
        return f"dv:{state.delta_version}"
    if state.aggregation_version is not None:
        return f"av:{state.aggregation_version}"
    return None


# ── cursors ─────────────────────────────────────────────────────────────────


def comment_cursor(family_id: str) -> datetime | None:
    newest: datetime | None = None
    for thread in comment_threads_collection.find(
        {"parent_dashboard_id": str(family_id)}, {"created_at": 1, "comments.created_at": 1}
    ):
        for value in [thread.get("created_at")] + [
            c.get("created_at") for c in thread.get("comments") or []
        ]:
            if isinstance(value, datetime) and (newest is None or value > newest):
                newest = value
    return newest


def ingestion_cursor(project_id: Any) -> datetime | None:
    doc = ingestion_runs_collection.find_one(
        {"project_id": str(project_id)}, {"started_at": 1}, sort=[("started_at", -1)]
    )
    value = (doc or {}).get("started_at")
    return value if isinstance(value, datetime) else None


def workflow_runs(project_id: Any) -> dict[str, list[str]]:
    workflows = {info["workflow_id"] for info in project_collections(project_id).values()}
    out: dict[str, list[str]] = {}
    for wf_id in workflows:
        oid = _oid(wf_id)
        if oid is None:
            continue
        tags = runs_collection.distinct("run_tag", {"workflow_id": oid})
        out[wf_id] = sorted(str(t) for t in tags if t)[:MAX_TRACKED_RUN_TAGS]
    return out


# ── baselines ───────────────────────────────────────────────────────────────


def family_dc_types(family_docs: list[dict[str, Any]], project_id: Any) -> dict[str, str]:
    """The collections a family reads, with their types (project document first)."""
    components = [c for _, c in family_components(family_docs)]
    dc_ids = schema_integrity.collect_dc_ids(components)[:MAX_TRACKED_COLLECTIONS]
    known = project_collections(project_id)
    out: dict[str, str] = {}
    for dc_id in dc_ids:
        dc_type = known.get(dc_id, {}).get("type") or ""
        if not dc_type:
            for component in components:
                if schema_integrity.component_dc_id(component) == dc_id:
                    dc_type = str((component.get("dc_config") or {}).get("type") or "").lower()
                    if dc_type:
                        break
        out[dc_id] = dc_type
    return out


def family_baseline(family_id: str, family_docs: list[dict[str, Any]]) -> ReaderBaseline:
    """What the family is at now: newest version, every collection, the discussion."""
    main = family_docs[0] if family_docs else {}
    project_id = main.get("project_id")
    latest = version_store.list_versions(str(family_id), limit=1)
    version = latest[0] if latest else None
    return ReaderBaseline(
        seen_at=utc_now_naive(),
        version_id=(version or {}).get("version_id"),
        version_seq=(version or {}).get("seq"),
        version_content_hash=(version or {}).get("content_hash"),
        dc_states={
            dc_id: dc_state(dc_id, dc_type)
            for dc_id, dc_type in family_dc_types(family_docs, project_id).items()
        },
        comment_cursor_at=comment_cursor(str(family_id)),
        ingestion_cursor_at=ingestion_cursor(project_id) if project_id else None,
    )


def project_baseline(project_id: str) -> ReaderBaseline:
    collections = project_collections(project_id)
    return ReaderBaseline(
        seen_at=utc_now_naive(),
        dc_states={
            dc_id: dc_state(dc_id, info["type"])
            for dc_id, info in list(collections.items())[:MAX_TRACKED_COLLECTIONS]
        },
        ingestion_cursor_at=ingestion_cursor(project_id),
        workflow_runs=workflow_runs(project_id),
    )


# ── baselines in the past, for read-only "since" views ──────────────────────


def _version_at(family_id: str, when: datetime) -> dict[str, Any] | None:
    return dashboard_versions_collection.find_one(
        {"family_id": str(family_id), "created_at": {"$lte": when}},
        {"tabs": 0},
        sort=[("seq", -1)],
    )


def _rewind_state(state: DcSeenState, dc_id: str, *, keep_agg, keep_report) -> DcSeenState:
    """``state`` with the writes ``keep_*`` rejects taken back out."""
    if state.multiqc_reports:
        reports = {r["_id"]: r for r in multiqc_reports_of(dc_id)}
        kept = {
            k: v
            for k, v in state.multiqc_reports.items()
            if (_oid(k) in reports and keep_report(reports[_oid(k)]))
        }
        tags = sorted(
            {reports[_oid(k)].get("run_tag") for k in kept if reports[_oid(k)].get("run_tag")}
        )
        return DcSeenState(dc_type=state.dc_type, multiqc_reports=kept, run_tags=tags)

    kept_aggs = [a for a in aggregations_of(dc_id) if keep_agg(a)]
    if not kept_aggs:
        return DcSeenState(
            dc_type=state.dc_type, delta_version=-1, aggregation_version=0, row_count=0
        )
    last = kept_aggs[-1]
    tags = sorted({t for a in kept_aggs for t in a.get("run_tags") or [] if t})
    return DcSeenState(
        dc_type=state.dc_type,
        delta_version=last.get("delta_version"),
        aggregation_version=last.get("aggregation_version"),
        row_count=last.get("rows_total"),
        run_tags=tags,
    )


def rewind_baseline(
    now: ReaderBaseline,
    family_id: str | None,
    *,
    since: datetime | None = None,
    before_run: str | None = None,
) -> ReaderBaseline:
    """The state just before an ingestion run, or at a moment.

    ``before_run`` is the sturdy form: the writes of that one ingestion are
    taken out by id, with no clock involved. ``since`` compares timestamps
    and inherits their clocks; it serves links that only have a time.
    """
    run_started: datetime | None = None
    run_tags: set[str] = set()
    if before_run:
        run = (
            ingestion_runs_collection.find_one(
                {"run_id": before_run}, {"started_at": 1, "run_tags": 1}
            )
            or {}
        )
        run_started = run.get("started_at")
        run_tags = set(run.get("run_tags") or [])

        def keep_agg(a: dict[str, Any]) -> bool:
            return a.get("ingestion_run_id") != before_run

        def keep_report(r: dict[str, Any]) -> bool:
            return r.get("ingestion_run_id") != before_run

        version_moment = run_started
    else:
        assert since is not None

        def keep_agg(a: dict[str, Any]) -> bool:
            when = a.get("delta_commit_timestamp") or a.get("aggregation_time")
            return not isinstance(when, datetime) or when <= since

        def keep_report(r: dict[str, Any]) -> bool:
            when = r.get("processed_at")
            return not isinstance(when, datetime) or when <= since

        version_moment = since

    rewound = ReaderBaseline(
        seen_at=version_moment or now.seen_at,
        dc_states={
            dc_id: _rewind_state(state, dc_id, keep_agg=keep_agg, keep_report=keep_report)
            for dc_id, state in now.dc_states.items()
        },
        comment_cursor_at=version_moment,
        ingestion_cursor_at=run_started if before_run else since,
        workflow_runs=(
            {wf: [t for t in tags if t not in run_tags] for wf, tags in now.workflow_runs.items()}
            if before_run
            else now.workflow_runs
        ),
    )
    if family_id and version_moment is not None:
        version = _version_at(family_id, version_moment)
        if version:
            rewound.version_id = version.get("version_id")
            rewound.version_seq = version.get("seq")
            rewound.version_content_hash = version.get("content_hash")
    return rewound
