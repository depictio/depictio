"""``project:<id>`` channel: who may subscribe, and the event a finished run publishes."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.events_endpoints import routes as events_routes
from depictio.api.v1.monitoring import store
from depictio.api.v1.services.events import publish
from depictio.api.v1.services.events.connection_manager import ConnectionManager

PROJECT_ID = str(ObjectId())


@pytest.fixture
def feature_on(monkeypatch):
    monkeypatch.setattr(publish.settings.dashboard_versions, "changes_since_enabled", True)
    monkeypatch.setattr(publish.settings.events, "enabled", True)
    monkeypatch.setattr(events_routes.settings.dashboard_versions, "changes_since_enabled", True)


@pytest.fixture
def redis():
    client = MagicMock()
    with patch("depictio.api.v1.monitoring.publish.get_sync_redis", return_value=client):
        yield client


def _run(**over):
    run = {
        "run_id": "run-1",
        "project_id": PROJECT_ID,
        "project_name": "rnaseq",
        "status": "success",
        "run_tags": ["run_c"],
        "data_collections": [{"tag": "multiqc_data"}, {"tag": "samples"}, {"status": "ok"}],
    }
    run.update(over)
    return run


class TestProjectChannelPermission:
    @pytest.fixture
    def projects(self):
        collection = mongomock.MongoClient().db.projects
        collection.insert_one({"_id": ObjectId(PROJECT_ID), "is_public": False})
        public = ObjectId()
        collection.insert_one({"_id": public, "is_public": True})
        with patch("depictio.api.v1.db.projects_collection", collection):
            yield SimpleNamespace(public=str(public))

    def test_a_viewer_may_subscribe(self, feature_on, projects):
        with patch(
            "depictio.api.v1.endpoints.dashboards_endpoints.routes.check_project_permission",
            return_value=True,
        ) as check:
            assert events_routes._user_can_access_dashboard(
                SimpleNamespace(is_admin=False), f"project:{PROJECT_ID}"
            )
        assert check.call_args.kwargs["required_permission"] == "viewer"

    def test_a_reader_without_access_is_refused(self, feature_on, projects):
        with patch(
            "depictio.api.v1.endpoints.dashboards_endpoints.routes.check_project_permission",
            return_value=False,
        ):
            assert not events_routes._user_can_access_dashboard(
                SimpleNamespace(is_admin=False), f"project:{PROJECT_ID}"
            )

    def test_anonymous_only_gets_public_projects(self, feature_on, projects):
        assert not events_routes._user_can_access_dashboard(None, f"project:{PROJECT_ID}")
        assert events_routes._user_can_access_dashboard(None, f"project:{projects.public}")

    def test_unknown_or_malformed_project_is_refused(self, feature_on, projects):
        assert not events_routes._user_can_access_dashboard(None, f"project:{ObjectId()}")
        assert not events_routes._user_can_access_dashboard(None, "project:not-an-id")

    def test_refused_while_the_feature_is_off(self, monkeypatch, projects):
        monkeypatch.setattr(
            events_routes.settings.dashboard_versions, "changes_since_enabled", False
        )
        assert not events_routes._user_can_access_dashboard(None, f"project:{projects.public}")


class TestPublishIngestionFinished:
    def test_publishes_the_payload_on_the_project_channel(self, feature_on, redis):
        publish.publish_ingestion_finished(_run())

        channel, raw = redis.publish.call_args.args
        assert channel == f"depictio:events:project:{PROJECT_ID}"
        message = json.loads(raw)
        assert message["event_type"] == "ingestion_finished"
        assert message["dashboard_id"] == f"project:{PROJECT_ID}"
        payload = message["payload"]
        assert payload["project_id"] == PROJECT_ID
        assert payload["project_name"] == "rnaseq"
        assert payload["run_id"] == "run-1"
        assert payload["status"] == "success"
        assert payload["run_tags"] == ["run_c"]
        assert payload["collections"] == ["multiqc_data", "samples"]
        assert payload["at"]

    @pytest.mark.parametrize("status", ["failed", "interrupted", "abandoned", "running"])
    def test_a_run_that_left_no_data_is_not_announced(self, feature_on, redis, status):
        publish.publish_ingestion_finished(_run(status=status))
        redis.publish.assert_not_called()

    def test_a_partial_run_is_announced(self, feature_on, redis):
        publish.publish_ingestion_finished(_run(status="partial"))
        redis.publish.assert_called_once()

    def test_a_run_without_a_project_is_not_announced(self, feature_on, redis):
        publish.publish_ingestion_finished(_run(project_id=None))
        redis.publish.assert_not_called()

    def test_nothing_is_published_while_the_feature_is_off(self, feature_on, redis, monkeypatch):
        monkeypatch.setattr(publish.settings.dashboard_versions, "changes_since_enabled", False)
        publish.publish_ingestion_finished(_run())
        redis.publish.assert_not_called()

    def test_a_redis_failure_never_raises(self, feature_on, redis):
        redis.publish.side_effect = RuntimeError("redis down")
        publish.publish_ingestion_finished(_run())


class TestFinishIngestionRunPublishes:
    @pytest.fixture
    def runs(self):
        collection = mongomock.MongoClient().db.ingestion_runs
        with patch.object(store, "ingestion_runs_collection", collection):
            yield collection

    def test_finishing_a_run_announces_it(self, feature_on, redis, runs):
        runs.insert_one(
            {
                "run_id": "run-1",
                "project_id": PROJECT_ID,
                "project_name": "rnaseq",
                "run_tags": ["run_c"],
                "data_collections": [{"tag": "multiqc_data"}],
                "status": "running",
            }
        )

        assert store.finish_ingestion_run("run-1", status="success")

        payload = json.loads(redis.publish.call_args.args[1])["payload"]
        assert payload["run_id"] == "run-1"
        assert payload["run_tags"] == ["run_c"]
        assert payload["collections"] == ["multiqc_data"]

    def test_an_unknown_run_announces_nothing(self, feature_on, redis, runs):
        assert not store.finish_ingestion_run("ghost", status="success")
        redis.publish.assert_not_called()

    def test_a_publish_failure_does_not_fail_the_finish(self, feature_on, runs):
        runs.insert_one({"run_id": "run-1", "project_id": PROJECT_ID, "status": "running"})
        with patch.object(publish, "publish_ingestion_finished", side_effect=RuntimeError("x")):
            assert store.finish_ingestion_run("run-1", status="success")


class TestRelayToSubscribers:
    @pytest.mark.asyncio
    async def test_a_project_message_reaches_only_its_subscribers(self):
        manager = ConnectionManager()
        mine, other = AsyncMock(), AsyncMock()
        manager._connections = {"a": mine, "b": other}
        manager._dashboard_subscriptions = {
            f"project:{PROJECT_ID}": {"a"},
            "project:other": {"b"},
        }
        message = {"event_type": "ingestion_finished", "payload": {"run_id": "run-1"}}

        await manager._handle_pubsub_message(
            f"depictio:events:project:{PROJECT_ID}", json.dumps(message)
        )

        mine.send_json.assert_awaited_once_with(message)
        other.send_json.assert_not_awaited()
