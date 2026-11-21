"""Harness of the UI-join tests: real Delta tables on disk, a mongomock project.

Nothing here reaches S3 or MongoDB. ``s3://<bucket>/<dc_id>`` is mapped to
``<tmp>/<dc_id>`` at the Delta helpers' seams (``read_delta_table``,
``write_delta_table``, ``read_delta_commit_info``), so the joins themselves are
the real polars joins over real Delta commits, and the collections the service
writes (projects, deltatables) are mongomock ones.

The project mirrors what the web UI builds for an upload: one workflow per
table collection (``_build_table_workflow``), the Delta table carrying the
bookkeeping columns the ingest adds (``aggregation_time``, ``depictio_run_id``
of the form ``<tag>-single-file-scan``).
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Iterator
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import mongomock
import polars as pl
import pytest
from beanie import init_beanie
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
from pymongo.errors import WriteError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.datacollections_endpoints import table_manage
from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.joins_endpoints import routes as join_routes
from depictio.api.v1.endpoints.joins_endpoints import service
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.cli.cli.utils import deltatables as cli_deltatables
from depictio.cli.cli.utils import joins as cli_joins
from depictio.cli.cli.utils.delta_versioning import read_delta_commit_info
from depictio.models.models.data_collections import Scan, ScanSingle
from depictio.models.models.projects import ProjectBeanie
from depictio.models.models.users import UserBase

BOOKKEEPING = ("aggregation_time", "depictio_run_id")


def _concrete_paths(node, parts: list[str], filters: dict, prefix: list[str]):
    """The dotted paths ``parts`` stands for, ``$[]`` / ``$[x]`` resolved to indices."""
    if not parts:
        yield ".".join(prefix)
        return
    head, rest = parts[0], parts[1:]
    if head.startswith("$[") and head.endswith("]"):
        ident = head[2:-1]
        for index, item in enumerate(node or []):
            if ident and not all(_dig(item, k) == v for k, v in filters[ident].items()):
                continue
            yield from _concrete_paths(item, rest, filters, [*prefix, str(index)])
    else:
        child = node.get(head) if isinstance(node, dict) else None
        yield from _concrete_paths(child, rest, filters, [*prefix, head])


def _dig(item, dotted: str):
    for key in dotted.split("."):
        item = item.get(key) if isinstance(item, dict) else None
    return item


def _step(node, key: str):
    return node[int(key)] if isinstance(node, list) else node.get(key)


def _apply(doc: dict, op: str, path: str, value, strict_null: bool) -> None:
    """One ``$set`` / ``$push`` / ``$pull`` of ``value`` at the concrete ``path`` of ``doc``."""
    *parents, last = path.split(".")
    node = doc
    for key in parents:
        child = _step(node, key)
        if child is None and isinstance(node, dict):
            if key in node and strict_null:
                # What MongoDB answers when a field of a null is set.
                raise WriteError(f"Cannot create field '{last}' in element {{{key}: null}}")
            child = node[key] = {}
        node = child
    if op == "$set":
        if isinstance(node, list):
            node[int(last)] = copy.deepcopy(value)
        else:
            node[last] = copy.deepcopy(value)
    elif op == "$push":
        node.setdefault(last, []).append(copy.deepcopy(value))
    elif op == "$pull":
        node[last] = [
            item
            for item in node.get(last) or []
            if not all(_dig(item, k) == v for k, v in value.items())
        ]
    else:  # pragma: no cover - the service uses these three only
        raise NotImplementedError(op)


class ArrayFilterCollection:
    """A mongomock collection that also takes ``array_filters`` and ``$[]``.

    mongomock implements neither (nor ``$pull`` inside an array element); the
    service writes its nested documents with all of them. An update that names
    ``$[...]`` is resolved against the stored document into concrete indices and
    applied here. ``strict_null`` makes it refuse, as MongoDB does, to set a
    field *of* a field that holds null.
    """

    def __init__(self, inner, strict_null: bool = False):
        self._inner = inner
        self.strict_null = strict_null

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def update_one(self, flt, update, upsert=False, array_filters=None, **kwargs):
        if not any("$[" in path for op in update.values() for path in op):
            return self._inner.update_one(flt, update, upsert=upsert, **kwargs)
        doc = self._inner.find_one(flt)
        if doc is None:
            return self._inner.update_one(flt, {"$unset": {"_none_": ""}})
        filters: dict[str, dict] = {}
        for entry in array_filters or []:
            for key, value in entry.items():
                ident, _, rest = key.partition(".")
                filters.setdefault(ident, {})[rest] = value
        updated = copy.deepcopy(doc)
        for op, fields in update.items():
            for path, value in fields.items():
                for concrete in _concrete_paths(doc, path.split("."), filters, []):
                    _apply(updated, op, concrete, value, self.strict_null)
        modified = int(updated != doc)
        if modified:
            self._inner.replace_one({"_id": doc["_id"]}, updated)
        return SimpleNamespace(matched_count=1, modified_count=modified)


def demographic_data() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "individual_id": [1, 2, 3, 4, 5, 6],
            "island": ["Torgersen", "Biscoe", "Dream", "Dream", "Biscoe", "Torgersen"],
            "sex": ["male", "female", "female", "male", "male", "female"],
            "year": [2007, 2007, 2008, 2008, 2009, 2009],
            "species": ["Adelie", "Gentoo", "Chinstrap", "Chinstrap", "Gentoo", "Adelie"],
        }
    )


def physical_features() -> pl.DataFrame:
    """Id 6 of the demographics is missing here, and id 7 is an extra."""
    return pl.DataFrame(
        {
            "individual_id": [1, 2, 3, 4, 5, 7],
            "bill_length_mm": [39.1, 46.5, 49.0, 50.2, 45.3, 41.0],
            "flipper_length_mm": [181, 215, 190, 187, 213, 195],
        }
    )


def island_info() -> pl.DataFrame:
    return pl.DataFrame(
        {"island": ["Torgersen", "Biscoe", "Dream"], "region": ["north", "east", "west"]}
    )


class JoinEnv:
    """The project, its tables on disk, and the users who may (not) edit it."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path / "delta"
        self.root.mkdir()
        self.db = mongomock.MongoClient()["joins_test"]
        self.projects = ArrayFilterCollection(self.db["projects"])
        self.project_oid = ObjectId()
        self.owner = self._user("owner@example.org")
        self.editor = self._user("editor@example.org")
        self.viewer = self._user("viewer@example.org")
        self.stranger = self._user("stranger@example.org")
        for user in (self.owner, self.editor, self.viewer, self.stranger):
            self.db["users"].insert_one({"_id": user.id, "email": user.email})
            self._token(user)
        self.db["projects"].insert_one(
            {
                "_id": self.project_oid,
                "name": "workshop",
                "is_public": False,
                "workflows": [],
                "permissions": {
                    "owners": [self._grant(self.owner)],
                    "editors": [self._grant(self.editor)],
                    "viewers": [self._grant(self.viewer)],
                },
            }
        )
        self.current: UserBase = self.owner
        self.cleaned: list[str] = []
        self.invalidated: list[str] = []
        self.app = FastAPI()
        self.app.include_router(join_routes.joins_endpoint_router, prefix="/joins")
        self.app.dependency_overrides[get_current_user] = lambda: self.current
        self.app.dependency_overrides[get_user_or_anonymous] = lambda: self.current
        self.client = TestClient(self.app)
        self.demo = self.add_table("demographic_data", demographic_data())
        self.phys = self.add_table("physical_features", physical_features())

    # ------------------------------------------------------------------ setup

    @staticmethod
    def _user(email: str) -> UserBase:
        return UserBase(id=ObjectId(), email=email, is_admin=False)

    @staticmethod
    def _grant(user: UserBase) -> dict:
        return {"_id": user.id, "email": user.email}

    def _token(self, user: UserBase) -> None:
        self.db["tokens"].insert_one(
            {
                "user_id": user.id,
                "access_token": "t",
                "refresh_token": "r",
                "token_type": "bearer",
                "name": "n",
                "token_lifetime": "long-lived",
                "expire_datetime": datetime.now() + timedelta(days=365),
                "refresh_expire_datetime": "2999-01-01 00:00:00",
                "created_at": "2024-01-01 00:00:00",
            }
        )

    def add_table(self, tag: str, frame: pl.DataFrame | None, *, kind: str = "table") -> str:
        """A table collection in a workflow of its own, as a UI upload makes it.

        ``frame=None`` is a collection nothing was ingested into. Returns the id.
        """
        workflow, dc = dc_utils._build_table_workflow(
            name=tag,
            description="",
            data_type=kind,
            file_format="csv",
            polars_kwargs={},
            lat_column=None,
            lon_column=None,
            scan=Scan(mode="single", scan_parameters=ScanSingle(filename=f"/uploads/{tag}.csv")),
            location="/uploads",
        )
        self.db["projects"].update_one(
            {"_id": self.project_oid}, {"$push": {"workflows": workflow.mongo()}}
        )
        dc_id = str(dc.id)
        if frame is not None:
            self.write(dc_id, frame.with_columns(self._bookkeeping(tag, frame.height)))
        return dc_id

    @staticmethod
    def _bookkeeping(tag: str, height: int) -> list[pl.Expr]:
        return [
            pl.lit("2025-01-01 00:00:00").alias("aggregation_time"),
            pl.lit(f"{tag}-single-file-scan").alias("depictio_run_id"),
        ]

    def write(self, dc_id: str, frame: pl.DataFrame, mode: str = "overwrite") -> None:
        frame.write_delta(
            str(self.root / dc_id),
            mode=mode,
            delta_write_options={"schema_mode": "overwrite"} if mode == "overwrite" else None,
        )

    def where(self, dc_id: str) -> str:
        return str(self.root / dc_id)

    # ---------------------------------------------------------------- project

    def project(self) -> dict:
        doc = self.db["projects"].find_one({"_id": self.project_oid})
        assert doc is not None
        return doc

    def dc_doc(self, dc_id: str) -> dict | None:
        for workflow in self.project()["workflows"]:
            for dc in workflow["data_collections"]:
                if str(dc["_id"]) == dc_id:
                    return dc
        return None

    def workflow_of(self, dc_id: str) -> dict:
        for workflow in self.project()["workflows"]:
            if any(str(dc["_id"]) == dc_id for dc in workflow["data_collections"]):
                return workflow
        raise AssertionError(f"{dc_id} is in no workflow")

    def tags(self) -> list[str]:
        return [
            dc["data_collection_tag"]
            for workflow in self.project()["workflows"]
            for dc in workflow["data_collections"]
        ]

    def joins(self) -> list[dict]:
        return self.project().get("joins") or []

    def join(self, name: str) -> dict:
        return next(j for j in self.joins() if j["name"] == name)

    def lock(self) -> None:
        self.db["projects"].update_one(
            {"_id": self.project_oid},
            {"$set": {"published_lock": {"reason": "release", "dashboard_ids": []}}},
        )

    # ------------------------------------------------------------------- data

    def read(self, dc_id: str) -> pl.DataFrame:
        return pl.read_delta(self.where(dc_id))

    def version(self, dc_id: str) -> int:
        from deltalake import DeltaTable

        return DeltaTable(self.where(dc_id)).version()

    def aggregations(self, dc_id: str) -> list[dict]:
        doc = self.db["deltatables"].find_one({"data_collection_id": ObjectId(dc_id)})
        return list((doc or {}).get("aggregation") or [])

    # ------------------------------------------------------------------- HTTP

    def request(self, user: UserBase | None, method: str, path: str, **kwargs):
        self.current = user or self.owner
        return self.client.request(method, f"/joins/{self.project_oid}{path}", **kwargs)

    def body(self, **fields) -> dict:
        body = {
            "name": "demo_phys",
            "left_dc_id": self.demo,
            "right_dc_id": self.phys,
            "on_columns": ["individual_id"],
            "how": "left",
        }
        return body | fields

    def preview(self, user: UserBase | None = None, **fields):
        return self.request(user, "POST", "/preview", json=self.body(**fields))

    def create(self, user: UserBase | None = None, **fields):
        return self.request(user, "POST", "", json=self.body(**fields))

    def create_ok(self, **fields) -> dict:
        response = self.create(**fields)
        assert response.status_code == 200, response.text
        return response.json()

    # ----------------------------------------------------------------- writes

    def append(self, dc_id: str, rows: pl.DataFrame, user: UserBase | None = None) -> dict:
        """Append rows through the web UI's own path (Manage data, Append)."""
        return table_manage.append_table_uploads(
            data_collection_id=dc_id,
            decoded_files=[(rows.write_csv().encode(), "more.csv")],
            current_user=user or self.owner,
        )


@pytest.fixture(autouse=True, scope="session")
def _beanie_models():
    """``ProjectBeanie.from_mongo`` (what the service validates documents with) needs init."""
    asyncio.run(
        init_beanie(database=AsyncMongoMockClient().beanie, document_models=[ProjectBeanie])
    )


@pytest.fixture()
def env(tmp_path) -> Iterator[JoinEnv]:
    e = JoinEnv(tmp_path)

    def local(path: str) -> str:
        return str(e.root / path.rsplit("/", 1)[-1])

    def read(path, opts):
        return _real_read(local(path), opts)

    def write(destination_file, **kwargs):
        return _real_write(destination_file=local(destination_file), **kwargs)

    def commit_info(path, opts):
        return read_delta_commit_info(local(path), opts)

    def identity_hash(location, opts):
        return _real_identity_hash(local(location), opts)

    def delete_files(dc_id: str) -> None:
        e.cleaned.append(dc_id)

    fake_user = SimpleNamespace(
        from_mongo=lambda doc: SimpleNamespace(
            turn_to_userbase=lambda: UserBase(id=doc["_id"], email=doc["email"])
        )
    )
    with ExitStack() as stack:
        stack.enter_context(patch.object(service, "projects_collection", e.projects))
        stack.enter_context(patch.object(service, "deltatables_collection", e.db["deltatables"]))
        stack.enter_context(patch.object(service, "dashboards_collection", e.db["dashboards"]))
        stack.enter_context(patch.object(service, "_delete_delta_files", delete_files))
        stack.enter_context(patch.object(dc_utils, "projects_collection", e.projects))
        stack.enter_context(patch.object(dc_utils, "tokens_collection", e.db["tokens"]))
        stack.enter_context(patch.object(dc_utils, "deltatables_collection", e.db["deltatables"]))
        stack.enter_context(patch.object(dc_utils, "_cleanup_s3_delta_table", AsyncMock()))
        stack.enter_context(
            patch.object(join_routes, "_cleanup_s3_delta_table", AsyncMock(side_effect=_record(e)))
        )
        stack.enter_context(patch.object(table_manage, "projects_collection", e.projects))
        stack.enter_context(
            patch.object(table_manage, "deltatables_collection", e.db["deltatables"])
        )
        stack.enter_context(patch.object(table_manage, "users_collection", e.db["users"]))
        stack.enter_context(patch.object(table_manage, "User", fake_user))
        stack.enter_context(patch.object(table_manage, "_delta_location_for", e.where))
        stack.enter_context(patch.object(table_manage, "polars_s3_config", {}))
        stack.enter_context(patch.object(table_manage, "s3_client", MagicMock()))
        stack.enter_context(patch.object(table_manage, "_begin_ui_ingestion_run", lambda **_: None))
        stack.enter_context(
            patch.object(
                table_manage,
                "_invalidate_table_caches_for_dc",
                lambda dc_id: e.invalidated.append(dc_id),
            )
        )
        stack.enter_context(patch.object(table_manage, "delta_identity_hash", identity_hash))
        stack.enter_context(patch.object(cli_deltatables, "read_delta_table", read))
        stack.enter_context(patch.object(cli_joins, "read_delta_table", read))
        stack.enter_context(patch.object(cli_joins, "write_delta_table", write))
        stack.enter_context(patch.object(cli_joins, "read_delta_commit_info", commit_info))
        stack.enter_context(
            patch("depictio.api.v1.permissions._default_groups_collection", lambda: e.db["groups"])
        )
        yield e


_real_read = cli_deltatables.read_delta_table
_real_write = cli_deltatables.write_delta_table
_real_identity_hash = table_manage.delta_identity_hash


def _record(e: JoinEnv):
    async def cleanup(dc_id: str) -> None:
        e.cleaned.append(dc_id)

    return cleanup


@pytest.fixture()
def bucket() -> str:
    return settings.s3.bucket
