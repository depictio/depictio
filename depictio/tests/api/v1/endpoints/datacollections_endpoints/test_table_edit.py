"""Cell edits on a table a user added: PATCH /datacollections/{id}/cells.

A real Delta table on disk, a mongomock project; the HTTP layer is the real
router so the error bodies are what the viewer receives.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import mongomock
import polars as pl
import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.endpoints.datacollections_endpoints import table_edit, table_manage
from depictio.api.v1.endpoints.datacollections_endpoints.routes import (
    datacollections_endpoint_router,
)
from depictio.api.v1.endpoints.projects_endpoints import publish_lock
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.models.models.users import UserBase

DC_ID = ObjectId()
PROJECT_ID = ObjectId()

UPLOAD_ORIGIN = {"kind": "upload", "location": "samples.csv"}


def _user(**flags) -> SimpleNamespace:
    return SimpleNamespace(
        id=ObjectId(), email="u@example.org", is_admin=False, is_anonymous=False, **flags
    )


def _table() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sample": ["s1", "s2", "s3"],
            "age": [10, 20, 30],
            "score": [1.5, 2.5, 3.5],
            "flag": [True, False, True],
            "day": [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)],
            "aggregation_time": ["2025-01-01 00:00:00"] * 3,
        }
    )


class Env:
    def __init__(self, tmp_path):
        self.location = str(tmp_path / "delta")
        _table().write_delta(self.location)
        self.db = mongomock.MongoClient()["t"]
        self.user = _user()
        self.invalidated: list[str] = []
        self.app = FastAPI()
        self.app.include_router(datacollections_endpoint_router, prefix="/datacollections")
        self.current = self.user
        self.app.dependency_overrides[get_current_user] = lambda: self.current
        self.app.dependency_overrides[get_user_or_anonymous] = lambda: self.current
        self.client = TestClient(self.app)

    def project(self, *, origin=UPLOAD_ORIGIN, config=None, locked=False, **roles):
        doc = {
            "_id": PROJECT_ID,
            "is_public": False,
            "permissions": {
                "owners": [],
                "editors": [],
                "viewers": [],
                **{k: [{"_id": u.id} for u in v] for k, v in roles.items()},
            },
            "workflows": [
                {
                    "_id": ObjectId(),
                    "data_collections": [
                        {
                            "_id": DC_ID,
                            "data_collection_tag": "samples",
                            "config": config
                            if config is not None
                            else {"type": "table", "source": "native", "origin": origin},
                        }
                    ],
                }
            ],
        }
        if locked:
            doc["published_lock"] = {"reason": "release", "dashboard_ids": []}
        self.db["projects"].delete_many({})
        self.db["projects"].insert_one(doc)

    def read(self) -> pl.DataFrame:
        return pl.read_delta(self.location)

    def version(self) -> int:
        from deltalake import DeltaTable

        return DeltaTable(self.location).version()

    def patch(self, edits, base_version=None):
        base = self.version() if base_version is None else base_version
        return self.client.patch(
            f"/datacollections/{DC_ID}/cells", json={"base_version": base, "edits": edits}
        )


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    e.db["users"].insert_one({"_id": e.user.id})
    fake_user = SimpleNamespace(
        from_mongo=lambda doc: SimpleNamespace(
            turn_to_userbase=lambda: UserBase(id=e.user.id, email=e.user.email)
        )
    )
    with (
        patch.object(table_edit, "projects_collection", e.db["projects"]),
        patch.object(table_edit, "_delta_location_for", lambda _dc: e.location),
        patch.object(table_manage, "_delta_location_for", lambda _dc: e.location),
        patch.object(table_edit, "polars_s3_config", {}),
        patch.object(table_manage, "polars_s3_config", {}),
        patch.object(table_manage, "deltatables_collection", e.db["deltatables"]),
        patch.object(table_manage, "users_collection", e.db["users"]),
        patch.object(table_manage, "User", fake_user),
        patch.object(
            table_manage,
            "_invalidate_table_caches_for_dc",
            lambda dc_id: e.invalidated.append(dc_id),
        ),
    ):
        yield e


def _cell(row, column, value):
    return {"row": row, "column": column, "value": value}


class TestEdit:
    def test_owner_edit_keeps_types_and_publishes_a_new_version(self, env):
        env.project(owners=[env.user])
        before = env.version()

        response = env.patch(
            [
                _cell(0, "sample", "renamed"),
                _cell(1, "age", "42"),
                _cell(2, "score", 9.25),
                _cell(0, "flag", "no"),
                _cell(1, "day", "2026-02-03"),
            ]
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["changed_cells"] == 5
        assert body["delta_version"] == before + 1
        after = env.read()
        assert after.schema == _table().schema
        assert after["sample"].to_list() == ["renamed", "s2", "s3"]
        assert after["age"].to_list() == [10, 42, 30]
        assert after["score"].to_list() == [1.5, 2.5, 9.25]
        assert after["flag"].to_list() == [False, False, True]
        assert after["day"].to_list()[1] == date(2026, 2, 3)
        # Bookkeeping columns are left alone.
        assert after["aggregation_time"].to_list() == ["2025-01-01 00:00:00"] * 3

    def test_every_reader_is_told(self, env):
        """An aggregation entry salts the cache keys; the cached frames are dropped."""
        env.project(editors=[env.user])
        env.patch([_cell(0, "age", 11)])
        env.patch([_cell(0, "age", 12)])

        record = env.db["deltatables"].find_one({"data_collection_id": DC_ID})
        versions = [a["aggregation_version"] for a in record["aggregation"]]
        assert versions == [1, 2]
        assert record["aggregation"][-1]["delta_version"] == env.version()
        assert record["aggregation"][-1]["rows_total"] == 3
        assert env.invalidated == [str(DC_ID), str(DC_ID)]

    def test_blank_clears_a_cell(self, env):
        env.project(owners=[env.user])
        assert env.patch([_cell(0, "age", ""), _cell(1, "sample", None)]).status_code == 200
        after = env.read()
        assert after["age"].to_list() == [None, 20, 30]
        assert after["sample"].to_list() == ["s1", None, "s3"]

    def test_an_edit_that_changes_nothing_writes_nothing(self, env):
        env.project(owners=[env.user])
        before = env.version()
        response = env.patch([_cell(0, "age", "10")])
        assert response.status_code == 200
        assert response.json()["changed_cells"] == 0
        assert env.version() == before
        assert env.invalidated == []

    def test_edit_data_returns_rows_and_the_version(self, env):
        env.project(owners=[env.user])
        response = env.client.get(f"/datacollections/{DC_ID}/edit_data")
        assert response.status_code == 200
        body = response.json()
        assert body["delta_version"] == env.version()
        assert [c["name"] for c in body["columns"]] == ["sample", "age", "score", "flag", "day"]
        assert {c["name"]: c["kind"] for c in body["columns"]}["day"] == "date"
        assert body["rows"][1] == {
            "sample": "s2",
            "age": 20,
            "score": 2.5,
            "flag": False,
            "day": "2025-01-02",
        }


class TestTypeErrors:
    def test_422_names_the_row_and_column_and_writes_nothing(self, env):
        env.project(owners=[env.user])
        before = env.version()

        response = env.patch([_cell(0, "sample", "fine"), _cell(1, "age", "twenty")])

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "invalid_cells"
        assert "Row 2" in detail["message"] and "'age'" in detail["message"]
        assert detail["errors"] == [
            {"row": 1, "column": "age", "message": "expected a whole number"}
        ]
        assert env.version() == before
        assert env.read()["sample"].to_list() == ["s1", "s2", "s3"]

    @pytest.mark.parametrize(
        "column, value",
        [
            ("age", 2.5),
            ("score", "abc"),
            ("flag", "maybe"),
            ("day", "not-a-date"),
            ("age", True),
            ("nope", "x"),
            ("aggregation_time", "x"),
        ],
    )
    def test_values_that_do_not_fit_are_refused(self, env, column, value):
        env.project(owners=[env.user])
        before = env.version()
        response = env.patch([_cell(0, column, value)])
        assert response.status_code == 422
        assert env.version() == before

    def test_a_row_that_does_not_exist_is_refused(self, env):
        env.project(owners=[env.user])
        response = env.patch([_cell(3, "age", 1)])
        assert response.status_code == 422
        assert response.json()["detail"]["errors"][0]["message"] == "no such row"


class TestLostUpdates:
    def test_a_stale_version_is_a_409_and_nothing_is_written(self, env):
        env.project(owners=[env.user])
        stale = env.version()
        assert env.patch([_cell(0, "age", 11)]).status_code == 200
        before = env.version()

        response = env.patch([_cell(0, "age", 99)], base_version=stale)

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "stale_version"
        assert detail["current_version"] == before
        assert env.version() == before
        assert env.read()["age"].to_list()[0] == 11


class TestWhoMayEdit:
    def test_a_viewer_is_refused_and_still_reads_the_state(self, env):
        env.project(viewers=[env.user])
        before = env.version()

        response = env.patch([_cell(0, "age", 1)])
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "read_only_role"
        assert env.client.get(f"/datacollections/{DC_ID}/edit_data").status_code == 403
        assert env.version() == before

        status = env.client.get(f"/datacollections/{DC_ID}/edit_status").json()
        assert status["table_editable"] is True
        assert status["can_edit"] is False
        assert status["role_can_edit"] is False

    def test_someone_who_cannot_see_the_project_gets_a_404(self, env):
        env.project()
        assert env.patch([_cell(0, "age", 1)]).status_code == 404

    def test_a_sysadmin_may(self, env):
        env.project()
        env.current = SimpleNamespace(
            id=env.user.id, email="a@example.org", is_admin=True, is_anonymous=False
        )
        assert env.patch([_cell(0, "age", 1)]).status_code == 200


class TestWhichTables:
    @pytest.mark.parametrize("kind", ["run", "manifest", "url"])
    def test_a_table_not_added_by_a_user_is_refused(self, env, kind):
        env.project(owners=[env.user], origin={"kind": kind, "location": "x"})
        before = env.version()

        response = env.patch([_cell(0, "age", 1)])

        assert response.status_code == 403
        assert response.json()["detail"]["code"] in {"pipeline_table", "url_table"}
        assert env.version() == before
        status = env.client.get(f"/datacollections/{DC_ID}/edit_status").json()
        assert status["table_editable"] is False
        assert status["can_edit"] is False
        assert status["role_can_edit"] is True
        assert status["reason"]

    def test_a_table_added_from_a_folder_is_editable(self, env):
        env.project(owners=[env.user], origin={"kind": "folder", "location": "/data"})
        assert env.patch([_cell(0, "age", 1)]).status_code == 200

    def test_no_marker_means_not_editable(self, env):
        env.project(owners=[env.user], origin=None)
        assert env.patch([_cell(0, "age", 1)]).status_code == 403

    def test_an_upload_from_before_origin_existed_is_recognised_by_its_temp_dir(self, env):
        scan = {
            "mode": "single",
            "scan_parameters": {"filename": "/tmp/depictio_upload_ab12/samples.csv"},
        }
        env.project(
            owners=[env.user],
            config={"type": "table", "source": "native", "scan": scan},
        )
        assert env.patch([_cell(0, "age", 1)]).status_code == 200

    def test_a_cli_scan_is_not_mistaken_for_an_upload(self, env):
        scan = {"mode": "single", "scan_parameters": {"filename": "/data/run1/samples.csv"}}
        env.project(
            owners=[env.user],
            config={"type": "table", "source": "native", "scan": scan},
        )
        assert env.patch([_cell(0, "age", 1)]).status_code == 403

    def test_a_joined_table_is_refused_whatever_its_origin(self, env):
        env.project(
            owners=[env.user],
            config={"type": "table", "source": "joined", "origin": UPLOAD_ORIGIN},
        )
        assert env.patch([_cell(0, "age", 1)]).status_code == 403

    def test_a_multiqc_collection_is_refused(self, env):
        env.project(owners=[env.user], config={"type": "multiqc", "origin": UPLOAD_ORIGIN})
        assert env.patch([_cell(0, "age", 1)]).status_code == 403


class TestPublishLockAndLimits:
    def test_a_published_project_is_read_only(self, env):
        env.project(owners=[env.user], locked=True)
        before = env.version()

        response = env.patch([_cell(0, "age", 1)])

        assert response.status_code == 409
        assert response.json()["detail"] == publish_lock.LOCKED_DETAIL
        assert env.version() == before
        status = env.client.get(f"/datacollections/{DC_ID}/edit_status").json()
        assert (status["table_editable"], status["can_edit"]) == (True, False)
        assert status["role_can_edit"] is True
        assert status["code"] == "published_lock"

    def test_a_table_over_the_row_limit_is_refused(self, env):
        env.project(owners=[env.user])
        with patch.object(table_edit, "MAX_EDITABLE_ROWS", 2):
            read = env.client.get(f"/datacollections/{DC_ID}/edit_data")
            write = env.patch([_cell(0, "age", 1)])
        assert read.status_code == 413
        assert write.status_code == 413
        assert write.json()["detail"]["code"] == "table_too_large"

    def test_a_table_without_data_is_a_404(self, env):
        env.project(owners=[env.user])
        with patch.object(table_edit, "_delta_location_for", lambda _dc: env.location + "-none"):
            assert env.client.get(f"/datacollections/{DC_ID}/edit_data").status_code == 404
