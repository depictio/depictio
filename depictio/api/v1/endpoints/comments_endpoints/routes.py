"""Comment threads and annotations pinned to dashboard components.

Threads are internal to a project's editors and owners: every route below goes
through ``_require_dashboard_editor`` on the thread's tab, except ``/access``
(never raises, answers whether the caller may comment) and ``/published``
(viewer level, shapes and labels only, never the discussion).

Storage (``comment_threads`` collection): one document per thread, ``_id`` an
ObjectId, everything else the :class:`CommentThread` fields. ``project_id``,
``parent_dashboard_id`` (the main tab of the family) and ``anchor.dashboard_id``
are stored as **strings**, as are all user ids; queries and cascades
stringify ids before matching. ``dedupe_key`` and ``run_id`` are left out of the
document when unset so their sparse indexes stay small.

Staleness is computed at read time against the tab as it is now, never stored.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import ValidationError
from pymongo import ReturnDocument

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import comment_threads_collection, dashboards_collection
from depictio.api.v1.deltatables_utils import _get_aggregation_hash
from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
    _require_dashboard_editor,
    check_project_permission,
)
from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_user_or_anonymous,
    oauth2_scheme_optional,
)
from depictio.models.models.comments import (
    MAX_COMMENTS_PER_THREAD,
    Annotation,
    Author,
    Comment,
    CommentAccess,
    CommentCreate,
    CommentThread,
    CommentUpdate,
    PublishedAnnotation,
    Review,
    Staleness,
    ThreadCreate,
    ThreadOut,
    ThreadReview,
    ThreadStatus,
    ThreadUpdate,
    component_fingerprint,
    utcnow,
)
from depictio.models.models.users import User

comments_endpoint_router = APIRouter()

MAX_THREADS_PER_RUN = 50
TAB_KEY = "__tab__"
"""Key standing for the tab itself (``component_index`` None) in counts and filters."""

# Component keys that point at a data collection the component reads.
_DC_KEYS = ("dc_id", "geojson_dc_id")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _oid(value: str, what: str = "Thread") -> ObjectId:
    """The ObjectId for a path id, or a 404 (a malformed id names nothing)."""
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=404, detail=f"{what} not found.")
    return ObjectId(value)


def _utc(value: Any) -> Any:
    """Attach UTC to the naive datetimes pymongo hands back, recursively."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, dict):
        return {k: _utc(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_utc(v) for v in value]
    return value


def _to_thread(doc: dict) -> CommentThread:
    data = _utc({k: v for k, v in doc.items() if k != "_id"})
    data["id"] = str(doc["_id"])
    return CommentThread.model_validate(data)


def _to_storage(thread: CommentThread) -> dict:
    """The Mongo document for a thread (``id`` becomes ``_id``)."""
    doc = thread.model_dump(mode="python", exclude={"id"})
    for sparse_key in ("dedupe_key", "run_id"):
        if doc.get(sparse_key) is None:
            doc.pop(sparse_key, None)
    doc["_id"] = ObjectId(thread.id)
    return doc


def _main_tab_id(dashboard: dict) -> str:
    if dashboard.get("is_main_tab", True) is False and dashboard.get("parent_dashboard_id"):
        return str(dashboard["parent_dashboard_id"])
    return str(dashboard["dashboard_id"])


def _components_by_index(dashboard: dict | None) -> dict[str, dict]:
    if not dashboard:
        return {}
    return {
        str(c.get("index")): c
        for c in dashboard.get("stored_metadata") or []
        if isinstance(c, dict) and c.get("index") is not None
    }


def _component_dc_ids(component: dict) -> list[str]:
    return [str(component[k]) for k in _DC_KEYS if component.get(k)]


class _HashCache:
    """Per-request cache of the latest aggregation hash of each data collection."""

    def __init__(self) -> None:
        self._hashes: dict[str, str | None] = {}

    def get(self, dc_id: str) -> str | None:
        if dc_id not in self._hashes:
            # ``_get_aggregation_hash`` returns "" for a DC with no hash yet.
            self._hashes[dc_id] = _get_aggregation_hash(dc_id) or None
        return self._hashes[dc_id]


def _data_hashes(component: dict, cache: _HashCache) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for dc_id in _component_dc_ids(component):
        h = cache.get(dc_id)
        if h:
            hashes[dc_id] = h
    return hashes


def _staleness(thread: CommentThread, tab: dict | None, cache: _HashCache) -> Staleness:
    anchor = thread.anchor
    if anchor.component_index is None:
        return Staleness(component_missing=tab is None)
    component = _components_by_index(tab).get(anchor.component_index)
    if component is None:
        return Staleness(component_missing=True)
    changed = anchor.component_hash is not None and (
        component_fingerprint(component) != anchor.component_hash
    )
    data_changed = False
    for dc_id, recorded in anchor.data_hashes.items():
        current = cache.get(dc_id)
        if current is not None and current != recorded:
            data_changed = True
            break
    return Staleness(component_changed=changed, data_changed=data_changed)


def _reattach(thread: CommentThread, tab: dict | None, *, persist: bool = True) -> CommentThread:
    """Point a thread whose component index vanished at its component again, by title.

    A YAML import regenerates component indexes, so a thread on a component
    that is still there looks orphaned. When exactly one component of the tab
    carries the anchor's (non-empty) ``component_title``, the thread moves to
    it: the new index is persisted and returned. No match or several matches
    leave the thread alone (it reads as ``component_missing``).

    ``persist=False`` answers with the new index without writing it: viewer
    reads (``/published``) never write.
    """
    anchor = thread.anchor
    if anchor.component_index is None or not anchor.component_title or tab is None:
        return thread
    components = _components_by_index(tab)
    if anchor.component_index in components:
        return thread
    matches = [idx for idx, c in components.items() if c.get("title") == anchor.component_title]
    if len(matches) != 1:
        return thread
    new_index = matches[0]
    moved = thread.model_copy(
        update={"anchor": anchor.model_copy(update={"component_index": new_index})}
    )
    if not persist:
        return moved
    try:
        comment_threads_collection.update_one(
            {"_id": ObjectId(thread.id), "anchor.component_index": anchor.component_index},
            {"$set": {"anchor.component_index": new_index}},
        )
        logger.info(
            f"comments: thread {thread.id} re-attached from {anchor.component_index} "
            f"to {new_index} by title"
        )
    except Exception as exc:  # noqa: BLE001 — the read still answers with the new index
        logger.warning(f"comments: failed to persist re-attachment of {thread.id}: {exc}")
    return moved


def _out(thread: CommentThread, tab: dict | None, cache: _HashCache | None = None) -> ThreadOut:
    return ThreadOut(
        **thread.model_dump(),
        staleness=_staleness(thread, tab, cache or _HashCache()),
    )


def _thread_out(doc: dict) -> ThreadOut:
    """A freshly written thread, with its staleness against its tab."""
    thread = _to_thread(doc)
    tab = dashboards_collection.find_one(
        {"dashboard_id": ObjectId(thread.anchor.dashboard_id)}, {"stored_metadata": 1}
    )
    return _out(_reattach(thread, tab), tab)


def _load_thread(thread_id: str, current_user: User) -> tuple[CommentThread, dict]:
    """The thread and its tab, once the caller is known to be an editor of it."""
    doc = comment_threads_collection.find_one({"_id": _oid(thread_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Thread not found.")
    thread = _to_thread(doc)
    dashboard = _require_dashboard_editor(
        _oid(thread.anchor.dashboard_id, "Dashboard"),  # type: ignore[arg-type]
        current_user,
    )
    return thread, dashboard


def _update_thread(thread_id: str, update: dict) -> ThreadOut:
    update.setdefault("$set", {})["updated_at"] = utcnow()
    doc = comment_threads_collection.find_one_and_update(
        {"_id": ObjectId(thread_id)}, update, return_document=ReturnDocument.AFTER
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Thread not found.")
    return _thread_out(doc)


def _human(current_user: User) -> Author:
    return Author(kind="human", user_id=str(current_user.id), email=current_user.email)


def _is_project_owner(project_id: Any, current_user: User) -> bool:
    return bool(project_id) and check_project_permission(project_id, current_user, "owner")


def _find_comment(thread: CommentThread, comment_id: str) -> Comment:
    for comment in thread.comments:
        if comment.id == comment_id:
            return comment
    raise HTTPException(status_code=404, detail="Comment not found.")


def _set_comment_fields(thread_id: str, comment_id: str, fields: dict[str, Any]) -> ThreadOut:
    """Set fields of one comment (and stamp ``edited_at``), then return the thread.

    ``update_one`` + ``find_one`` rather than ``find_one_and_update``: the
    positional ``$`` operator is applied correctly by both mongod and mongomock
    only through ``update_one``.
    """
    now = utcnow()
    update = {f"comments.$.{k}": v for k, v in fields.items()}
    update.update({"comments.$.edited_at": now, "updated_at": now})
    result = comment_threads_collection.update_one(
        {"_id": ObjectId(thread_id), "comments.id": comment_id}, {"$set": update}
    )
    doc = comment_threads_collection.find_one({"_id": ObjectId(thread_id)})
    if not result.matched_count or not doc:
        raise HTTPException(status_code=404, detail="Comment not found.")
    return _thread_out(doc)


def _next_annotation_number(dashboard_id: str) -> int:
    last = comment_threads_collection.find_one(
        {"anchor.dashboard_id": dashboard_id, "annotation": {"$ne": None}},
        {"number": 1},
        sort=[("number", -1)],
    )
    return int((last or {}).get("number") or 0) + 1


async def _optional_user(
    token: str | None = Depends(oauth2_scheme_optional),
) -> User | None:
    """The caller, or None when there is no usable session (``/access`` never 401s)."""
    try:
        return await get_user_or_anonymous(token)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# Access and reads
# ---------------------------------------------------------------------------
@comments_endpoint_router.get("/access/{dashboard_id}", response_model=CommentAccess)
async def get_comment_access(
    dashboard_id: str,
    current_user: User | None = Depends(_optional_user),
) -> CommentAccess:
    """Whether the caller may read and write threads on this tab. Never raises."""
    if current_user is None or not ObjectId.is_valid(dashboard_id):
        return CommentAccess(can_comment=False)
    if getattr(current_user, "is_anonymous", False) and not settings.auth.is_single_user_mode:
        return CommentAccess(can_comment=False)
    try:
        dashboard = dashboards_collection.find_one(
            {"dashboard_id": ObjectId(dashboard_id)}, {"project_id": 1}
        )
        project_id = (dashboard or {}).get("project_id")
        allowed = bool(project_id) and check_project_permission(project_id, current_user, "editor")
    except Exception as exc:  # noqa: BLE001 — an access probe must not fail
        logger.warning(f"comments: access check failed for {dashboard_id}: {exc}")
        allowed = False
    return CommentAccess(can_comment=allowed)


@comments_endpoint_router.get("/dashboard/{dashboard_id}", response_model=list[ThreadOut])
async def list_threads(
    dashboard_id: str,
    scope: Literal["tab", "family"] = "tab",
    component_index: str | None = Query(
        default=None, description=f"Only this component's threads; '{TAB_KEY}' for the tab's own."
    ),
    status: ThreadStatus | None = None,
    current_user: User = Depends(get_user_or_anonymous),
) -> list[ThreadOut]:
    """Threads of a tab (``scope=tab``) or of every tab of its dashboard (``family``).

    Rejected threads are hidden unless ``status=rejected`` is asked for.
    """
    dashboard = _require_dashboard_editor(_oid(dashboard_id, "Dashboard"), current_user)  # type: ignore[arg-type]

    query: dict[str, Any] = {}
    if scope == "family":
        main_id = _main_tab_id(dashboard)
        query["parent_dashboard_id"] = main_id
        tabs = {
            str(d["dashboard_id"]): d
            for d in dashboards_collection.find(
                {
                    "$or": [
                        {"dashboard_id": ObjectId(main_id)},
                        {"parent_dashboard_id": ObjectId(main_id)},
                    ]
                },
                {"dashboard_id": 1, "stored_metadata": 1},
            )
        }
    else:
        query["anchor.dashboard_id"] = str(dashboard["dashboard_id"])
        tabs = {str(dashboard["dashboard_id"]): dashboard}

    query["status"] = status if status is not None else {"$ne": "rejected"}

    threads = [
        _reattach(t, tabs.get(t.anchor.dashboard_id))
        for t in map(_to_thread, comment_threads_collection.find(query))
    ]
    # Filtered after re-attachment, so a thread moved by title lands on its new component.
    if component_index is not None:
        wanted = None if component_index == TAB_KEY else component_index
        threads = [t for t in threads if t.anchor.component_index == wanted]
    threads.sort(key=lambda t: t.created_at)
    cache = _HashCache()
    return [_out(t, tabs.get(t.anchor.dashboard_id), cache) for t in threads]


@comments_endpoint_router.get("/counts/{dashboard_id}")
async def count_threads(
    dashboard_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, dict[str, int]]:
    """Open and proposed threads of a tab, per component index (``__tab__`` for the tab)."""
    dashboard = _require_dashboard_editor(_oid(dashboard_id, "Dashboard"), current_user)  # type: ignore[arg-type]
    counts: dict[str, dict[str, int]] = {"open": {}, "proposed": {}}
    docs = comment_threads_collection.find(
        {
            "anchor.dashboard_id": str(dashboard["dashboard_id"]),
            "status": {"$in": ["open", "proposed"]},
        }
    )
    for doc in docs:
        thread = _reattach(_to_thread(doc), dashboard)
        key = thread.anchor.component_index or TAB_KEY
        bucket = counts[thread.status]
        bucket[key] = bucket.get(key, 0) + 1
    return counts


@comments_endpoint_router.get("/published/{dashboard_id}", response_model=list[PublishedAnnotation])
async def list_published_annotations(
    dashboard_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> list[PublishedAnnotation]:
    """Published annotations of a tab, for anyone who can view it. Never the comments."""
    dashboard = dashboards_collection.find_one(
        {"dashboard_id": _oid(dashboard_id, "Dashboard")},
        {"project_id": 1, "dashboard_id": 1, "stored_metadata": 1},
    )
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    project_id = dashboard.get("project_id")
    if not project_id or not check_project_permission(project_id, current_user, "viewer"):
        raise HTTPException(status_code=403, detail="You don't have access to this dashboard.")

    docs = comment_threads_collection.find(
        {
            "anchor.dashboard_id": str(dashboard["dashboard_id"]),
            "annotation.published": True,
            "status": {"$in": ["open", "resolved"]},
        },
        {"comments": 0},
    )
    out: list[PublishedAnnotation] = []
    for doc in docs:
        doc.setdefault("comments", [])
        thread = _reattach(_to_thread(doc), dashboard, persist=False)
        ann = thread.annotation
        if ann is None or not ann.published or thread.is_agent_proposal:
            continue
        out.append(
            PublishedAnnotation(
                thread_id=thread.id,
                dashboard_id=thread.anchor.dashboard_id,
                component_index=thread.anchor.component_index,
                number=thread.number,
                kind=ann.kind,
                geometry=ann.geometry,
                label=ann.label,
                color=ann.color,
                style=ann.style,
                variant=ann.variant,
            )
        )
    out.sort(key=lambda a: (a.number is None, a.number or 0))
    return out


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------
@comments_endpoint_router.post("/threads", response_model=ThreadOut, status_code=201)
async def create_thread(
    body: ThreadCreate,
    response: Response,
    current_user: User = Depends(get_user_or_anonymous),
) -> ThreadOut:
    """Open a thread on a component or a tab.

    With ``agent`` set, the thread is written by an agent on behalf of the
    caller and starts ``proposed``. A ``dedupe_key`` already used on the same
    anchor updates that thread instead of creating a new one (200).
    Fingerprints in the anchor are always computed here; client values are ignored.
    """
    dashboard = _require_dashboard_editor(
        _oid(body.anchor.dashboard_id, "Dashboard"),  # type: ignore[arg-type]
        current_user,
    )
    tab_id = str(dashboard["dashboard_id"])

    component: dict | None = None
    if body.anchor.component_index is not None:
        component = _components_by_index(dashboard).get(body.anchor.component_index)
        if component is None:
            raise HTTPException(
                status_code=400,
                detail=f"Component '{body.anchor.component_index}' is not on this tab.",
            )

    cache = _HashCache()
    anchor = body.anchor.model_copy(
        update={
            "dashboard_id": tab_id,
            "component_hash": component_fingerprint(component),
            "data_hashes": _data_hashes(component, cache) if component else {},
            "component_title": body.anchor.component_title
            or ((component or {}).get("title") or None),
        }
    )

    if body.agent is not None:
        author = Author(
            kind="agent",
            user_id=str(current_user.id),
            email=current_user.email,
            agent=body.agent.model_copy(update={"on_behalf_of": str(current_user.id)}),
        )
    else:
        author = _human(current_user)
    run_id = body.agent.run_id if body.agent is not None else None
    now = utcnow()

    uid = str(current_user.id)

    def check_run_cap() -> None:
        taken = comment_threads_collection.count_documents(
            {"run_id": run_id, "created_by.agent.on_behalf_of": uid}
        )
        if taken >= MAX_THREADS_PER_RUN:
            raise HTTPException(
                status_code=429,
                detail=f"An agent run may open at most {MAX_THREADS_PER_RUN} threads.",
            )

    # Idempotence: an agent re-run updates the caller's own earlier proposal
    # instead of duplicating it. Only a proposal still awaiting (or refused)
    # review qualifies; after acceptance, a re-run yields a fresh proposal.
    # Human requests never dedupe.
    if body.agent is not None and body.dedupe_key is not None:
        existing_doc = comment_threads_collection.find_one(
            {
                "dedupe_key": body.dedupe_key,
                "anchor.dashboard_id": tab_id,
                "anchor.component_index": anchor.component_index,
                "created_by.kind": "agent",
                "created_by.agent.on_behalf_of": uid,
                "status": {"$in": ["proposed", "rejected"]},
            }
        )
        if existing_doc:
            existing = _to_thread(existing_doc)
            if existing.run_id != run_id:
                check_run_cap()
            update_set: dict[str, Any] = {
                "anchor": anchor.model_dump(mode="python"),
                "run_id": run_id,
                # A rejected proposal made again goes back to review.
                "status": "proposed",
                "review": None,
            }
            if body.annotation is not None:
                # Still a proposal: never visible to viewers.
                annotation = body.annotation.model_copy(update={"published": False})
                update_set["annotation"] = annotation.model_dump(mode="python")
                if existing.number is None:
                    update_set["number"] = _next_annotation_number(tab_id)
            elif existing.annotation is not None:
                update_set["annotation.published"] = False
            if body.evidence is not None:
                update_set["evidence"] = [e.model_dump(mode="python") for e in body.evidence]
            update: dict[str, Any] = {"$set": update_set}
            live = [c for c in existing.comments if not c.deleted]
            if body.body is not None and (not live or live[-1].body != body.body):
                if len(existing.comments) >= MAX_COMMENTS_PER_THREAD:
                    raise HTTPException(status_code=409, detail="This thread is full.")
                comment = Comment(
                    id=uuid.uuid4().hex, author=author, body=body.body, created_at=now
                )
                update["$push"] = {"comments": comment.model_dump(mode="python")}
            response.status_code = 200
            return _update_thread(existing.id, update)

    if run_id is not None:
        check_run_cap()

    comments = []
    if body.body is not None:
        comments.append(Comment(id=uuid.uuid4().hex, author=author, body=body.body, created_at=now))

    thread = CommentThread(
        id=str(ObjectId()),
        project_id=str(dashboard["project_id"]),
        parent_dashboard_id=_main_tab_id(dashboard),
        anchor=anchor,
        annotation=body.annotation,
        number=_next_annotation_number(tab_id) if body.annotation is not None else None,
        status="proposed" if body.agent is not None else "open",
        evidence=body.evidence,
        dedupe_key=body.dedupe_key,
        run_id=run_id,
        created_by=author,
        created_at=now,
        updated_at=now,
        comments=comments,
    )
    comment_threads_collection.insert_one(_to_storage(thread))
    logger.info(
        f"comments: thread {thread.id} opened on {tab_id}/{anchor.component_index or TAB_KEY} "
        f"by {author.kind} {author.user_id}"
    )
    return _out(thread, dashboard, cache)


@comments_endpoint_router.patch("/threads/{thread_id}", response_model=ThreadOut)
async def update_thread(
    thread_id: str,
    body: ThreadUpdate,
    current_user: User = Depends(get_user_or_anonymous),
) -> ThreadOut:
    """Resolve or reopen a thread, and/or edit its annotation (including publishing it)."""
    thread, _ = _load_thread(thread_id, current_user)
    if body.status is None and body.annotation is None:
        raise HTTPException(status_code=400, detail="Nothing to update.")

    update_set: dict[str, Any] = {}

    if body.status is not None:
        if thread.status in ("proposed", "rejected"):
            raise HTTPException(
                status_code=409,
                detail=f"A {thread.status} thread must be reviewed before it can be resolved or reopened.",
            )
        update_set["status"] = body.status
        if body.status == "resolved":
            update_set["resolved_by"] = str(current_user.id)
            update_set["resolved_at"] = utcnow()
        else:
            update_set["resolved_by"] = None
            update_set["resolved_at"] = None

    if body.annotation is not None:
        if thread.annotation is None:
            raise HTTPException(status_code=404, detail="This thread has no annotation.")
        # An explicit null means "leave as is": every annotation field is
        # required once set. ``style`` and ``geometry`` replace the stored
        # value wholesale, so clients send the complete object.
        patch = {
            k: v
            for k, v in body.annotation.model_dump(mode="python", exclude_unset=True).items()
            if v is not None
        }
        if patch.get("published") and thread.is_agent_proposal:
            raise HTTPException(
                status_code=409,
                detail="An agent's annotation cannot be published before a human accepts it.",
            )
        merged = {**thread.annotation.model_dump(mode="python"), **patch}
        try:
            annotation = Annotation.model_validate(merged)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail=exc.errors(include_url=False, include_context=False)
            ) from exc
        update_set["annotation"] = annotation.model_dump(mode="python")
        # Keep the "modified" review outcome: a human reshaped an agent's
        # annotation (publishing alone is not a modification).
        if thread.created_by.kind == "agent" and set(patch) - {"published"}:
            update_set["human_edited"] = True

    return _update_thread(thread.id, {"$set": update_set})


@comments_endpoint_router.post("/threads/{thread_id}/review", response_model=ThreadOut)
async def review_thread(
    thread_id: str,
    body: ThreadReview,
    current_user: User = Depends(get_user_or_anonymous),
) -> ThreadOut:
    """Accept or reject an agent's proposed thread. The decision and reason are kept."""
    thread, _ = _load_thread(thread_id, current_user)
    if thread.created_by.kind != "agent" or thread.status != "proposed":
        raise HTTPException(status_code=409, detail="Only a proposed agent thread can be reviewed.")

    review = Review(
        decision=body.decision, by=str(current_user.id), at=utcnow(), reason=body.reason
    )
    update_set: dict[str, Any] = {
        "review": review.model_dump(mode="python"),
        "status": "open" if body.decision == "accepted" else "rejected",
    }
    if body.decision == "rejected" and thread.annotation is not None:
        update_set["annotation.published"] = False
    return _update_thread(thread.id, {"$set": update_set})


@comments_endpoint_router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> Response:
    """Delete a thread: its creator (or the user an agent wrote it for), a project owner, or an admin."""
    thread, dashboard = _load_thread(thread_id, current_user)
    uid = str(current_user.id)
    creator = thread.created_by
    is_creator = creator.user_id == uid or (
        creator.agent is not None and creator.agent.on_behalf_of == uid
    )
    if not (
        is_creator
        or current_user.is_admin
        or _is_project_owner(dashboard.get("project_id"), current_user)
    ):
        raise HTTPException(
            status_code=403, detail="Only the thread's author or a project owner can delete it."
        )
    comment_threads_collection.delete_one({"_id": ObjectId(thread.id)})
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
@comments_endpoint_router.post("/threads/{thread_id}/comments", response_model=ThreadOut)
async def add_comment(
    thread_id: str,
    body: CommentCreate,
    current_user: User = Depends(get_user_or_anonymous),
) -> ThreadOut:
    """Reply to a thread."""
    thread, _ = _load_thread(thread_id, current_user)
    if thread.status == "rejected":
        raise HTTPException(status_code=409, detail="A rejected thread takes no replies.")
    now = utcnow()
    comment = Comment(
        id=uuid.uuid4().hex, author=_human(current_user), body=body.body, created_at=now
    )
    # The cap is part of the match so two concurrent replies cannot both slip past it.
    doc = comment_threads_collection.find_one_and_update(
        {"_id": ObjectId(thread.id), f"comments.{MAX_COMMENTS_PER_THREAD - 1}": {"$exists": False}},
        {"$push": {"comments": comment.model_dump(mode="python")}, "$set": {"updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise HTTPException(
            status_code=409,
            detail=f"A thread holds at most {MAX_COMMENTS_PER_THREAD} comments.",
        )
    return _thread_out(doc)


@comments_endpoint_router.patch(
    "/threads/{thread_id}/comments/{comment_id}", response_model=ThreadOut
)
async def edit_comment(
    thread_id: str,
    comment_id: str,
    body: CommentUpdate,
    current_user: User = Depends(get_user_or_anonymous),
) -> ThreadOut:
    """Edit one's own comment."""
    thread, _ = _load_thread(thread_id, current_user)
    comment = _find_comment(thread, comment_id)
    if comment.author.kind != "human" or comment.author.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Only the author can edit a comment.")
    if comment.deleted:
        raise HTTPException(status_code=409, detail="This comment was deleted.")
    return _set_comment_fields(thread.id, comment_id, {"body": body.body})


@comments_endpoint_router.delete(
    "/threads/{thread_id}/comments/{comment_id}", response_model=ThreadOut
)
async def delete_comment(
    thread_id: str,
    comment_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> ThreadOut:
    """Soft-delete a comment (its author or a project owner). The body is cleared."""
    thread, dashboard = _load_thread(thread_id, current_user)
    comment = _find_comment(thread, comment_id)
    is_author = comment.author.user_id == str(current_user.id)
    if not (is_author or _is_project_owner(dashboard.get("project_id"), current_user)):
        raise HTTPException(
            status_code=403, detail="Only the author or a project owner can delete a comment."
        )
    return _set_comment_fields(thread.id, comment_id, {"deleted": True, "body": ""})
