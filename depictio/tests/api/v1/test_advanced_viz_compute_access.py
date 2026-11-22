"""Access control on the POST /advanced_viz/compute_* dispatch routes.

The dispatchers take the dc id from the caller and hand it to Celery (or the
compute cache), so without a gate any caller could compute over — and read
cached results from — any data collection by id. Every dispatcher must run
the same viewer-level gate as ``POST /advanced_viz/data`` before any cache
read or task dispatch.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.advanced_viz_endpoints import routes as viz_routes

COMPUTE_DISPATCHERS = [
    "dispatch_compute_embedding",
    "dispatch_compute_complex_heatmap",
    "dispatch_compute_upset",
    "dispatch_compute_coverage_track",
    "dispatch_compute_contact_map",
    "dispatch_compute_sankey",
    "dispatch_compute_group_compare",
]


def _user(*, admin: bool = False, anonymous: bool = False):
    return SimpleNamespace(id=ObjectId(), is_admin=admin, is_anonymous=anonymous)


def _payload(**extra):
    return {"wf_id": str(ObjectId()), "dc_id": str(ObjectId()), **extra}


class _Task:
    """Stand-in for the Celery task: records the dispatch, no broker."""

    time_limit = 300

    def __init__(self):
        self.calls: list = []

    def apply_async(self, args):
        self.calls.append(args)
        return SimpleNamespace(id="task-1")


@pytest.mark.parametrize("name", COMPUTE_DISPATCHERS)
def test_a_caller_with_no_access_gets_404_before_any_dispatch(name):
    """No membership, project not public, caller not admin: 404, raised
    before the compute cache or the Celery task is touched."""
    projects = MagicMock()
    projects.find_one.return_value = None  # no accessible project
    groups = MagicMock()
    groups.find.return_value = []
    cache_db = MagicMock()
    with (
        patch("depictio.api.v1.db.projects_collection", projects),
        patch("depictio.api.v1.db.groups_collection", groups),
        patch("depictio.api.v1.db.db", cache_db),
    ):
        with pytest.raises(HTTPException) as exc_info:
            getattr(viz_routes, name)(_payload(), current_user=_user(), access_token=None)
    assert exc_info.value.status_code == 404
    # Viewer level, same as /data: the membership $or carries the public /
    # viewers clauses an owner-only gate would not have.
    match_clause = projects.find_one.call_args[0][0]
    assert any("is_public" in clause for clause in match_clause["$or"])
    # Refused before any compute work started.
    cache_db.__getitem__.assert_not_called()


def test_compute_embedding_still_dispatches_for_an_authorized_viewer():
    """The gate must not change the happy path: a caller whose project is
    reachable gets the job dispatched exactly as before."""
    projects = MagicMock()
    projects.find_one.return_value = {"_id": ObjectId()}
    groups = MagicMock()
    groups.find.return_value = []
    task = _Task()
    with (
        patch("depictio.api.v1.db.projects_collection", projects),
        patch("depictio.api.v1.db.groups_collection", groups),
        patch("depictio.api.v1.db.db", mongomock.MongoClient().db),
        patch("depictio.api.v1.celery_tasks.compute_embedding", task),
    ):
        payload = _payload(method="umap", params={})
        out = viz_routes.dispatch_compute_embedding(
            payload, current_user=_user(), access_token=None
        )
    assert out["status"] == "pending"
    assert out["from_cache"] is False
    assert task.calls and task.calls[0][0] is payload


def test_an_anonymous_visitor_reaches_public_projects_only():
    """Anonymous visitors keep the /data contract: a public DC passes the
    gate, a private one answers 404 via the is_public clause."""
    from contextlib import ExitStack

    projects = MagicMock()
    groups = MagicMock()
    groups.find.return_value = []
    task = _Task()
    caller = _user(anonymous=True)

    # Public project: dispatched as before.
    projects.find_one.return_value = {"_id": ObjectId()}
    with ExitStack() as stack:
        for target, replacement in (
            ("depictio.api.v1.db.projects_collection", projects),
            ("depictio.api.v1.db.groups_collection", groups),
            ("depictio.api.v1.db.db", mongomock.MongoClient().db),
            ("depictio.api.v1.celery_tasks.compute_coverage_track", task),
        ):
            stack.enter_context(patch(target, replacement))
        out = viz_routes.dispatch_compute_coverage_track(
            _payload(), current_user=caller, access_token=None
        )
    assert out["status"] == "pending"

    # Private project: same caller, now refused.
    projects.find_one.return_value = None
    with ExitStack() as stack:
        for target, replacement in (
            ("depictio.api.v1.db.projects_collection", projects),
            ("depictio.api.v1.db.groups_collection", groups),
            ("depictio.api.v1.db.db", mongomock.MongoClient().db),
            ("depictio.api.v1.celery_tasks.compute_coverage_track", task),
        ):
            stack.enter_context(patch(target, replacement))
        with pytest.raises(HTTPException) as exc_info:
            viz_routes.dispatch_compute_coverage_track(
                _payload(), current_user=caller, access_token=None
            )
    assert exc_info.value.status_code == 404
    # The anonymous gate is the public-project clause, not a membership $or.
    match_clause = projects.find_one.call_args[0][0]
    assert match_clause.get("is_public") is True
