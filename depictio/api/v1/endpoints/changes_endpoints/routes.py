"""What changed since a reader's last visit (#1397).

Mounted under ``/changes``. Every route 404s while
``DEPICTIO_DASHBOARD_VERSIONS_CHANGES_SINCE_ENABLED`` is off.

A reader mark is per-reader state, never content: these routes need only
viewer permission, write to ``reader_marks`` alone, and record no dashboard
version. A signed-in reader's mark lives on the server; an anonymous or
temporary reader's lives in their browser, so the server hands the baseline
back and reads it from the request instead. One anonymous account is shared
by every anonymous visitor, so storing it server-side would show one
visitor's marks to all of them.

``since`` and ``before_run`` give read-only views ("what changed after this
moment / this ingestion") that never move a mark.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Optional

import polars as pl
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import (
    comment_threads_collection,
    dashboard_versions_collection,
    dashboards_collection,
    ingestion_runs_collection,
    projects_collection,
)
from depictio.api.v1.endpoints.dashboards_endpoints import versioning
from depictio.api.v1.endpoints.dashboards_endpoints.versions_routes import (
    _require,
    _resolve_family,
)
from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_user_or_anonymous,
    oauth2_scheme_optional,
)
from depictio.api.v1.services.changes import baseline as bl
from depictio.api.v1.services.changes import diff as df
from depictio.api.v1.services.changes import store
from depictio.models.models.reader_marks import (
    ChangesRequest,
    DismissedComponent,
    PrefsRequest,
    ReaderBaseline,
    SeenRequest,
    component_key,
)
from depictio.models.models.users import User

changes_router = APIRouter()

INBOX_LIMIT = 20
TIMELINE_LIMIT = 50


# ── shared ──────────────────────────────────────────────────────────────────


def _enabled() -> None:
    if not settings.dashboard_versions.changes_since_enabled:
        raise HTTPException(status_code=404, detail="Not found.")


def _server_held(user: User | None) -> bool:
    """Whether this reader's marks live on the server (else in their browser)."""
    return bool(
        user is not None
        and getattr(user, "id", None)
        and not getattr(user, "is_anonymous", False)
        and not getattr(user, "is_temporary", False)
    )


def _reader(user: User | None) -> df.Reader:
    return df.Reader(getattr(user, "id", None), getattr(user, "email", None))


def _project_permission(project_id: Any, user: User, level: str) -> bool:
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission

    return bool(project_id) and check_project_permission(project_id, user, level)


def _require_project(project_id: str, user: User) -> None:
    if not ObjectId.is_valid(project_id):
        raise HTTPException(status_code=400, detail="Invalid project id.")
    if not _project_permission(ObjectId(project_id), user, "viewer"):
        raise HTTPException(status_code=403, detail="You cannot view this project.")


def _comment_reader(project_id: Any, user: User) -> tuple[bool, bool]:
    """(may read comments, may moderate) — the rules of the comments drawer."""
    if getattr(user, "is_anonymous", False) and not settings.auth.is_single_user_mode:
        return False, False
    moderator = _project_permission(project_id, user, "editor")
    readable = moderator or (
        settings.comments.viewers_can_comment and _project_permission(project_id, user, "viewer")
    )
    return readable, moderator


def _jsonable(baseline: ReaderBaseline) -> dict[str, Any]:
    return baseline.model_dump(mode="json")


# ── dashboard family ────────────────────────────────────────────────────────


def _family(dashboard_id: str, user: User) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    family_oid, main = _resolve_family(dashboard_id)
    _require(main, user, "viewer")
    docs = versioning.load_family_docs(family_oid)
    return str(family_oid), main, docs


def dashboard_change_set(
    family_id: str,
    main: dict[str, Any],
    docs: list[dict[str, Any]],
    base: ReaderBaseline | None,
    now: ReaderBaseline,
    user: User,
    dismissed: dict[str, DismissedComponent],
) -> dict[str, Any]:
    project_id = main.get("project_id")
    out: dict[str, Any] = {
        "family_id": family_id,
        "first_visit": base is None,
        "since": base.seen_at.isoformat() if base else None,
        "approximate": False,
        "data": [],
        "failed_ingestions": [],
        "dashboard": [],
        "comments": [],
        "changed_components": {},
        "baseline_version_id": base.version_id if base else None,
    }
    if base is None:
        return out

    reader = _reader(user)
    collections = bl.project_collections(project_id)
    data = df.data_changes(base, now, collections, reader)
    dashboard, changed_keys, approximate = df.dashboard_changes(family_id, base, docs, reader)
    readable, moderator = _comment_reader(project_id, user)
    comments = df.comment_changes(family_id, base, reader, moderator=moderator) if readable else []

    marked: dict[str, list[str]] = {key: ["definition"] for key in changed_keys}
    by_data = df.components_reading(docs, {d["dc_id"] for d in data})
    for key in by_data:
        marked.setdefault(key, []).append("data")
    marked = df.apply_dismissals(marked, docs, now, dismissed)

    out.update(
        approximate=approximate,
        data=data,
        failed_ingestions=df.failed_ingestions(project_id, base, reader) if project_id else [],
        dashboard=dashboard,
        comments=comments,
        changed_components=marked,
    )
    return out


@changes_router.post("/dashboard/{dashboard_id}")
def dashboard_changes_endpoint(
    dashboard_id: str,
    body: ChangesRequest | None = None,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """The changes since the caller's mark (or since ``since`` / ``before_run``)."""
    _enabled()
    body = body or ChangesRequest()
    family_id, main, docs = _family(dashboard_id, current_user)
    now = bl.family_baseline(family_id, docs)
    held = _server_held(current_user)

    dismissed: dict[str, DismissedComponent] = {}
    if body.since is not None or body.before_run:
        base: ReaderBaseline | None = bl.rewind_baseline(
            now, family_id, since=body.since, before_run=body.before_run
        )
    elif held:
        mark = store.get_mark(str(current_user.id), "dashboard", family_id)
        base = mark.baseline if mark else None
        dismissed = mark.dismissed if mark else {}
    else:
        base = body.baseline
        dismissed = body.dismissed or {}

    result = dashboard_change_set(family_id, main, docs, base, now, current_user, dismissed)
    result["server_held"] = held
    result["mark_mode"] = store.get_mark_mode(str(current_user.id) if held else None)
    if not held:
        result["current_baseline"] = _jsonable(now)
    return result


@changes_router.put("/dashboard/{dashboard_id}/visit")
def record_dashboard_visit(
    dashboard_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Record a viewer open. The first one, or any in ``previous_visit`` mode, moves the mark."""
    _enabled()
    family_id, _main, docs = _family(dashboard_id, current_user)
    if not _server_held(current_user):
        return {"persisted": False}
    user_id = str(current_user.id)
    mark = store.get_mark(user_id, "dashboard", family_id)
    if mark is None or mark.baseline is None or store.get_mark_mode(user_id) == "previous_visit":
        store.set_baseline(
            user_id, "dashboard", family_id, bl.family_baseline(family_id, docs), visit=True
        )
        return {"persisted": True, "moved": True}
    store.touch_visit(user_id, "dashboard", family_id)
    return {"persisted": True, "moved": False}


@changes_router.put("/dashboard/{dashboard_id}/seen")
def mark_dashboard_seen(
    dashboard_id: str,
    body: SeenRequest | None = None,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Mark everything as seen (moves the mark to now), or only some components."""
    _enabled()
    body = body or SeenRequest()
    family_id, _main, docs = _family(dashboard_id, current_user)
    now = bl.family_baseline(family_id, docs)
    held = _server_held(current_user)

    if body.component_keys is None:
        if held:
            store.set_baseline(str(current_user.id), "dashboard", family_id, now, visit=False)
            return {"persisted": True}
        return {"persisted": False, "baseline": _jsonable(now)}

    live = {
        component_key(tab_id, str(c["index"])): c
        for tab_id, c in bl.family_components(docs)
        if c.get("index")
    }
    entries = {key: df.dismissal_for(live[key], now) for key in body.component_keys if key in live}
    if held:
        store.dismiss(str(current_user.id), "dashboard", family_id, entries)
        return {"persisted": True}
    return {"persisted": False, "dismissed": {k: v.model_dump() for k, v in entries.items()}}


# ── project ─────────────────────────────────────────────────────────────────


def project_change_set(
    project_id: str, base: ReaderBaseline | None, now: ReaderBaseline, user: User
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "project_id": project_id,
        "first_visit": base is None,
        "since": base.seen_at.isoformat() if base else None,
        "data": [],
        "new_runs": [],
        "failed_ingestions": [],
        "dashboards": [],
    }
    if base is None:
        return out
    reader = _reader(user)
    collections = bl.project_collections(project_id)
    out["data"] = df.data_changes(base, now, collections, reader)
    out["new_runs"] = df.new_workflow_runs(base, now)
    out["failed_ingestions"] = df.failed_ingestions(project_id, base, reader)
    out["dashboards"] = _project_dashboard_changes(project_id, base, reader)
    return out


def _project_dashboard_changes(
    project_id: str, base: ReaderBaseline, reader: df.Reader
) -> list[dict[str, Any]]:
    """Dashboards of the project with versions by someone else since the mark."""
    families: dict[str, dict[str, Any]] = {}
    for version in dashboard_versions_collection.find(
        {"project_id": str(project_id), "created_at": {"$gt": base.seen_at}},
        {
            "family_id": 1,
            "author_id": 1,
            "author_email": 1,
            "seq": 1,
            "version_id": 1,
            "created_at": 1,
        },
    ).limit(500):
        if reader.wrote(user_id=version.get("author_id"), email=version.get("author_email")):
            continue
        entry = families.setdefault(
            version["family_id"],
            {"family_id": version["family_id"], "versions": 0, "authors": set()},
        )
        entry["versions"] += 1
        if version.get("author_email"):
            entry["authors"].add(version["author_email"])
        if entry.get("seq", -1) < version.get("seq", 0):
            entry.update(seq=version.get("seq"), version_id=version.get("version_id"))
    titles = {
        str(d["dashboard_id"]): d.get("title") or ""
        for d in dashboards_collection.find(
            {"dashboard_id": {"$in": [ObjectId(f) for f in families if ObjectId.is_valid(f)]}},
            {"dashboard_id": 1, "title": 1},
        )
    }
    return [
        {**e, "authors": sorted(e["authors"]), "title": titles.get(e["family_id"], "")}
        for e in families.values()
        if e["family_id"] in titles
    ]


@changes_router.post("/project/{project_id}")
def project_changes_endpoint(
    project_id: str,
    body: ChangesRequest | None = None,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    _enabled()
    body = body or ChangesRequest()
    _require_project(project_id, current_user)
    now = bl.project_baseline(project_id)
    held = _server_held(current_user)
    if body.since is not None or body.before_run:
        base: ReaderBaseline | None = bl.rewind_baseline(
            now, None, since=body.since, before_run=body.before_run
        )
    elif held:
        mark = store.get_mark(str(current_user.id), "project", project_id)
        base = mark.baseline if mark else None
    else:
        base = body.baseline
    result = project_change_set(project_id, base, now, current_user)
    result["server_held"] = held
    if not held:
        result["current_baseline"] = _jsonable(now)
    return result


@changes_router.put("/project/{project_id}/visit")
def record_project_visit(
    project_id: str, current_user: User = Depends(get_user_or_anonymous)
) -> dict[str, Any]:
    _enabled()
    _require_project(project_id, current_user)
    if not _server_held(current_user):
        return {"persisted": False}
    user_id = str(current_user.id)
    mark = store.get_mark(user_id, "project", project_id)
    if mark is None or mark.baseline is None or store.get_mark_mode(user_id) == "previous_visit":
        store.set_baseline(
            user_id, "project", project_id, bl.project_baseline(project_id), visit=True
        )
        return {"persisted": True, "moved": True}
    store.touch_visit(user_id, "project", project_id)
    return {"persisted": True, "moved": False}


@changes_router.put("/project/{project_id}/seen")
def mark_project_seen(
    project_id: str, current_user: User = Depends(get_user_or_anonymous)
) -> dict[str, Any]:
    _enabled()
    _require_project(project_id, current_user)
    now = bl.project_baseline(project_id)
    if not _server_held(current_user):
        return {"persisted": False, "baseline": _jsonable(now)}
    store.set_baseline(str(current_user.id), "project", project_id, now, visit=False)
    return {"persisted": True}


@changes_router.get("/project/{project_id}/timeline")
def project_timeline(
    project_id: str,
    before: Optional[datetime] = None,
    types: Optional[str] = Query(
        default=None, description="Comma-separated: ingestion,version,comment"
    ),
    limit: int = Query(default=TIMELINE_LIMIT, ge=1, le=200),
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """One time-ordered list of what happened in a project, newest first."""
    _enabled()
    _require_project(project_id, current_user)
    wanted = {t.strip() for t in (types or "ingestion,version,comment").split(",") if t.strip()}
    time_filter: dict[str, Any] = {"$lt": before} if before else {"$exists": True}
    can_see_people = _project_permission(ObjectId(project_id), current_user, "editor")
    events: list[dict[str, Any]] = []

    if "ingestion" in wanted:
        for run in (
            ingestion_runs_collection.find(
                {"project_id": project_id, "started_at": time_filter},
                {
                    "run_id": 1,
                    "status": 1,
                    "started_at": 1,
                    "finished_at": 1,
                    "command": 1,
                    "trigger": 1,
                    "run_tags": 1,
                    "email": 1,
                    "data_collections.tag": 1,
                    "data_collections.rows_written": 1,
                },
            )
            .sort("started_at", -1)
            .limit(limit)
        ):
            events.append(
                {
                    "type": "ingestion",
                    "at": run.get("started_at"),
                    "id": run.get("run_id"),
                    "status": run.get("status"),
                    "command": run.get("command"),
                    "trigger": run.get("trigger"),
                    "run_tags": run.get("run_tags") or [],
                    "collections": [d.get("tag") for d in run.get("data_collections") or []],
                    "rows_written": sum(
                        int(d.get("rows_written") or 0) for d in run.get("data_collections") or []
                    ),
                    "by": run.get("email") if can_see_people else None,
                }
            )

    if "version" in wanted:
        families = {
            str(d["dashboard_id"]): d.get("title") or ""
            for d in dashboards_collection.find(
                {"project_id": ObjectId(project_id), "is_main_tab": {"$ne": False}},
                {"dashboard_id": 1, "title": 1},
            )
        }
        for version in (
            dashboard_versions_collection.find(
                {"project_id": project_id, "created_at": time_filter},
                {"tabs": 0, "data_collections": 0},
            )
            .sort("created_at", -1)
            .limit(limit)
        ):
            events.append(
                {
                    "type": "version",
                    "at": version.get("created_at"),
                    "id": version.get("version_id"),
                    "family_id": version.get("family_id"),
                    "dashboard_title": families.get(version.get("family_id"), ""),
                    "seq": version.get("seq"),
                    "kind": version.get("kind"),
                    "label": version.get("label"),
                    "component_count": version.get("component_count"),
                    "by": version.get("author_email"),
                }
            )

    if "comment" in wanted:
        readable, moderator = _comment_reader(ObjectId(project_id), current_user)
        if readable:
            statuses = ["open", "resolved", "proposed"] if moderator else ["open", "resolved"]
            for thread in (
                comment_threads_collection.find(
                    {
                        "project_id": project_id,
                        "status": {"$in": statuses},
                        "created_at": time_filter,
                    },
                    {
                        "anchor": 1,
                        "created_at": 1,
                        "created_by": 1,
                        "comments": {"$slice": 1},
                        "parent_dashboard_id": 1,
                    },
                )
                .sort("created_at", -1)
                .limit(limit)
            ):
                first = (thread.get("comments") or [{}])[0]
                events.append(
                    {
                        "type": "comment",
                        "at": thread.get("created_at"),
                        "id": str(thread.get("_id")),
                        "family_id": thread.get("parent_dashboard_id"),
                        "tab_id": (thread.get("anchor") or {}).get("dashboard_id"),
                        "component_title": (thread.get("anchor") or {}).get("component_title"),
                        "excerpt": (first.get("body") or "")[:160],
                        "by": (thread.get("created_by") or {}).get("email"),
                    }
                )

    events = [e for e in events if isinstance(e.get("at"), datetime)]
    events.sort(key=lambda e: e["at"], reverse=True)
    events = events[:limit]
    return {
        "events": [{**e, "at": e["at"].isoformat()} for e in events],
        "next_before": events[-1]["at"].isoformat() if len(events) == limit else None,
    }


# ── reader preferences and the bell ─────────────────────────────────────────


@changes_router.get("/prefs")
def get_prefs(current_user: User = Depends(get_user_or_anonymous)) -> dict[str, Any]:
    _enabled()
    held = _server_held(current_user)
    return {
        "mark_mode": store.get_mark_mode(str(current_user.id) if held else None),
        "default_mark_mode": store.default_mark_mode(),
        "server_held": held,
    }


@changes_router.put("/prefs")
def put_prefs(
    body: PrefsRequest, current_user: User = Depends(get_user_or_anonymous)
) -> dict[str, Any]:
    _enabled()
    if not _server_held(current_user):
        return {"persisted": False, "mark_mode": body.mark_mode}
    store.set_mark_mode(str(current_user.id), body.mark_mode)
    return {"persisted": True, "mark_mode": body.mark_mode}


@changes_router.get("/inbox")
def inbox(current_user: User = Depends(get_user_or_anonymous)) -> dict[str, Any]:
    """Per marked dashboard or project, a short summary of what is new. Signed-in readers only."""
    _enabled()
    if not _server_held(current_user):
        return {"items": [], "server_held": False}
    reader = _reader(current_user)
    items: list[dict[str, Any]] = []
    for mark in store.list_marks(str(current_user.id), limit=INBOX_LIMIT):
        if mark.baseline is None:
            continue
        try:
            item = _inbox_item(mark.scope_kind, mark.scope_id, mark.baseline, current_user, reader)
        except HTTPException:
            continue  # access revoked or scope deleted since the mark was written
        if item:
            items.append(item)
    items.sort(key=lambda i: i.get("at") or "", reverse=True)
    return {"items": items, "server_held": True}


def _inbox_item(
    scope_kind: str, scope_id: str, base: ReaderBaseline, user: User, reader: df.Reader
) -> dict[str, Any] | None:
    if scope_kind == "project":
        _require_project(scope_id, user)
        now = bl.project_baseline(scope_id)
        project = projects_collection.find_one({"_id": ObjectId(scope_id)}, {"name": 1}) or {}
        data = df.data_changes(base, now, bl.project_collections(scope_id), reader)
        runs = df.new_workflow_runs(base, now)
        title = project.get("name") or ""
        dashboard_versions = 0
    else:
        family_id, main, docs = _family(scope_id, user)
        now = bl.family_baseline(family_id, docs)
        data = df.data_changes(base, now, bl.project_collections(main.get("project_id")), reader)
        runs = []
        title = main.get("title") or ""
        dashboard_versions = dashboard_versions_collection.count_documents(
            {
                "family_id": family_id,
                "seq": {"$gt": base.version_seq if base.version_seq is not None else -1},
                "author_id": {"$ne": reader.user_id},
            }
        )
    new_run_tags = sorted(
        {t for d in data for t in d.get("new_run_tags") or []} | {r["run_tag"] for r in runs}
    )
    if not (data or runs or dashboard_versions):
        return None
    times = [d.get("at") for d in data if d.get("at")]
    return {
        "scope_kind": scope_kind,
        "scope_id": scope_id,
        "title": title,
        "new_run_tags": new_run_tags,
        "refreshed": [d.get("data_collection_tag") for d in data],
        "dashboard_versions": dashboard_versions,
        "at": max(times) if times else None,
    }


# ── one figure, before and after ────────────────────────────────────────────


class ComponentDiffRequest(ChangesRequest):
    """The change-set body, plus the filters the figure is drawn with."""

    filters: list[dict[str, Any]] = []


def _resolve_base(
    family_id: str, now: ReaderBaseline, body: ChangesRequest, user: User
) -> ReaderBaseline | None:
    if body.since is not None or body.before_run:
        return bl.rewind_baseline(now, family_id, since=body.since, before_run=body.before_run)
    if _server_held(user):
        mark = store.get_mark(str(user.id), "dashboard", family_id)
        return mark.baseline if mark else None
    return body.baseline


def _live_component(
    docs: list[dict[str, Any]], component_id: str
) -> tuple[str, dict[str, Any]] | None:
    for tab_id, component in bl.family_components(docs):
        if str(component.get("index")) == component_id:
            return tab_id, component
    return None


def _component_in_version(version_id: str | None, tab_id: str, index: str) -> dict[str, Any] | None:
    if not version_id:
        return None
    record = dashboard_versions_collection.find_one(
        {"version_id": version_id}, {"tabs": {"$elemMatch": {"dashboard_id": tab_id}}}
    )
    for tab in (record or {}).get("tabs") or []:
        for component in tab.get("stored_metadata") or []:
            if str(component.get("index")) == index:
                return component
    return None


def _figure_columns(component: dict[str, Any], dc_id: str) -> list[str] | None:
    """The columns a figure diff reads: its encodings and any row-naming column."""
    from depictio.api.v1.services.changes.figure_diff import _ID_NAMES

    aggs = bl.aggregations_of(dc_id)
    known = [
        c.get("name")
        for c in ((aggs[-1] if aggs else {}).get("aggregation_columns_specs") or [])
        if c.get("name")
    ]
    if not known:
        return None
    kwargs = component.get("dict_kwargs") or {}
    wanted = {
        kwargs.get("x"),
        kwargs.get("y"),
        kwargs.get("color"),
        kwargs.get("hover_name"),
        component.get("selection_column"),
        *_ID_NAMES,
    }
    wanted |= {c for c in known if c.lower().endswith(("_id", "_index"))}
    return [c for c in known if c in wanted]


@changes_router.post("/component_diff/{dashboard_id}/{component_id}")
def component_diff(
    dashboard_id: str,
    component_id: str,
    body: ComponentDiffRequest | None = None,
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, Any]:
    """Which points, bars or samples of one component changed since the baseline.

    The live definition is used for both sides so the comparison is about the
    data; ``definition_changed`` says when the reader saw another definition
    (the side-by-side view shows that one).
    """
    from depictio.api.v1.services.changes import figure_diff as fd

    _enabled()
    body = body or ComponentDiffRequest()
    family_id, main, docs = _family(dashboard_id, current_user)
    found = _live_component(docs, component_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Component not found.")
    tab_id, component = found
    now = bl.family_baseline(family_id, docs)
    base = _resolve_base(family_id, now, body, current_user)
    if base is None:
        return fd.unsupported("Nothing to compare on a first visit.")

    before_def = _component_in_version(base.version_id, tab_id, component_id)
    dc_id = str(component.get("dc_id") or "")
    state_before = base.dc_states.get(dc_id)
    state_now = now.dc_states.get(dc_id)
    meta = {
        "component_key": component_key(tab_id, component_id),
        "baseline_version_id": base.version_id,
        "definition_changed": before_def is not None
        and df.definition_fingerprint(before_def) != df.definition_fingerprint(component),
        "since": base.seen_at.isoformat(),
    }
    if state_before is None or state_now is None:
        return {
            **fd.unsupported("This collection was not on the dashboard at the baseline."),
            **meta,
        }

    component_type = component.get("component_type")
    if component_type == "multiqc" or state_now.dc_type == "multiqc":
        samples_now: set[str] = set()
        reports_then: set[str] = set()
        for report in bl.multiqc_reports_of(dc_id):
            names = bl.report_samples(report)
            samples_now |= names
            if state_before.multiqc_reports.get(bl.report_identity(report)) == bl.report_signature(
                report
            ):
                reports_then |= names
        samples_then = set(state_before.samples) if state_before.samples_complete else reports_then
        return {**fd.sample_diff(samples_then, samples_now), **meta}

    if component_type == "advanced_viz":
        from depictio.api.v1.services.changes.advanced_diff import advanced_viz_diff

        return {
            **advanced_viz_diff(component, dc_id, state_before, state_now, body.filters),
            **meta,
        }

    if component_type != "figure":
        return {**fd.unsupported(f"{component_type} components have no before/after view."), **meta}
    if state_before.delta_version is None or state_now.delta_version is None:
        return {**fd.unsupported("This collection keeps no version history."), **meta}
    if state_before.delta_version == state_now.delta_version:
        return {
            **fd.frame_diff(pl.DataFrame(), pl.DataFrame(), component),
            **meta,
            "unchanged": True,
        }

    from depictio.api.v1.deltatables_utils import load_deltatable_lite
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _build_filter_metadata,
        _resolve_link_filters_cached,
    )

    filters = _resolve_link_filters_cached(
        body.filters, dc_id, main.get("project_id"), access_token, "figure"
    )
    metadata = _build_filter_metadata(filters)
    columns = _figure_columns(component, dc_id)
    wf_id = ObjectId(str(component.get("wf_id")))

    def frame(version: int) -> pl.DataFrame:
        return load_deltatable_lite(
            wf_id, dc_id, metadata=metadata, select_columns=columns, delta_version=version
        )

    try:
        before, after = frame(state_before.delta_version), frame(state_now.delta_version)
    except Exception as exc:
        return {**fd.unsupported(f"The data could not be read: {exc}"), **meta}
    return {
        **fd.frame_diff(before, after, component),
        **meta,
        "delta_from": state_before.delta_version,
        "delta_to": state_now.delta_version,
    }
