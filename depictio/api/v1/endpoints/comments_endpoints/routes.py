"""Comment threads and annotations pinned to dashboard components: the REST routes.

Thin wrappers over :mod:`.service`, which holds the logic and the permission
checks (shared with the agent tools). A request authenticated with a scoped
token is an agent caller: its threads and replies get agent authorship, and it
can neither review a thread nor publish an annotation (the service enforces
both).
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from depictio.api.v1.endpoints.comments_endpoints import service
from depictio.api.v1.endpoints.comments_endpoints.service import (  # noqa: F401 — re-exported
    MAX_COMMENTS_PER_THREAD,
    MAX_THREADS_PER_RUN,
    TAB_KEY,
    _get_aggregation_hash,
    comment_threads_collection,
    dashboards_collection,
)
from depictio.api.v1.endpoints.user_endpoints.routes import (
    get_user_or_anonymous,
    oauth2_scheme_optional,
)
from depictio.models.models.comments import (
    CommentAccess,
    CommentCreate,
    CommentUpdate,
    PublishedAnnotation,
    ThreadCreate,
    ThreadKind,
    ThreadOut,
    ThreadReview,
    ThreadStatus,
    ThreadUpdate,
)
from depictio.models.models.users import User

comments_endpoint_router = APIRouter()


class _RoutesModule(ModuleType):
    """Forward patches of the service's storage handles and caps to the service.

    ``patch.object(routes, "comment_threads_collection", ...)`` predates the
    service split; forwarding keeps such patches effective where the code now runs.
    """

    def __setattr__(self, name: str, value: Any) -> None:
        if name in service.PATCHABLE:
            setattr(service, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _RoutesModule


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
    return await service.get_comment_access(current_user, dashboard_id)


@comments_endpoint_router.get("/dashboard/{dashboard_id}", response_model=list[ThreadOut])
async def list_threads(
    dashboard_id: str,
    scope: Literal["tab", "family"] = "tab",
    component_index: str | None = Query(
        default=None, description=f"Only this component's threads; '{TAB_KEY}' for the tab's own."
    ),
    status: ThreadStatus | None = None,
    kind: ThreadKind | None = None,
    current_user: User = Depends(get_user_or_anonymous),
) -> list[ThreadOut]:
    """Threads of a tab (``scope=tab``) or of every tab of its dashboard (``family``).

    Rejected threads are hidden unless ``status=rejected`` is asked for.
    """
    return await service.list_threads(
        current_user,
        dashboard_id,
        scope=scope,
        component_index=component_index,
        status=status,
        kind=kind,
    )


@comments_endpoint_router.get("/counts/{dashboard_id}")
async def count_threads(
    dashboard_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict[str, dict[str, int]]:
    """Open and proposed threads of a tab, per component index (``__tab__`` for the tab)."""
    return await service.count_threads(current_user, dashboard_id)


@comments_endpoint_router.get("/published/{dashboard_id}", response_model=list[PublishedAnnotation])
async def list_published_annotations(
    dashboard_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> list[PublishedAnnotation]:
    """Published annotations of a tab, for anyone who can view it. Never the comments."""
    return await service.list_published_annotations(current_user, dashboard_id)


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

    With ``agent`` set (or a scoped token), the thread is written by an agent
    on behalf of the caller and starts ``proposed``. A ``dedupe_key`` already
    used on the same anchor updates that thread instead of creating a new one (200).
    """
    thread, created = await service.create_thread(current_user, body)
    if not created:
        response.status_code = 200
    return thread


@comments_endpoint_router.get("/threads/{thread_id}", response_model=ThreadOut)
async def get_thread(
    thread_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> ThreadOut:
    """One thread, with its staleness."""
    return await service.get_thread(current_user, thread_id)


@comments_endpoint_router.patch("/threads/{thread_id}", response_model=ThreadOut)
async def update_thread(
    thread_id: str,
    body: ThreadUpdate,
    current_user: User = Depends(get_user_or_anonymous),
) -> ThreadOut:
    """Resolve or reopen a thread, and/or edit its annotation (including publishing it)."""
    return await service.update_thread(current_user, thread_id, body)


@comments_endpoint_router.post("/threads/{thread_id}/review", response_model=ThreadOut)
async def review_thread(
    thread_id: str,
    body: ThreadReview,
    current_user: User = Depends(get_user_or_anonymous),
) -> ThreadOut:
    """Accept or reject an agent's proposed thread. The decision and reason are kept."""
    return await service.review_thread(current_user, thread_id, body)


@comments_endpoint_router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> Response:
    """Delete a thread: its creator (or the user an agent wrote it for), a project owner, or an admin."""
    await service.delete_thread(current_user, thread_id)
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
    return await service.add_comment(current_user, thread_id, body)


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
    return await service.edit_comment(current_user, thread_id, comment_id, body)


@comments_endpoint_router.delete(
    "/threads/{thread_id}/comments/{comment_id}", response_model=ThreadOut
)
async def delete_comment(
    thread_id: str,
    comment_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> ThreadOut:
    """Soft-delete a comment (its author or a project owner). The body is cleared."""
    return await service.delete_comment(current_user, thread_id, comment_id)
