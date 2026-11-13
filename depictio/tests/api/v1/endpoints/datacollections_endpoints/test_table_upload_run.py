"""The ingestion run a UI table upload opens names the project that owns the data collection.

Without a ``project_id`` the run never reaches the project's ingestion history
(``GET /projects/ingestion-runs/{project_id}`` filters on it).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import mongomock
from bson import ObjectId

from depictio.api.v1.endpoints.datacollections_endpoints import table_manage
from depictio.api.v1.monitoring import store


def test_ui_upload_run_carries_the_project(monkeypatch):
    database = mongomock.MongoClient()["t"]
    project_id = ObjectId()
    dc_id = str(ObjectId())
    user = SimpleNamespace(id=ObjectId(), email="u@example.org")
    monkeypatch.setattr(
        table_manage.settings, "monitoring", SimpleNamespace(enabled=True), raising=False
    )

    with (
        patch.object(store, "ingestion_runs_collection", database["ingestion_runs"]),
        patch.object(
            table_manage,
            "_load_table_dc",
            return_value=({"_id": project_id, "name": "Demo"}, {"_id": ObjectId(dc_id)}),
        ),
        patch.object(
            table_manage, "_write_table_upload", return_value={"rows_added": 1, "rows_total": 1}
        ),
    ):
        table_manage._process_table_uploads(
            data_collection_id=dc_id,
            decoded_files=[(b"a,b\n1,2\n", "x.csv")],
            current_user=user,
            mode="append",
        )

    (run,) = list(database["ingestion_runs"].find())
    assert run["project_id"] == str(project_id)
    assert run["project_name"] == "Demo"
    assert run["status"] == "success"
