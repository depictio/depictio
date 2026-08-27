"""Tests for the project-driven visibility model and its security invariants.

Covers:

1. ``check_project_permission`` — a public project grants VIEWER access only;
   editor/owner always require explicit membership (no public ⇒ owner
   escalation, issue behind the demo-deployment dashboard deletions).
2. ``is_dashboard_owner`` / ``check_dashboard_mutation_permission`` — owners of
   a dashboard *document* (e.g. a visitor's duplicated copy on a public
   project) keep mutating their own copy without project-wide editor rights.
3. ``save_dashboard`` — mass-assignment protection on update (``is_public``,
   ``permissions``, ``project_id`` are server-owned) and project-driven
   ``is_public`` stamping + viewer check on insert.
4. ``cascade_project_visibility`` / ``reconcile_dashboard_visibility`` — the
   project toggle cascade and the startup reconciliation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

from depictio.models.models.base import PyObjectId
from depictio.models.models.dashboards import DashboardData
from depictio.models.models.users import Permission, UserBase

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(*, user_id=None, is_admin=False, is_anonymous=False):
    user = MagicMock()
    user.id = user_id or PyObjectId()
    user.is_admin = is_admin
    user.is_anonymous = is_anonymous
    return user


def _project_doc(*, is_public=False, owners=(), editors=(), viewers=()):
    return {
        "_id": ObjectId(),
        "is_public": is_public,
        "permissions": {
            "owners": [{"_id": ObjectId(str(o))} for o in owners],
            "editors": [{"_id": ObjectId(str(e))} for e in editors],
            "viewers": [{"_id": ObjectId(str(v))} for v in viewers],
        },
    }


# ---------------------------------------------------------------------------
# 1. check_project_permission — public grants read, never write
# ---------------------------------------------------------------------------


class TestCheckProjectPermission:
    def _check(self, project_doc, user, level):
        from depictio.api.v1.endpoints.dashboards_endpoints import routes

        projects_coll = MagicMock()
        projects_coll.find_one.return_value = project_doc
        with patch.object(routes, "projects_collection", projects_coll):
            return routes.check_project_permission(ObjectId(), user, level)

    @pytest.mark.parametrize("level", ["viewer", "editor", "owner"])
    def test_admin_always_passes(self, level):
        assert self._check(_project_doc(), _user(is_admin=True), level) is True

    def test_public_project_grants_viewer_to_any_authenticated_user(self):
        assert self._check(_project_doc(is_public=True), _user(), "viewer") is True

    @pytest.mark.parametrize("level", ["editor", "owner"])
    def test_public_project_does_not_grant_write(self, level):
        """The old public ⇒ owner escalation: any signed-in visitor of a public
        (demo) project could edit/delete its dashboards. Public = read-only."""
        assert self._check(_project_doc(is_public=True), _user(), level) is False

    def test_anonymous_viewer_on_public_project(self):
        user = _user(is_anonymous=True)
        assert self._check(_project_doc(is_public=True), user, "viewer") is True

    @pytest.mark.parametrize("level", ["editor", "owner"])
    def test_anonymous_never_gets_write(self, level):
        user = _user(is_anonymous=True)
        assert self._check(_project_doc(is_public=True), user, level) is False

    def test_private_project_denies_non_member(self):
        assert self._check(_project_doc(), _user(), "viewer") is False

    def test_explicit_owner_keeps_owner_access_on_public_project(self):
        owner_id = PyObjectId()
        doc = _project_doc(is_public=True, owners=[owner_id])
        assert self._check(doc, _user(user_id=owner_id), "owner") is True

    def test_explicit_editor_on_private_project(self):
        editor_id = PyObjectId()
        doc = _project_doc(editors=[editor_id])
        assert self._check(doc, _user(user_id=editor_id), "editor") is True
        assert self._check(doc, _user(user_id=editor_id), "owner") is False


# ---------------------------------------------------------------------------
# 2. Dashboard-document ownership bypass
# ---------------------------------------------------------------------------


class TestDashboardMutationPermission:
    def test_dashboard_owner_without_project_role_can_mutate(self):
        """A visitor's duplicated copy on a public project stays editable and
        deletable by that visitor (demo walkthrough flow) — via document
        ownership, not project-wide editor rights."""
        from depictio.api.v1.endpoints.dashboards_endpoints import routes

        visitor = _user()
        dashboard_doc = {
            "project_id": ObjectId(),
            "permissions": {"owners": [{"_id": ObjectId(str(visitor.id))}]},
        }
        projects_coll = MagicMock()
        projects_coll.find_one.return_value = _project_doc(is_public=True)
        with patch.object(routes, "projects_collection", projects_coll):
            assert (
                routes.check_dashboard_mutation_permission(dashboard_doc, visitor, "editor") is True
            )
            assert (
                routes.check_dashboard_mutation_permission(dashboard_doc, visitor, "owner") is True
            )

    def test_non_owner_visitor_cannot_mutate_public_dashboard(self):
        from depictio.api.v1.endpoints.dashboards_endpoints import routes

        dashboard_doc = {
            "project_id": ObjectId(),
            "permissions": {"owners": [{"_id": ObjectId()}]},
        }
        projects_coll = MagicMock()
        projects_coll.find_one.return_value = _project_doc(is_public=True)
        with patch.object(routes, "projects_collection", projects_coll):
            assert (
                routes.check_dashboard_mutation_permission(dashboard_doc, _user(), "editor")
                is False
            )

    def test_anonymous_is_never_dashboard_owner(self):
        from depictio.api.v1.endpoints.dashboards_endpoints import routes

        anon = _user(is_anonymous=True)
        dashboard_doc = {"permissions": {"owners": [{"_id": ObjectId(str(anon.id))}]}}
        assert routes.is_dashboard_owner(dashboard_doc, anon) is False


# ---------------------------------------------------------------------------
# 3. save_dashboard — mass-assignment protection + insert stamping
# ---------------------------------------------------------------------------


def _dashboard_payload(*, owner, project_id, is_public=False):
    return DashboardData(
        dashboard_id=PyObjectId(),
        title="Test dashboard",
        permissions=Permission(
            owners=[UserBase(id=owner.id, email="owner@example.com")],
            editors=[],
            viewers=[],
        ),
        is_public=is_public,
        project_id=project_id,
    )


@pytest.mark.asyncio
async def test_save_update_strips_server_owned_fields():
    """An editor round-tripping the whole document must not be able to flip
    ``is_public``, rewrite ``permissions``, or move the dashboard to another
    project via /save — those have dedicated owner-gated paths."""
    from depictio.api.v1.endpoints.dashboards_endpoints import routes

    owner = _user()
    project_id = PyObjectId()
    data = _dashboard_payload(owner=owner, project_id=project_id, is_public=True)

    existing = {
        "_id": ObjectId(str(data.dashboard_id)),
        "dashboard_id": ObjectId(str(data.dashboard_id)),
        "project_id": ObjectId(str(project_id)),
        "is_public": False,
        "creation_time": "2024-01-01 00:00:00",
        "permissions": {"owners": [{"_id": ObjectId(str(owner.id))}]},
    }

    dashboards_coll = MagicMock()
    dashboards_coll.find_one.return_value = existing
    dashboards_coll.find_one_and_update.return_value = dict(existing)

    projects_coll = MagicMock()
    projects_coll.find_one.return_value = _project_doc(is_public=False, owners=[owner.id])

    with (
        patch.object(routes, "dashboards_collection", dashboards_coll),
        patch.object(routes, "projects_collection", projects_coll),
        # Skip the best-effort screenshot enqueue — no Celery broker in tests.
        patch.object(routes, "_should_enqueue_screenshot", return_value=False),
    ):
        await routes.save_dashboard(
            dashboard_id=data.dashboard_id,
            data=data,
            current_user=owner,
        )

    update_call = dashboards_coll.find_one_and_update.call_args
    set_payload = update_call.args[1]["$set"]
    assert "is_public" not in set_payload
    assert "permissions" not in set_payload
    assert "project_id" not in set_payload
    assert "_id" not in set_payload


@pytest.mark.asyncio
@pytest.mark.parametrize("project_is_public", [True, False])
async def test_save_insert_stamps_visibility_from_project(project_is_public: bool):
    """New dashboards (create / duplicate / tab) are born with their project's
    visibility, whatever the client sent — the flag is project-driven."""
    from depictio.api.v1.endpoints.dashboards_endpoints import routes

    creator = _user()
    project_id = PyObjectId()
    # Client claims the opposite of the project's flag — must be overridden.
    data = _dashboard_payload(owner=creator, project_id=project_id, is_public=not project_is_public)

    dashboards_coll = MagicMock()
    dashboards_coll.find_one.return_value = None  # insert branch
    dashboards_coll.find_one_and_update.return_value = {
        "dashboard_id": ObjectId(str(data.dashboard_id))
    }

    projects_coll = MagicMock()
    projects_coll.find_one.return_value = _project_doc(
        is_public=project_is_public, owners=[creator.id]
    )

    with (
        patch.object(routes, "dashboards_collection", dashboards_coll),
        patch.object(routes, "projects_collection", projects_coll),
        # Skip the best-effort screenshot enqueue — no Celery broker in tests.
        patch.object(routes, "_should_enqueue_screenshot", return_value=False),
    ):
        await routes.save_dashboard(
            dashboard_id=data.dashboard_id,
            data=data,
            current_user=creator,
        )

    set_payload = dashboards_coll.find_one_and_update.call_args.args[1]["$set"]
    assert set_payload["is_public"] is project_is_public


@pytest.mark.asyncio
async def test_save_insert_requires_project_read_access():
    """Creating a dashboard in a project the caller cannot even see is a
    cross-tenant write — rejected with 403 (the insert branch used to have no
    permission check at all)."""
    from fastapi import HTTPException

    from depictio.api.v1.endpoints.dashboards_endpoints import routes

    outsider = _user()
    data = _dashboard_payload(owner=outsider, project_id=PyObjectId())

    dashboards_coll = MagicMock()
    dashboards_coll.find_one.return_value = None

    projects_coll = MagicMock()
    projects_coll.find_one.return_value = _project_doc(is_public=False)  # not a member

    with (
        patch.object(routes, "dashboards_collection", dashboards_coll),
        patch.object(routes, "projects_collection", projects_coll),
        # Skip the best-effort screenshot enqueue — no Celery broker in tests.
        patch.object(routes, "_should_enqueue_screenshot", return_value=False),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await routes.save_dashboard(
                dashboard_id=data.dashboard_id,
                data=data,
                current_user=outsider,
            )

    assert exc_info.value.status_code == 403
    dashboards_coll.find_one_and_update.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Cascade + reconciliation
# ---------------------------------------------------------------------------


def test_cascade_project_visibility_updates_dashboards_and_tab_families():
    from depictio.api.v1.endpoints.dashboards_endpoints import core_functions

    project_id = ObjectId()
    main_tab_id = ObjectId()

    dashboards_coll = MagicMock()
    dashboards_coll.update_many.return_value = MagicMock(modified_count=3)
    dashboards_coll.find.return_value = [{"dashboard_id": main_tab_id}]

    with (
        patch.object(core_functions, "dashboards_collection", dashboards_coll),
        patch.object(core_functions, "sync_tab_family_permissions", return_value=2) as mock_sync,
    ):
        counts = core_functions.cascade_project_visibility(project_id, True)

    assert counts == {"dashboards_updated": 3, "child_tabs_updated": 2}
    dashboards_coll.update_many.assert_called_once_with(
        {"project_id": project_id},
        {"$set": {"is_public": True}},
    )
    mock_sync.assert_called_once_with(main_tab_id, new_is_public=True)


def test_reconcile_dashboard_visibility_syncs_drifted_flags():
    from depictio.api.v1.endpoints.dashboards_endpoints import core_functions

    public_project = {"_id": ObjectId(), "is_public": True}
    private_project = {"_id": ObjectId()}  # missing flag → treated as private

    projects_coll = MagicMock()
    projects_coll.find.return_value = [public_project, private_project]

    dashboards_coll = MagicMock()
    dashboards_coll.update_many.side_effect = [
        MagicMock(modified_count=2),
        MagicMock(modified_count=1),
    ]

    with (
        patch.object(core_functions, "projects_collection", projects_coll),
        patch.object(core_functions, "dashboards_collection", dashboards_coll),
    ):
        corrected = core_functions.reconcile_dashboard_visibility()

    assert corrected == 3
    first_call, second_call = dashboards_coll.update_many.call_args_list
    assert first_call.args[0] == {
        "project_id": public_project["_id"],
        "is_public": {"$ne": True},
    }
    assert first_call.args[1] == {"$set": {"is_public": True}}
    assert second_call.args[0] == {
        "project_id": private_project["_id"],
        "is_public": {"$ne": False},
    }
