"""Regression tests for ``check_dashboard_owner_permission_sync``.

Dashboard duplication assigns the new owner at the **dashboard** level
(``dashboard.permissions.owners``) while keeping ``project_id`` pointing
at the original project. The screenshot service previously consulted
only the project's owners, so the celery screenshot task denied every
duplicated dashboard with::

    Screenshot denied: user <copier> is not owner of dashboard <copy>

These tests pin the new behaviour: dashboard-level owners win, with a
fallback to project owners for seeded dashboards that don't carry their
own owner list.
"""

from __future__ import annotations

from bson import ObjectId

from depictio.api.v1.services import screenshot_service


def _user_doc(user_id: ObjectId) -> dict:
    return {"_id": user_id, "email": f"user-{user_id}@example.com"}


def _stub_collections(monkeypatch, *, dashboard: dict | None, project: dict | None) -> None:
    class _Coll:
        def __init__(self, doc):
            self.doc = doc

        def find_one(self, _query):
            return self.doc

    monkeypatch.setattr(screenshot_service, "dashboards_collection", _Coll(dashboard))
    monkeypatch.setattr(screenshot_service, "projects_collection", _Coll(project))


def test_dashboard_level_owner_grants_access(monkeypatch) -> None:
    """Duplicated dashboard: owner is on the dashboard, NOT on the project."""
    copier = ObjectId()
    original_owner = ObjectId()
    project_id = ObjectId()
    dashboard_id = ObjectId()

    dashboard = {
        "dashboard_id": dashboard_id,
        "project_id": project_id,
        "permissions": {"owners": [_user_doc(copier)]},
    }
    project = {
        "_id": project_id,
        "permissions": {"owners": [_user_doc(original_owner)]},
    }
    _stub_collections(monkeypatch, dashboard=dashboard, project=project)

    assert (
        screenshot_service.check_dashboard_owner_permission_sync(str(dashboard_id), str(copier))
        is True
    )


def test_project_level_fallback_for_seeded_dashboard(monkeypatch) -> None:
    """Seeded dashboards have no dashboard-level owners — project owners still grant access."""
    project_owner = ObjectId()
    project_id = ObjectId()
    dashboard_id = ObjectId()

    dashboard = {
        "dashboard_id": dashboard_id,
        "project_id": project_id,
        "permissions": {"owners": []},
    }
    project = {
        "_id": project_id,
        "permissions": {"owners": [_user_doc(project_owner)]},
    }
    _stub_collections(monkeypatch, dashboard=dashboard, project=project)

    assert (
        screenshot_service.check_dashboard_owner_permission_sync(
            str(dashboard_id), str(project_owner)
        )
        is True
    )


def test_unrelated_user_is_denied(monkeypatch) -> None:
    """User who is neither dashboard-owner nor project-owner gets denied."""
    dashboard_owner = ObjectId()
    project_owner = ObjectId()
    stranger = ObjectId()
    project_id = ObjectId()
    dashboard_id = ObjectId()

    dashboard = {
        "dashboard_id": dashboard_id,
        "project_id": project_id,
        "permissions": {"owners": [_user_doc(dashboard_owner)]},
    }
    project = {
        "_id": project_id,
        "permissions": {"owners": [_user_doc(project_owner)]},
    }
    _stub_collections(monkeypatch, dashboard=dashboard, project=project)

    assert (
        screenshot_service.check_dashboard_owner_permission_sync(str(dashboard_id), str(stranger))
        is False
    )


def test_owner_id_stored_as_string(monkeypatch) -> None:
    """Some import paths serialise ``_id`` as a string — must still match."""
    copier = ObjectId()
    project_id = ObjectId()
    dashboard_id = ObjectId()

    dashboard = {
        "dashboard_id": dashboard_id,
        "project_id": project_id,
        "permissions": {"owners": [{"_id": str(copier), "email": "x@example.com"}]},
    }
    project = {"_id": project_id, "permissions": {"owners": []}}
    _stub_collections(monkeypatch, dashboard=dashboard, project=project)

    assert (
        screenshot_service.check_dashboard_owner_permission_sync(str(dashboard_id), str(copier))
        is True
    )


def test_missing_dashboard_returns_false(monkeypatch) -> None:
    _stub_collections(monkeypatch, dashboard=None, project=None)
    assert (
        screenshot_service.check_dashboard_owner_permission_sync(str(ObjectId()), str(ObjectId()))
        is False
    )


def test_dashboard_with_no_project_id_and_no_owners(monkeypatch) -> None:
    """Edge case: orphaned dashboard with no project_id and no owners."""
    dashboard = {
        "dashboard_id": ObjectId(),
        "permissions": {"owners": []},
    }
    _stub_collections(monkeypatch, dashboard=dashboard, project=None)

    assert (
        screenshot_service.check_dashboard_owner_permission_sync(
            str(dashboard["dashboard_id"]), str(ObjectId())
        )
        is False
    )
