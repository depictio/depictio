"""What changed between a reader's baseline and now.

Three groups, as the reader thinks of them: **data** (collections refreshed,
new runs, new samples), **dashboard** (components and tabs added, edited or
removed, with who and in which version) and **comments**.

A reader's own changes are not news to them and are left out: dashboard
versions they authored, ingestions they ran, comments they wrote.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from depictio.api.v1.db import (
    comment_threads_collection,
    dashboard_versions_collection,
    ingestion_runs_collection,
    runs_collection,
)
from depictio.api.v1.endpoints.dashboards_endpoints import schema_integrity
from depictio.api.v1.services.changes import baseline as bl
from depictio.models.models.comments import component_fingerprint
from depictio.models.models.reader_marks import (
    DcSeenState,
    DismissedComponent,
    ReaderBaseline,
    component_key,
)

#: Versions walked to attribute changes. Past this the attribution is partial
#: (the net change is still exact: it compares the baseline with the live state).
MAX_VERSIONS_WALKED = 100
MAX_ITEMS_PER_GROUP = 200

#: Component keys that say where a tile sits, not what it shows. Moving a
#: tile is not a change worth a mark.
_PLACEMENT_KEYS = frozenset(
    {"layout", "last_updated", "parent_index", "section", "group", "panel", "placement", "fit"}
)


class Reader:
    """Who is asking, for self-exclusion."""

    def __init__(self, user_id: str | None, email: str | None) -> None:
        self.user_id = str(user_id) if user_id else None
        self.email = (email or "").lower() or None

    def wrote(self, *, user_id: Any = None, email: Any = None) -> bool:
        if self.user_id and user_id and str(user_id) == self.user_id:
            return True
        return bool(self.email and email and str(email).lower() == self.email)


def definition_fingerprint(component: dict[str, Any] | None) -> str | None:
    if not component:
        return None
    return component_fingerprint({k: v for k, v in component.items() if k not in _PLACEMENT_KEYS})


def _title(component: dict[str, Any]) -> str:
    for key in ("title", "card_title", "label", "column_name", "selected_plot"):
        value = component.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(component.get("component_type") or "component")


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else (str(value) if value else None)


# ── dashboard definition ────────────────────────────────────────────────────


def _tabs_state(tabs: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """``tab_id -> {title, components: {index: component}}``."""
    out: dict[str, dict[str, Any]] = {}
    for tab in tabs:
        tab_id = str(tab.get("dashboard_id") or tab.get("_id"))
        components = {}
        for component in tab.get("stored_metadata") or []:
            if isinstance(component, dict) and component.get("index"):
                components[str(component["index"])] = component
        out[tab_id] = {"title": tab.get("title") or "", "components": components}
    return out


def _version_tabs(version_id: str) -> list[dict[str, Any]] | None:
    record = dashboard_versions_collection.find_one(
        {"version_id": version_id},
        {"tabs.dashboard_id": 1, "tabs.title": 1, "tabs.stored_metadata": 1},
    )
    return None if record is None else list(record.get("tabs") or [])


def _start_version(family_id: str, base: ReaderBaseline) -> tuple[dict[str, Any] | None, bool]:
    """The version the baseline saw, or the closest survivor (then ``approximate``)."""
    if base.version_id:
        record = dashboard_versions_collection.find_one(
            {"version_id": base.version_id, "family_id": str(family_id)}, {"tabs": 0}
        )
        if record:
            return record, False
    if base.version_seq is not None:
        record = dashboard_versions_collection.find_one(
            {"family_id": str(family_id), "seq": {"$lte": base.version_seq}},
            {"tabs": 0},
            sort=[("seq", DESCENDING)],
        )
        if record:
            return record, True
    # The reader saw the family before it had any version. The first version
    # recorded after that is the "Before first tracked change" baseline the
    # editor seeds, i.e. what the reader saw.
    record = dashboard_versions_collection.find_one(
        {"family_id": str(family_id), "created_at": {"$gte": base.seen_at}},
        {"tabs": 0},
        sort=[("seq", ASCENDING)],
    )
    return record, record is not None and base.version_id is not None


def dashboard_changes(
    family_id: str,
    base: ReaderBaseline,
    live_docs: list[dict[str, Any]],
    reader: Reader,
) -> tuple[list[dict[str, Any]], set[str], bool]:
    """Definition changes, the keys of changed components, and ``approximate``."""
    start, approximate = _start_version(family_id, base)
    if start is None:
        return [], set(), False
    start_tabs = _version_tabs(start["version_id"]) or []
    before = _tabs_state(start_tabs)
    now = _tabs_state(live_docs)

    # Walk the versions after the start to learn who changed what, and when.
    authors: dict[str, dict[str, Any]] = {}
    prev = before
    cursor = (
        dashboard_versions_collection.find(
            {"family_id": str(family_id), "seq": {"$gt": start.get("seq", 0)}},
            {
                "version_id": 1,
                "seq": 1,
                "author_id": 1,
                "author_email": 1,
                "updated_at": 1,
                "created_at": 1,
                "tabs.dashboard_id": 1,
                "tabs.title": 1,
                "tabs.stored_metadata": 1,
            },
        )
        .sort("seq", ASCENDING)
        .limit(MAX_VERSIONS_WALKED)
    )
    for version in cursor:
        state = _tabs_state(version.get("tabs") or [])
        touched = _touched_keys(prev, state)
        for key in touched:
            entry = authors.setdefault(key, {"authors": {}, "self_only": True})
            email = version.get("author_email")
            is_self = reader.wrote(user_id=version.get("author_id"), email=email)
            if not is_self:
                entry["self_only"] = False
                if email:
                    entry["authors"][email] = True
            entry["version_id"] = version.get("version_id")
            entry["seq"] = version.get("seq")
            entry["at"] = _iso(version.get("updated_at") or version.get("created_at"))
        prev = state

    changes: list[dict[str, Any]] = []
    changed_keys: set[str] = set()
    net = _touched_keys(before, now)
    for key in sorted(net):
        info = authors.get(key)
        if info and info["self_only"]:
            continue
        kind, tab_id, index = key.split("|", 2)
        tab_now = now.get(tab_id) or {}
        tab_before = before.get(tab_id) or {}
        item: dict[str, Any] = {
            "kind": kind,
            "tab_id": tab_id,
            "tab_title": tab_now.get("title") or tab_before.get("title") or "",
            "authors": sorted((info or {}).get("authors", {}).keys()),
            "version_id": (info or {}).get("version_id"),
            "seq": (info or {}).get("seq"),
            "at": (info or {}).get("at"),
        }
        if index:
            component = (tab_now.get("components") or {}).get(index) or (
                tab_before.get("components") or {}
            ).get(index)
            item.update(
                component_index=index,
                component_type=(component or {}).get("component_type"),
                component_title=_title(component or {}),
                key=component_key(tab_id, index),
            )
            if kind != "component_removed":
                changed_keys.add(component_key(tab_id, index))
        changes.append(item)
    return changes[:MAX_ITEMS_PER_GROUP], changed_keys, approximate


def _touched_keys(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    """``kind|tab_id|index`` for every tab and component that differs."""
    keys: set[str] = set()
    for tab_id in set(before) | set(after):
        b, a = before.get(tab_id), after.get(tab_id)
        if b is None:
            keys.add(f"tab_added|{tab_id}|")
            continue
        if a is None:
            keys.add(f"tab_removed|{tab_id}|")
            continue
        if (b.get("title") or "") != (a.get("title") or ""):
            keys.add(f"tab_renamed|{tab_id}|")
        bc, ac = b["components"], a["components"]
        for index in set(bc) | set(ac):
            if index not in bc:
                keys.add(f"component_added|{tab_id}|{index}")
            elif index not in ac:
                keys.add(f"component_removed|{tab_id}|{index}")
            elif definition_fingerprint(bc[index]) != definition_fingerprint(ac[index]):
                keys.add(f"component_edited|{tab_id}|{index}")
    return keys


# ── data ────────────────────────────────────────────────────────────────────


def _ingestion_authors(run_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    ids = [r for r in set(run_ids) if r]
    if not ids:
        return {}
    return {
        doc["run_id"]: doc
        for doc in ingestion_runs_collection.find(
            {"run_id": {"$in": ids}}, {"run_id": 1, "user_id": 1, "email": 1, "status": 1}
        )
    }


def _delta_change(dc_id: str, before: DcSeenState, reader: Reader) -> dict[str, Any] | None:
    aggregations = bl.aggregations_of(dc_id)
    if before.delta_version is not None:
        newer = [
            a
            for a in aggregations
            if a.get("delta_version") is not None and a["delta_version"] > before.delta_version
        ]
    else:
        floor = before.aggregation_version or 0
        newer = [a for a in aggregations if (a.get("aggregation_version") or 0) > floor]
    if not newer:
        return None

    runs = _ingestion_authors(a.get("ingestion_run_id") for a in newer)

    def by_reader(agg: dict[str, Any]) -> bool:
        run = runs.get(agg.get("ingestion_run_id") or "")
        if run is not None:
            return reader.wrote(user_id=run.get("user_id"), email=run.get("email"))
        by = agg.get("aggregation_by") or {}
        return reader.wrote(user_id=by.get("id") or by.get("_id"), email=by.get("email"))

    others = [a for a in newer if not by_reader(a)]
    if not others:
        return None

    tags = sorted({t for a in newer for t in a.get("run_tags") or [] if t})
    known = set(before.run_tags)
    rows_after = newer[-1].get("rows_total")
    return {
        "kind": "emptied" if rows_after == 0 else "refreshed",
        "new_run_tags": [t for t in tags if t not in known],
        "touched_run_tags": tags,
        "rows_before": before.row_count,
        "rows_after": rows_after,
        "rows_added": sum(int(a.get("rows_added") or 0) for a in newer),
        "commits": len(newer),
        "delta_from": before.delta_version,
        "delta_to": newer[-1].get("delta_version"),
        "ingestion_run_ids": sorted(
            {a["ingestion_run_id"] for a in newer if a.get("ingestion_run_id")}
        ),
        "by": sorted({(a.get("aggregation_by") or {}).get("email") for a in others} - {None}),
        "at": _iso(newer[-1].get("delta_commit_timestamp") or newer[-1].get("aggregation_time")),
    }


def _report_run_tag(report: dict[str, Any]) -> str | None:
    """Reports ingested since run tags were recorded carry one. Older ones are
    not new to any reader, so they never need a fallback here."""
    return report.get("run_tag") or None


def _multiqc_change(dc_id: str, before: DcSeenState, reader: Reader) -> dict[str, Any] | None:
    reports = bl.multiqc_reports_of(dc_id)
    now = {str(r["_id"]): r for r in reports}
    seen = before.multiqc_reports
    added = [r for k, r in now.items() if k not in seen]
    refreshed = [
        r for k, r in now.items() if k in seen and bl._iso(r.get("processed_at")) != seen[k]
    ]
    removed = [k for k in seen if k not in now]
    if not (added or refreshed or removed):
        return None

    runs = _ingestion_authors(r.get("ingestion_run_id") for r in added + refreshed)
    changed = added + refreshed
    others = [
        r
        for r in changed
        if not (
            r.get("ingestion_run_id") in runs
            and reader.wrote(
                user_id=runs[r["ingestion_run_id"]].get("user_id"),
                email=runs[r["ingestion_run_id"]].get("email"),
            )
        )
    ]
    if not others and not removed:
        return None

    unchanged_samples: set[str] = set()
    for key, report in now.items():
        if report in changed:
            continue
        unchanged_samples.update(
            str(s) for s in (report.get("metadata") or {}).get("samples") or []
        )
    new_samples: set[str] = set()
    for report in changed:
        new_samples.update(str(s) for s in (report.get("metadata") or {}).get("samples") or [])
    new_samples -= unchanged_samples

    known = set(before.run_tags)
    added_tags = sorted({t for t in (_report_run_tag(r) for r in added) if t})
    return {
        "kind": "refreshed",
        "new_run_tags": [t for t in added_tags if t not in known],
        "touched_run_tags": sorted({t for t in (_report_run_tag(r) for r in changed) if t}),
        "reports_added": len(added),
        "reports_refreshed": len(refreshed),
        "reports_removed": len(removed),
        "new_samples": sorted(new_samples)[:200],
        "new_sample_count": len(new_samples),
        "ingestion_run_ids": sorted(
            {r["ingestion_run_id"] for r in changed if r.get("ingestion_run_id")}
        ),
        "by": sorted(
            {
                runs[r["ingestion_run_id"]].get("email")
                for r in others
                if r.get("ingestion_run_id") in runs
            }
            - {None}
        ),
        "at": max((bl._iso(r.get("processed_at")) for r in changed), default=None),
    }


def data_changes(
    base: ReaderBaseline,
    now: ReaderBaseline,
    collections: dict[str, dict[str, Any]],
    reader: Reader,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for dc_id, state_now in now.dc_states.items():
        before = base.dc_states.get(dc_id)
        if before is None:
            # Newly referenced: the component that reads it is the news.
            continue
        if state_now.dc_type == "multiqc" or before.multiqc_reports:
            change = _multiqc_change(dc_id, before, reader)
        else:
            change = _delta_change(dc_id, before, reader)
        if change is None:
            continue
        info = collections.get(dc_id, {})
        change.update(
            dc_id=dc_id,
            dc_type=state_now.dc_type,
            workflow_tag=info.get("workflow_tag", ""),
            data_collection_tag=info.get("data_collection_tag", ""),
        )
        out.append(change)
    return out


def failed_ingestions(
    project_id: Any, base: ReaderBaseline, reader: Reader
) -> list[dict[str, Any]]:
    """Ingestions after the baseline that failed or partly failed."""
    if base.ingestion_cursor_at is None:
        return []
    out = []
    for run in ingestion_runs_collection.find(
        {
            "project_id": str(project_id),
            "started_at": {"$gt": base.ingestion_cursor_at},
            "status": {"$in": ["failed", "partial", "interrupted"]},
        },
        {
            "run_id": 1,
            "status": 1,
            "user_id": 1,
            "email": 1,
            "started_at": 1,
            "run_tags": 1,
            "data_collections.tag": 1,
        },
    ).limit(20):
        if reader.wrote(user_id=run.get("user_id"), email=run.get("email")):
            continue
        out.append(
            {
                "run_id": run.get("run_id"),
                "status": run.get("status"),
                "run_tags": run.get("run_tags") or [],
                "data_collection_tags": [d.get("tag") for d in run.get("data_collections") or []],
                "at": _iso(run.get("started_at")),
            }
        )
    return out


def new_workflow_runs(base: ReaderBaseline, now: ReaderBaseline) -> list[dict[str, Any]]:
    out = []
    for wf_id, tags in now.workflow_runs.items():
        known = set(base.workflow_runs.get(wf_id, []))
        for tag in tags:
            if tag in known:
                continue
            run = (
                runs_collection.find_one(
                    {"workflow_id": ObjectId(wf_id), "run_tag": tag},
                    {"run_location": 1, "registration_time": 1},
                )
                or {}
            )
            out.append(
                {
                    "workflow_id": wf_id,
                    "run_tag": tag,
                    "run_location": run.get("run_location"),
                    "registered": run.get("registration_time"),
                }
            )
    return out


# ── comments ────────────────────────────────────────────────────────────────


def comment_changes(
    family_id: str, base: ReaderBaseline, reader: Reader, *, moderator: bool
) -> list[dict[str, Any]]:
    cursor_at = base.comment_cursor_at or base.seen_at
    statuses = ["open", "resolved", "proposed"] if moderator else ["open", "resolved"]
    out: list[dict[str, Any]] = []
    for thread in comment_threads_collection.find(
        {
            "parent_dashboard_id": str(family_id),
            "status": {"$in": statuses},
            "$or": [
                {"created_at": {"$gt": cursor_at}},
                {"comments.created_at": {"$gt": cursor_at}},
            ],
        }
    ).limit(MAX_ITEMS_PER_GROUP):
        anchor = thread.get("anchor") or {}
        base_item = {
            "thread_id": str(thread.get("_id")),
            "tab_id": anchor.get("dashboard_id"),
            "component_index": anchor.get("component_index"),
            "component_title": anchor.get("component_title"),
            "number": thread.get("number"),
        }
        comments = [c for c in thread.get("comments") or [] if not c.get("deleted")]
        for i, comment in enumerate(comments):
            created = comment.get("created_at")
            if not isinstance(created, datetime) or created <= cursor_at:
                continue
            author = comment.get("author") or {}
            if reader.wrote(user_id=author.get("user_id"), email=author.get("email")):
                continue
            out.append(
                {
                    **base_item,
                    "kind": "thread" if i == 0 else "reply",
                    "author": author.get("email") or (author.get("agent") or {}).get("name"),
                    "at": _iso(created),
                    "excerpt": (comment.get("body") or "")[:160],
                }
            )
    out.sort(key=lambda c: c.get("at") or "")
    return out


# ── marks on the canvas ─────────────────────────────────────────────────────


def components_reading(
    live_docs: list[dict[str, Any]], dc_ids: set[str]
) -> dict[str, dict[str, Any]]:
    """``key -> component`` for every live component reading one of ``dc_ids``."""
    out = {}
    for tab_id, component in bl.family_components(live_docs):
        dc_id = schema_integrity.component_dc_id(component)
        if dc_id in dc_ids and component.get("index"):
            out[component_key(tab_id, str(component["index"]))] = component
    return out


def apply_dismissals(
    marked: dict[str, list[str]],
    live_docs: list[dict[str, Any]],
    now: ReaderBaseline,
    dismissed: dict[str, DismissedComponent],
) -> dict[str, list[str]]:
    """Drop the marks a reader dismissed while the component is still as they left it."""
    if not dismissed:
        return marked
    live = {
        component_key(tab_id, str(c["index"])): c
        for tab_id, c in bl.family_components(live_docs)
        if c.get("index")
    }
    out = {}
    for key, reasons in marked.items():
        entry = dismissed.get(key)
        component = live.get(key)
        if entry and component is not None:
            dc_id = schema_integrity.component_dc_id(component)
            same_def = entry.fingerprint == definition_fingerprint(component)
            same_data = entry.data_token == bl.data_token(now.dc_states.get(dc_id or ""))
            if same_def and same_data:
                continue
        out[key] = reasons
    return out


def dismissal_for(component: dict[str, Any], now: ReaderBaseline) -> DismissedComponent:
    dc_id = schema_integrity.component_dc_id(component)
    return DismissedComponent(
        fingerprint=definition_fingerprint(component),
        data_token=bl.data_token(now.dc_states.get(dc_id or "")),
    )
