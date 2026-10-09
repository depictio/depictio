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


def _run_pipeline(
    monkeypatch,
    tmp_path,
    *,
    roots=None,
    project_doc=None,
    joins=None,
    join_result=None,
    registered=(),
    images=("a.png",),
    all_succeed=False,
    process_raises=None,
    job_status=None,
):
    """Run the task with the CLI helpers and the job and run stores mocked.

    The data root is ``tmp_path/data`` unless ``roots`` says otherwise; the
    image collection uploads from ``tmp_path/data/images``.
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import depictio.cli.cli.utils.helpers as helpers
    import depictio.cli.cli.utils.image_upload as image_upload
    import depictio.cli.cli.utils.joins as joins_module
    from depictio.api.v1 import db as api_db
    from depictio.api.v1 import ingestion_tasks
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.db import projects_collection
    from depictio.api.v1.jobs import store as jobs_store
    from depictio.api.v1.monitoring import store as monitoring_store
    from depictio.models.models import projects

    data = tmp_path / "data"
    image_dir = data / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for name in images:
        target = image_dir / name
        if not target.exists():
            target.write_bytes(b"png")
    monkeypatch.setattr(
        settings.ingestion, "allowed_data_roots", [str(data)] if roots is None else roots
    )

    import mongomock
    from bson import ObjectId

    files = mongomock.MongoClient().db.files
    monkeypatch.setattr(api_db, "files_collection", files)
    table_id = ObjectId()
    for location in registered:
        files.insert_one({"data_collection_id": table_id, "file_location": str(location)})

    image_dc = SimpleNamespace(
        data_collection_tag="images",
        config=SimpleNamespace(
            dc_specific_properties=SimpleNamespace(local_images_path=str(image_dir))
        ),
    )
    workflow = SimpleNamespace(
        name="iris",
        workflow_tag="python/iris",
        data_collections=[
            SimpleNamespace(data_collection_tag="table", id=table_id),
            SimpleNamespace(data_collection_tag="broken"),
        ],
    )
    project = SimpleNamespace(name="Iris", workflows=[workflow], joins=joins)

    def fake_helper(**kwargs):
        if kwargs["mode"] == "scan":
            return {"covered_dcs": [], "complete": True}
        if process_raises is not None:
            raise process_raises
        failed = kwargs["data_collection_tag"] == "broken" and not all_succeed
        return {"total_failed": int(failed), "failed_tags": ["broken"] if failed else []}

    calls = SimpleNamespace(
        helper=MagicMock(side_effect=fake_helper),
        images=MagicMock(return_value=[image_dc]),
        upload=MagicMock(),
        finish_run=MagicMock(),
        finish_job=MagicMock(),
        joins=MagicMock(return_value=join_result or {"processed": [], "errors": []}),
    )
    doc = project_doc if project_doc is not None else {"_id": "p"}
    monkeypatch.setattr(projects_collection, "find_one", lambda *_a, **_k: doc)
    monkeypatch.setattr(projects.ProjectBeanie, "from_mongo", MagicMock())
    monkeypatch.setattr(projects.Project, "model_validate", lambda *_a, **_k: project)
    monkeypatch.setattr(
        ingestion_tasks,
        "build_server_cli_config",
        lambda _uid: SimpleNamespace(user=SimpleNamespace(email="a@b.c")),
    )
    for name in ("mark_job_running", "update_job_progress"):
        monkeypatch.setattr(jobs_store, name, MagicMock())
    monkeypatch.setattr(jobs_store, "get_job", MagicMock(return_value={"status": job_status}))
    monkeypatch.setattr(jobs_store, "finish_job", calls.finish_job)
    monkeypatch.setattr(monitoring_store, "create_ingestion_run", MagicMock())
    monkeypatch.setattr(monitoring_store, "upsert_ingestion_step", MagicMock())
    monkeypatch.setattr(monitoring_store, "finish_ingestion_run", calls.finish_run)
    monkeypatch.setattr(helpers, "process_project_helper", calls.helper)
    monkeypatch.setattr(image_upload, "image_collections_to_upload", calls.images)
    monkeypatch.setattr(image_upload, "upload_collection_images", calls.upload)
    monkeypatch.setattr(joins_module, "process_project_joins", calls.joins)

    payload = {
        "job_id": "j",
        "run_id": "r",
        "project_id": "507f1f77bcf86cd799439011",
        "user_id": "507f1f77bcf86cd799439012",
    }
    try:
        outcome = ingestion_tasks.run_project_ingestion.run(payload)
    except Exception as exc:  # noqa: BLE001 - the task re-raises; tests inspect it
        outcome = exc
    return calls, outcome, image_dc


class TestServerSidePipeline:
    """The task drives the CLI's own helpers; these pin how it calls them."""

    @pytest.fixture
    def harness(self, monkeypatch, tmp_path):
        return _run_pipeline(monkeypatch, tmp_path)

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


class TestJoinFailures:
    """A failed join leaves its joined table stale; the run and job must say so.

    The run status used to be computed before the joins ran, so a failed join
    only ever reached the joins step: the run read ``success`` and the job had
    no error to show.
    """

    FAILED_JOIN = {"processed": [], "errors": [{"join": "penguins_joined", "errors": ["x"]}]}

    def test_a_failed_join_makes_a_clean_run_partial(self, monkeypatch, tmp_path):
        calls, outcome, _ = _run_pipeline(
            monkeypatch, tmp_path, joins=["j"], join_result=self.FAILED_JOIN, all_succeed=True
        )

        assert outcome["data_collections_failed"] == []
        assert outcome["joins_failed"] == ["penguins_joined"]
        run = calls.finish_run.call_args.kwargs
        assert run["status"] == "partial"
        assert run["error"] == "1 join(s) failed: penguins_joined"
        # A partial run is still a successful job, but the job now says why.
        job = calls.finish_job.call_args.kwargs
        assert job["status"] == "success"
        assert job["error"] == "1 join(s) failed: penguins_joined"

    def test_collection_and_join_failures_are_both_reported(self, monkeypatch, tmp_path):
        calls, _outcome, _ = _run_pipeline(
            monkeypatch, tmp_path, joins=["j"], join_result=self.FAILED_JOIN
        )

        error = calls.finish_run.call_args.kwargs["error"]
        assert "1 data collection(s) failed: broken" in error
        assert "1 join(s) failed: penguins_joined" in error

    def test_a_clean_run_records_no_error(self, monkeypatch, tmp_path):
        calls, _outcome, _ = _run_pipeline(
            monkeypatch,
            tmp_path,
            joins=["j"],
            join_result={"processed": ["j"], "errors": []},
            all_succeed=True,
        )

        assert calls.finish_run.call_args.kwargs["status"] == "success"
        assert calls.finish_run.call_args.kwargs["error"] is None
        assert calls.finish_job.call_args.kwargs["error"] is None


# ── Allowed data roots ──────────────────────────────────────────────────────


@pytest.fixture
def roots(monkeypatch, tmp_path):
    """``tmp_path/data`` is the one allowed root; ``tmp_path/secret`` is not."""
    from depictio.api.v1.configs.config import settings

    data = tmp_path / "data"
    secret = tmp_path / "secret"
    data.mkdir()
    secret.mkdir()
    (secret / "keys.csv").write_text("private")
    monkeypatch.setattr(settings.ingestion, "allowed_data_roots", [str(data)])
    return data, secret


class TestAllowedRoots:
    def test_no_roots_refuses_and_names_the_setting(self, monkeypatch, tmp_path):
        from depictio.api.v1.configs.config import settings
        from depictio.api.v1.ingestion_roots import ALLOWED_ROOTS_ENV, roots_refusal

        monkeypatch.setattr(settings.ingestion, "allowed_data_roots", [])

        refusal, outside = roots_refusal(_project([str(tmp_path)]))

        assert refusal is not None and ALLOWED_ROOTS_ENV in refusal
        assert outside == []

    def test_a_location_inside_a_root_is_allowed(self, roots):
        from depictio.api.v1.ingestion_roots import roots_refusal

        data, _ = roots
        (data / "run1").mkdir()

        assert roots_refusal(_project([str(data / "run1")])) == (None, [])

    def test_a_location_outside_every_root_is_refused_without_naming_it(self, roots):
        from depictio.api.v1.ingestion_roots import roots_refusal

        _, secret = roots

        refusal, outside = roots_refusal(_project([str(secret)]))

        assert refusal is not None
        assert str(secret) not in refusal
        assert outside == [str(secret)]

    def test_dot_dot_cannot_climb_out(self, roots):
        from depictio.api.v1.ingestion_roots import roots_refusal

        data, _ = roots

        refusal, _ = roots_refusal(_project([f"{data}/../secret"]))

        assert refusal is not None

    def test_a_symlinked_location_is_judged_by_its_target(self, roots):
        from depictio.api.v1.ingestion_roots import roots_refusal

        data, secret = roots
        (data / "innocent").symlink_to(secret)

        refusal, _ = roots_refusal(_project([str(data / "innocent")]))

        assert refusal is not None

    def test_a_sibling_with_a_common_prefix_is_not_inside(self, roots, tmp_path):
        from depictio.api.v1.ingestion_roots import roots_refusal

        (tmp_path / "data-other").mkdir()

        refusal, _ = roots_refusal(_project([str(tmp_path / "data-other")]))

        assert refusal is not None

    def test_single_file_and_image_paths_are_checked_too(self, roots):
        from depictio.api.v1.ingestion_roots import project_read_paths, roots_refusal

        data, secret = roots
        project = _project([str(data)])
        project["workflows"][0]["data_collections"] = [
            {
                "config": {
                    "scan": {
                        "mode": "single",
                        "scan_parameters": {"filename": str(secret / "keys.csv")},
                    }
                }
            },
            {"config": {"dc_specific_properties": {"local_images_path": str(secret)}}},
        ]

        assert set(project_read_paths(project)) >= {str(secret / "keys.csv"), str(secret)}
        refusal, outside = roots_refusal(project)
        assert refusal is not None
        assert len(outside) == 2

    def test_settings_accept_a_comma_separated_or_json_list(self, monkeypatch):
        from depictio.api.v1.configs.settings_models import IngestionConfig

        monkeypatch.setenv("DEPICTIO_INGESTION_ALLOWED_DATA_ROOTS", "/data/runs, /mnt/shared")
        assert IngestionConfig().allowed_data_roots == ["/data/runs", "/mnt/shared"]

        monkeypatch.setenv("DEPICTIO_INGESTION_ALLOWED_DATA_ROOTS", '["/data/runs", "/mnt/a"]')
        assert IngestionConfig().allowed_data_roots == ["/data/runs", "/mnt/a"]

        monkeypatch.delenv("DEPICTIO_INGESTION_ALLOWED_DATA_ROOTS")
        assert IngestionConfig().allowed_data_roots == []


class TestTaskReadsNothingOutsideRoots:
    """The task checks again, and checks what the scan registered."""

    def test_no_roots_fails_before_any_scan(self, monkeypatch, tmp_path):
        calls, outcome, _ = _run_pipeline(monkeypatch, tmp_path, roots=[])

        assert isinstance(outcome, PermissionError)
        assert "DEPICTIO_INGESTION_ALLOWED_DATA_ROOTS" in str(outcome)
        calls.helper.assert_not_called()
        assert calls.finish_job.call_args.kwargs["status"] == "failed"

    def test_a_project_pointing_outside_fails_before_any_scan(self, monkeypatch, tmp_path):
        secret = tmp_path / "secret"
        secret.mkdir()

        calls, outcome, _ = _run_pipeline(
            monkeypatch, tmp_path, project_doc={"_id": "p", **_project([str(secret)])}
        )

        assert isinstance(outcome, PermissionError)
        assert str(secret) not in str(outcome)
        calls.helper.assert_not_called()

    def test_a_registered_file_symlinked_out_of_the_root_is_not_processed(
        self, monkeypatch, tmp_path
    ):
        secret = tmp_path / "secret"
        secret.mkdir()
        (secret / "keys.csv").write_text("private")
        data = tmp_path / "data"
        data.mkdir()
        (data / "keys.csv").symlink_to(secret / "keys.csv")

        calls, outcome, _ = _run_pipeline(
            monkeypatch, tmp_path, registered=[data / "keys.csv"], all_succeed=True
        )

        processed = [
            c.kwargs["data_collection_tag"]
            for c in calls.helper.call_args_list
            if c.kwargs["mode"] == "process"
        ]
        assert "table" not in processed
        assert "table" in outcome["data_collections_failed"]
        (refused,) = calls.finish_run.call_args.kwargs["errors"]
        assert refused["kind"] == "outside_data_roots"
        assert str(secret) not in refused["message"]

    def test_files_inside_the_root_are_processed(self, monkeypatch, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        (data / "iris.csv").write_text("a\n1\n")

        _calls, outcome, _ = _run_pipeline(
            monkeypatch, tmp_path, registered=[data / "iris.csv"], all_succeed=True
        )

        assert outcome["data_collections_failed"] == []

    def test_an_image_symlinked_out_of_the_root_is_not_uploaded(self, monkeypatch, tmp_path):
        secret = tmp_path / "secret"
        secret.mkdir()
        (secret / "photo.png").write_bytes(b"png")
        image_dir = tmp_path / "data" / "images"
        image_dir.mkdir(parents=True)
        (image_dir / "photo.png").symlink_to(secret / "photo.png")

        calls, outcome, _ = _run_pipeline(monkeypatch, tmp_path, all_succeed=True)

        calls.upload.assert_not_called()
        assert "table" in outcome["data_collections_failed"]


# ── Endpoints ───────────────────────────────────────────────────────────────


@pytest.fixture
def api(monkeypatch, roots):
    """The projects router over mongomock, with the trigger switched on."""
    from types import SimpleNamespace

    import mongomock
    from bson import ObjectId
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from depictio.api.v1 import ingestion_tasks
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.endpoints.projects_endpoints import routes
    from depictio.api.v1.endpoints.user_endpoints import routes as user_routes
    from depictio.api.v1.jobs import store as jobs_store

    data, secret = roots
    db = mongomock.MongoClient().db
    monkeypatch.setattr(routes, "projects_collection", db.projects)
    monkeypatch.setattr(jobs_store, "jobs_collection", db.jobs)
    monkeypatch.setattr(settings.ingestion, "browser_trigger", True)
    monkeypatch.setattr(settings.jobs, "enabled", True)
    dispatched = []

    class _Task:
        def apply_async(self, *args, **kwargs):
            dispatched.append(kwargs)
            return SimpleNamespace(id="celery-1")

    monkeypatch.setattr(ingestion_tasks, "run_project_ingestion", _Task())

    editor = SimpleNamespace(id=ObjectId(), is_admin=False, is_anonymous=False, email="e@x.org")
    admin = SimpleNamespace(id=ObjectId(), is_admin=True, is_anonymous=False, email="a@x.org")

    def make_project(locations):
        pid = ObjectId()
        db.projects.insert_one(
            {
                "_id": pid,
                "name": f"p-{pid}",
                "permissions": {"owners": [], "editors": [{"_id": editor.id}], "viewers": []},
                "workflows": [{"data_location": {"structure": "flat", "locations": locations}}],
            }
        )
        return str(pid)

    app = FastAPI()
    app.include_router(routes.projects_endpoint_router, prefix="/projects")
    who = {"user": editor}
    app.dependency_overrides[user_routes.get_current_user] = lambda: who["user"]
    app.dependency_overrides[user_routes.get_user_or_anonymous] = lambda: who["user"]
    return SimpleNamespace(
        client=TestClient(app),
        who=who,
        editor=editor,
        admin=admin,
        make_project=make_project,
        db=db,
        data=data,
        secret=secret,
        dispatched=dispatched,
        ingestion_tasks=ingestion_tasks,
    )


class TestTriggerEndpoints:
    def test_status_refuses_outside_roots_with_a_count_only(self, api):
        pid = api.make_project([str(api.secret)])

        body = api.client.get(f"/projects/ingestion/trigger-status/{pid}").json()

        assert body["available"] is False
        assert "DEPICTIO_INGESTION_ALLOWED_DATA_ROOTS" in body["reason"]
        assert body["outside_roots_count"] == 1
        assert str(api.secret) not in str(body)

    def test_status_shows_admins_the_paths(self, api):
        pid = api.make_project([str(api.secret)])
        api.who["user"] = api.admin

        body = api.client.get(f"/projects/ingestion/trigger-status/{pid}").json()

        assert body["outside_roots"] == [str(api.secret)]

    def test_status_does_not_echo_unreachable_paths_to_non_admins(self, api):
        missing = str(api.data / "not-mounted")
        pid = api.make_project([missing])

        body = api.client.get(f"/projects/ingestion/trigger-status/{pid}").json()

        assert body["available"] is False
        assert body["unreachable_count"] == 1
        assert missing not in str(body)

        api.who["user"] = api.admin
        admin_body = api.client.get(f"/projects/ingestion/trigger-status/{pid}").json()
        assert admin_body["unreachable_locations"] == [missing]

    def test_status_is_available_inside_the_roots(self, api):
        pid = api.make_project([str(api.data)])

        body = api.client.get(f"/projects/ingestion/trigger-status/{pid}").json()

        assert body == {"enabled": True, "available": True, "reason": None}

    def test_trigger_outside_the_roots_is_403_and_names_the_setting(self, api):
        pid = api.make_project([str(api.secret)])

        response = api.client.post(f"/projects/ingestion/trigger/{pid}")

        assert response.status_code == 403
        assert "DEPICTIO_INGESTION_ALLOWED_DATA_ROOTS" in response.json()["detail"]
        assert str(api.secret) not in response.json()["detail"]
        assert api.dispatched == []
        assert api.db.jobs.count_documents({}) == 0

    def test_trigger_without_roots_is_403(self, api, monkeypatch):
        from depictio.api.v1.configs.config import settings

        monkeypatch.setattr(settings.ingestion, "allowed_data_roots", [])
        pid = api.make_project([str(api.data)])

        response = api.client.post(f"/projects/ingestion/trigger/{pid}")

        assert response.status_code == 403
        assert "DEPICTIO_INGESTION_ALLOWED_DATA_ROOTS" in response.json()["detail"]

    def test_trigger_inside_the_roots_dispatches(self, api):
        pid = api.make_project([str(api.data)])

        response = api.client.post(f"/projects/ingestion/trigger/{pid}")

        assert response.status_code == 200
        assert response.json()["already_running"] is False
        assert len(api.dispatched) == 1

    def test_a_second_trigger_after_the_first_finished_creates_a_new_job(self, api):
        """The keyless-job collision of the old sparse index, end to end."""
        from depictio.api.v1.jobs import store as jobs_store

        jobs_store.ensure_jobs_storage()
        pid = api.make_project([str(api.data)])
        first = api.client.post(f"/projects/ingestion/trigger/{pid}").json()
        jobs_store.finish_job(first["job_id"], status="success")

        second = api.client.post(f"/projects/ingestion/trigger/{pid}")

        assert second.status_code == 200
        assert second.json()["job_id"] != first["job_id"]

    def test_broker_down_fails_the_job_and_answers_503(self, api, monkeypatch):
        """Otherwise the job sat pending, and every later trigger answered
        "already running" until the job's retention expired."""
        from depictio.api.v1.jobs import store as jobs_store

        class _Down:
            def apply_async(self, *args, **kwargs):
                from kombu.exceptions import OperationalError

                raise OperationalError("broker down")

        monkeypatch.setattr(api.ingestion_tasks, "run_project_ingestion", _Down())
        pid = api.make_project([str(api.data)])

        response = api.client.post(f"/projects/ingestion/trigger/{pid}")

        assert response.status_code == 503
        (job,) = list(api.db.jobs.find({}))
        assert job["status"] == "failed"
        assert jobs_store.find_active_job(kind="project.ingest", project_id=pid) is None


class TestCancel:
    """A cancel reaches a prefork worker as ``SoftTimeLimitExceeded``."""

    def test_a_cancel_mid_collection_stops_the_run_and_records_it_interrupted(
        self, monkeypatch, tmp_path
    ):
        from celery.exceptions import SoftTimeLimitExceeded

        calls, outcome, _ = _run_pipeline(
            monkeypatch,
            tmp_path,
            process_raises=SoftTimeLimitExceeded(),
            job_status="cancelled",
        )

        assert isinstance(outcome, SoftTimeLimitExceeded)
        # One collection attempted, then the run stopped: not "one failed,
        # carry on with the next".
        processed = [c for c in calls.helper.call_args_list if c.kwargs["mode"] == "process"]
        assert len(processed) == 1
        calls.upload.assert_not_called()
        run = calls.finish_run.call_args.kwargs
        assert run["status"] == "interrupted"
        assert run["error"] == "Cancelled"

    def test_a_soft_time_limit_without_a_cancel_is_a_failure(self, monkeypatch, tmp_path):
        from celery.exceptions import SoftTimeLimitExceeded

        calls, _outcome, _ = _run_pipeline(
            monkeypatch,
            tmp_path,
            process_raises=SoftTimeLimitExceeded(),
            job_status="running",
        )

        assert calls.finish_run.call_args.kwargs["status"] == "failed"
