"""Tests for the preconditions on browser-triggered ingestion.

The failure this guards against is the quiet one: a server that cannot see the
project's data starting an ingestion anyway, finding nothing, and reporting
success. Every check below exists to make that impossible to reach, so they are
worth pinning down independently of the endpoint that calls them.
"""

from __future__ import annotations

import pytest

from depictio.api.v1.endpoints.projects_endpoints.routes import (
    _may_trigger_ingestion,
    _unreachable_data_locations,
)


class _User:
    def __init__(self, user_id: str, is_admin: bool = False) -> None:
        self.id = user_id
        self.is_admin = is_admin


def _project(locations: list[str]) -> dict:
    return {"workflows": [{"data_location": {"structure": "flat", "locations": locations}}]}


class TestReachability:
    def test_an_existing_directory_is_reachable(self, tmp_path):
        assert _unreachable_data_locations(_project([str(tmp_path)])) == []

    def test_a_missing_directory_is_reported(self, tmp_path):
        missing = str(tmp_path / "not-mounted")

        assert _unreachable_data_locations(_project([missing])) == [missing]

    def test_a_file_is_not_a_data_location(self, tmp_path):
        """A path that exists but is not a directory cannot be scanned."""
        target = tmp_path / "runs.txt"
        target.write_text("not a directory")

        assert _unreachable_data_locations(_project([str(target)])) == [str(target)]

    def test_every_missing_location_is_listed(self, tmp_path):
        present = str(tmp_path)
        absent_a = str(tmp_path / "a")
        absent_b = str(tmp_path / "b")

        result = _unreachable_data_locations(_project([present, absent_a, absent_b]))

        assert result == [absent_a, absent_b]

    def test_a_project_with_no_workflows_is_vacuously_reachable(self):
        # Nothing to read means nothing unreadable; the ingestion itself is a
        # no-op, which is a different (and visible) outcome.
        assert _unreachable_data_locations({"workflows": []}) == []

    def test_a_workflow_without_a_data_location_does_not_explode(self):
        assert _unreachable_data_locations({"workflows": [{"name": "wf"}]}) == []


def _permissions(owner: str = "u-owner", editor: str = "u-editor") -> dict:
    return {
        "permissions": {
            "owners": [{"_id": owner}],
            "editors": [{"_id": editor}],
            "viewers": [{"_id": "u-viewer"}],
        }
    }


class TestPermission:
    @pytest.mark.parametrize("user_id", ["u-owner", "u-editor"])
    def test_owners_and_editors_may_trigger(self, user_id):
        assert _may_trigger_ingestion(_permissions(), _User(user_id)) is True

    def test_viewers_may_not(self):
        # Triggering rewrites data collections, so it takes write access, not
        # read access.
        assert _may_trigger_ingestion(_permissions(), _User("u-viewer")) is False

    def test_a_stranger_may_not(self):
        assert _may_trigger_ingestion(_permissions(), _User("u-nobody")) is False

    def test_admins_may(self):
        assert _may_trigger_ingestion(_permissions(), _User("u-nobody", is_admin=True)) is True

    def test_a_project_with_no_permissions_block_denies(self):
        assert _may_trigger_ingestion({}, _User("u-owner")) is False


class TestServerSidePipeline:
    """The task drives the CLI's own helpers; these pin how it calls them."""

    @pytest.fixture
    def harness(self, monkeypatch):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        import depictio.cli.cli.utils.helpers as helpers
        import depictio.cli.cli.utils.image_upload as image_upload
        from depictio.api.v1 import ingestion_tasks
        from depictio.api.v1.db import projects_collection
        from depictio.api.v1.jobs import store as jobs_store
        from depictio.api.v1.monitoring import store as monitoring_store
        from depictio.models.models import projects

        image_dc = SimpleNamespace(data_collection_tag="images")
        workflow = SimpleNamespace(
            name="iris",
            workflow_tag="python/iris",
            data_collections=[
                SimpleNamespace(data_collection_tag="table"),
                SimpleNamespace(data_collection_tag="broken"),
            ],
        )
        project = SimpleNamespace(name="Iris", workflows=[workflow], joins=None)

        def fake_helper(**kwargs):
            if kwargs["mode"] == "scan":
                return {"covered_dcs": [], "complete": True}
            failed = kwargs["data_collection_tag"] == "broken"
            return {"total_failed": int(failed), "failed_tags": ["broken"] if failed else []}

        calls = SimpleNamespace(
            helper=MagicMock(side_effect=fake_helper),
            images=MagicMock(return_value=[image_dc]),
            upload=MagicMock(),
            finish_run=MagicMock(),
        )
        monkeypatch.setattr(projects_collection, "find_one", lambda *_a, **_k: {"_id": "p"})
        monkeypatch.setattr(projects.ProjectBeanie, "from_mongo", MagicMock())
        monkeypatch.setattr(projects.Project, "model_validate", lambda *_a, **_k: project)
        monkeypatch.setattr(
            ingestion_tasks,
            "build_server_cli_config",
            lambda _uid: SimpleNamespace(user=SimpleNamespace(email="a@b.c")),
        )
        for name in ("mark_job_running", "update_job_progress", "finish_job"):
            monkeypatch.setattr(jobs_store, name, MagicMock())
        monkeypatch.setattr(monitoring_store, "create_ingestion_run", MagicMock())
        monkeypatch.setattr(monitoring_store, "upsert_ingestion_step", MagicMock())
        monkeypatch.setattr(monitoring_store, "finish_ingestion_run", calls.finish_run)
        monkeypatch.setattr(helpers, "process_project_helper", calls.helper)
        monkeypatch.setattr(image_upload, "image_collections_to_upload", calls.images)
        monkeypatch.setattr(image_upload, "upload_collection_images", calls.upload)

        outcome = ingestion_tasks.run_project_ingestion.run(
            {
                "job_id": "j",
                "run_id": "r",
                "project_id": "507f1f77bcf86cd799439011",
                "user_id": "507f1f77bcf86cd799439012",
            }
        )
        return calls, outcome, image_dc

    def test_workflows_are_selected_by_tag_not_name(self, harness):
        # The CLI helpers filter on workflow_tag; a bare name matches nothing.
        calls, _outcome, _image_dc = harness

        assert {c.kwargs["workflow_name"] for c in calls.helper.call_args_list} == {"python/iris"}

    def test_a_failure_reported_by_the_helper_counts_as_failed(self, harness):
        calls, outcome, _image_dc = harness

        assert outcome["data_collections_failed"] == ["broken"]
        assert outcome["data_collections_processed"] == 1
        assert calls.finish_run.call_args.kwargs["status"] == "partial"

    def test_images_are_uploaded_after_their_table(self, harness):
        # `depictio ingest` uploads an image collection's files once its table
        # is written; the server-side path must not silently skip that step.
        calls, _outcome, image_dc = harness

        assert calls.images.call_args_list[0].kwargs == {
            "workflow_name": "python/iris",
            "data_collection_tag": "table",
        }
        assert calls.upload.call_args.args[0] is image_dc
