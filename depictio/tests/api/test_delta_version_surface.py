"""Tests for what the Delta version surface exposes, and to whom.

Two separate concerns share this module because they are two halves of the same
feature — "show people what changed and when":

1. The ingestion report's change counts, which the CLI has always emitted in
   ``dc_stats`` and nothing ever read.
2. Who is allowed to see *who* ran an ingestion. Read access to a data
   collection is a much weaker bar than that: ``is_public: True`` admits
   anonymous users, so the email attached to each commit needs its own gate.
"""

from __future__ import annotations

import pytest

from depictio.api.v1.endpoints.projects_endpoints.ingestion_report import _aggregate_run_stats


class _FakeRuns:
    """Stands in for ``runs_collection`` with a fixed set of run documents."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def find(self, *_args, **_kwargs):
        return iter(self._docs)


def _run(run_tag: str, dc_stats: dict) -> dict:
    return {
        "run_tag": run_tag,
        "run_location": f"/data/{run_tag}",
        "scan_results": [{"scan_time": "2026-07-24 10:00:00", "dc_stats": dc_stats}],
    }


@pytest.fixture
def project() -> dict:
    from bson import ObjectId

    return {"workflows": [{"_id": str(ObjectId())}]}


class TestChangeCounts:
    """`updated_files` was collected by the CLI and dropped on the floor."""

    def test_updated_files_are_summed_per_dc(self, monkeypatch, project):
        import depictio.api.v1.endpoints.projects_endpoints.ingestion_report as module

        monkeypatch.setattr(
            module,
            "runs_collection",
            _FakeRuns(
                [
                    _run("run_a", {"reads": {"total_files": 5, "new_files": 5}}),
                    _run("run_b", {"reads": {"total_files": 4, "updated_files": 2}}),
                ]
            ),
        )

        per_dc, _runs, _scan_time = _aggregate_run_stats(project)

        assert per_dc["reads"]["new_files"] == 5
        assert per_dc["reads"]["updated_files"] == 2
        assert per_dc["reads"]["total_files"] == 9

    def test_runs_carry_their_own_totals(self, monkeypatch, project):
        import depictio.api.v1.endpoints.projects_endpoints.ingestion_report as module

        monkeypatch.setattr(
            module,
            "runs_collection",
            _FakeRuns(
                [
                    _run(
                        "run_a",
                        {
                            "reads": {"total_files": 5, "new_files": 5},
                            "qc": {"total_files": 1, "new_files": 1},
                        },
                    ),
                    _run("run_b", {"reads": {"total_files": 4, "updated_files": 2}}),
                ]
            ),
        )

        _per_dc, runs, _scan_time = _aggregate_run_stats(project)
        by_tag = {r.run_tag: r for r in runs}

        # Per-run totals sum across that run's DCs — the point is to answer
        # "which run brought the new data in" without expanding every DC.
        assert by_tag["run_a"].files_total == 6
        assert by_tag["run_a"].files_new == 6
        assert by_tag["run_a"].files_updated == 0
        assert by_tag["run_b"].files_total == 4
        assert by_tag["run_b"].files_updated == 2

    def test_missing_counters_default_to_zero(self, monkeypatch, project):
        """Runs scanned by an older CLI have no `updated_files` key at all."""
        import depictio.api.v1.endpoints.projects_endpoints.ingestion_report as module

        monkeypatch.setattr(
            module, "runs_collection", _FakeRuns([_run("old", {"reads": {"total_files": 3}})])
        )

        per_dc, runs, _scan_time = _aggregate_run_stats(project)

        assert per_dc["reads"]["updated_files"] == 0
        assert runs[0].files_updated == 0
        assert runs[0].files_total == 3

    def test_a_run_that_was_never_scanned_reports_zero(self, monkeypatch, project):
        import depictio.api.v1.endpoints.projects_endpoints.ingestion_report as module

        monkeypatch.setattr(
            module,
            "runs_collection",
            _FakeRuns([{"run_tag": "empty", "run_location": "/data/empty", "scan_results": []}]),
        )

        _per_dc, runs, _scan_time = _aggregate_run_stats(project)

        assert runs[0].status == "no_scan"
        assert runs[0].files_total == 0


class _FakeProjects:
    def __init__(self, doc: dict | None) -> None:
        self._doc = doc

    def find_one(self, *_args, **_kwargs):
        return self._doc


class _User:
    def __init__(self, user_id: str, is_admin: bool = False) -> None:
        self.id = user_id
        self.is_admin = is_admin


def _project_with(owner: str = "u-owner", editor: str = "u-editor") -> dict:
    return {
        "permissions": {
            "owners": [{"_id": owner}],
            "editors": [{"_id": editor}],
            "viewers": [{"_id": "u-viewer"}],
        }
    }


class TestOperatorVisibility:
    """Who may see the email attached to each Delta commit."""

    @pytest.fixture(autouse=True)
    def _patch_projects(self, monkeypatch):
        import depictio.api.v1.endpoints.deltatables_endpoints.routes as routes

        self.routes = routes
        self.set_project = lambda doc: monkeypatch.setattr(
            routes, "projects_collection", _FakeProjects(doc)
        )

    def test_owner_sees_operators(self):
        from bson import ObjectId

        self.set_project(_project_with())
        assert self.routes._caller_is_project_operator(ObjectId(), _User("u-owner")) is True

    def test_editor_sees_operators(self):
        from bson import ObjectId

        self.set_project(_project_with())
        assert self.routes._caller_is_project_operator(ObjectId(), _User("u-editor")) is True

    def test_viewer_does_not(self):
        from bson import ObjectId

        self.set_project(_project_with())
        assert self.routes._caller_is_project_operator(ObjectId(), _User("u-viewer")) is False

    def test_stranger_on_a_public_project_does_not(self):
        """The case this gate exists for: read access via `is_public`."""
        from bson import ObjectId

        self.set_project(_project_with())
        assert self.routes._caller_is_project_operator(ObjectId(), _User("u-nobody")) is False

    def test_admin_always_does(self):
        from bson import ObjectId

        self.set_project(_project_with())
        assert (
            self.routes._caller_is_project_operator(ObjectId(), _User("u-nobody", is_admin=True))
            is True
        )

    def test_a_missing_project_denies_rather_than_raising(self):
        from bson import ObjectId

        self.set_project(None)
        assert self.routes._caller_is_project_operator(ObjectId(), _User("u-owner")) is False
