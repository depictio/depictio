"""``/projects/builder/{capabilities,tree,suggest,match,tracks_manifest,template,metadata}``
on the main API.

The routes are the core's (``depictio.project_builder.routes``); what is under
test here is how the main API opens the root a request names, which has to be
exactly as the run-folder dialog opens it: a folder on the server's disk only
under ``depictio local``, for an administrator on this machine, below an
allowed root; an ``s3://`` prefix only where the configuration allows it, listed
once a minute per caller. Every refusal answers ``{detail, code}``.

No network, no MongoDB: users are overridden, S3 is the shared CLI stub, and the
metadata fetches are replaced at the remote-fetch gateway.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.routing import Match

from depictio.api.v1 import remote_fetch
from depictio.api.v1.endpoints import routers
from depictio.api.v1.endpoints.projects_endpoints import builder, routes
from depictio.api.v1.endpoints.projects_endpoints.builder import builder_endpoint_router
from depictio.api.v1.endpoints.user_endpoints import routes as user_routes
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.users import UserBase
from depictio.models.s3_access import S3AccessError, S3Target
from depictio.tests.cli.project_builder._fixtures import QUANT, RUN_TREE
from depictio.tests.cli.s3_stubs import (
    MEGATEST_TREE,
    S3_BUCKET,
    S3_KEY_PREFIX,
    S3_ROOT,
    install_s3_listing,
    write_tree,
)

PREFIX = "/depictio/api/v1/projects/builder"
LOOPBACK = "http://localhost:8058"
BUILDER_PATHS = ("tree", "suggest", "match", "tracks_manifest", "template", "metadata")


def _user(is_admin: bool = True) -> UserBase:
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=is_admin)


class _Caller:
    """The user the routes see; changed per test."""

    def __init__(self, user):
        self.user = user

    def __call__(self):
        return self.user


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    """Server context (importing the CLI app flips the process to ``CLI``), local
    folders off and no bucket listed unless a test turns them on; no listing
    carried over from another test."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    for name in (
        "DEPICTIO_LOCAL_DATA_ROOTS",
        "DEPICTIO_AUTH_SINGLE_USER_MODE",
        "DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS",
        "DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS",
    ):
        monkeypatch.delenv(name, raising=False)
    builder._ROOTS.clear()
    yield
    builder._ROOTS.clear()


@pytest.fixture
def caller():
    return _Caller(_user())


def _app(caller_) -> FastAPI:
    """The builder router alone, mounted where the main API mounts it."""
    app = FastAPI()
    app.include_router(builder_endpoint_router, prefix=PREFIX)

    @app.exception_handler(S3AccessError)
    async def s3_access(_request, exc: S3AccessError):  # the main app's own handler
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code}
        )

    app.dependency_overrides[get_user_or_anonymous] = caller_
    return app


@pytest.fixture
def client(caller) -> TestClient:
    """A caller on this machine (a loopback ``Host``)."""
    return TestClient(_app(caller), base_url=LOOPBACK)


@pytest.fixture
def remote_client(caller) -> TestClient:
    """The same app reached by a name that is not this machine."""
    return TestClient(_app(caller), base_url="http://depictio.example.org")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Local folders on, ``home/`` the one root, the pipeline run at ``home/run42``."""
    folder = tmp_path / "home"
    write_tree(folder / "run42", RUN_TREE)
    (folder / ".hidden-runs" / "run1").mkdir(parents=True)
    (folder / "depictio-local").mkdir()
    outside = tmp_path / "outside"
    write_tree(outside, RUN_TREE)
    (folder / "escape").symlink_to(outside)
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(folder))
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(folder / "depictio-local"))
    return folder


@pytest.fixture
def run_root(home) -> dict:
    return {"data_root": str(home / "run42")}


def _post(client, route: str, **body):
    return client.post(f"{PREFIX}/{route}", json=body)


def _draft(*collections: dict, name: str = "Lab QC") -> dict:
    return {"name": name, "workflows": [{"name": "main", "data_collections": list(collections)}]}


SHEET = {
    "tag": "sheet",
    "type": "table",
    "mode": "single",
    "path": "samplesheet.csv",
    "props": {"kind": "table", "format": "csv", "separator": ","},
}
QUANT_DC = {
    "tag": "quant",
    "type": "table",
    "mode": "recursive",
    "regex": r"^quant\.tsv$",
    "props": {"kind": "table", "format": "tsv", "separator": "\t"},
}
IMAGES = {
    "tag": "imgs",
    "type": "image",
    "mode": "single",
    "path": "images.csv",
    "props": {"kind": "image", "image_column": "img", "local_images_path": "images"},
}


# ── the routes on a folder of this computer ──────────────────────────────────


class TestOnALocalFolder:
    def test_tree_lists_one_folder_level(self, client, run_root, home):
        response = _post(client, "tree", root=run_root)
        assert response.status_code == 200
        body = response.json()
        assert body["path"] == "" and body["is_remote"] is False
        assert body["root_label"] == str(home / "run42")
        assert [e["name"] for e in body["entries"]] == [
            "images",
            "multiqc",
            "regions",
            "star",
            "trees",
            "variants",
            "images.csv",
            "samplesheet.csv",
        ]
        inner = _post(client, "tree", root=run_root, path="star").json()
        assert [e["path"] for e in inner["entries"]] == ["star/S1", "star/S2", "star/S3"]

    def test_tree_leaves_hidden_entries_out(self, client, home, run_root):
        (home / "run42" / ".cache").mkdir()
        (home / "run42" / "node_modules").mkdir()
        names = {e["name"] for e in _post(client, "tree", root=run_root).json()["entries"]}
        assert not names & {".cache", "node_modules"}

    def test_tree_of_a_missing_folder_is_a_404(self, client, run_root):
        response = _post(client, "tree", root=run_root, path="nope")
        assert response.status_code == 404
        assert response.json()["code"] == "folder_missing"

    def test_suggest_guesses_the_collection(self, client, run_root):
        response = _post(
            client,
            "suggest",
            root=run_root,
            path="star/S1/quant.tsv",
            examples=["star/S2/quant.tsv"],
        )
        assert response.status_code == 200
        body = response.json()
        assert (body["type"], body["mode"], body["glob"]) == (
            "table",
            "recursive",
            "star/S*/quant.tsv",
        )
        assert body["format"] == "tsv"

    def test_suggest_of_a_missing_file_is_a_404(self, client, run_root):
        response = _post(client, "suggest", root=run_root, path="nope.csv")
        assert (response.status_code, response.json()["code"]) == (404, "file_missing")

    def test_suggest_takes_at_most_fifty_examples(self, client, run_root):
        response = _post(
            client,
            "suggest",
            root=run_root,
            path="samplesheet.csv",
            examples=[f"star/S{i}/quant.tsv" for i in range(51)],
        )
        assert response.status_code == 422

    def test_match_lists_what_the_scan_would_ingest(self, client, run_root):
        response = _post(
            client,
            "match",
            root=run_root,
            workflow={"structure": "flat"},
            collection=QUANT_DC,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["files"] == ["star/S1/quant.tsv", "star/S2/quant.tsv", "star/S3/quant.tsv"]
        assert body["count"] == 3 and body["consistent"] is True
        assert body["schema"] == {"gene": "String", "count": "Int64"}

    def test_match_without_a_workflow_is_a_flat_one(self, client, run_root):
        response = _post(client, "match", root=run_root, collection=QUANT_DC)
        assert response.json()["count"] == 3

    def test_match_with_sequencing_runs(self, client, home, run_root):
        for run in ("run_1", "run_2"):
            write_tree(home / "run42" / run, {"quant.tsv": QUANT})
        response = _post(
            client,
            "match",
            root=run_root,
            workflow={"structure": "sequencing-runs", "runs_regex": r"^run_\d$"},
            collection=QUANT_DC,
        )
        body = response.json()
        assert body["runs"] == ["run_1", "run_2"]
        assert body["files"] == ["run_1/quant.tsv", "run_2/quant.tsv"]

    def test_match_with_a_bad_regex_is_a_400_with_its_code(self, client, run_root):
        collection = {**QUANT_DC, "regex": "("}
        response = _post(client, "match", root=run_root, collection=collection)
        assert (response.status_code, response.json()["code"]) == (400, "regex_invalid")

    def test_a_path_leaving_the_root_is_a_400_on_every_route(self, client, run_root):
        for route, body in (
            ("tree", {"path": "../x"}),
            ("suggest", {"path": "/etc/passwd"}),
            ("match", {"collection": {**SHEET, "path": "../x.csv"}}),
        ):
            response = _post(client, route, root=run_root, **body)
            assert response.status_code == 400, route
            assert response.json()["code"] == "builder_path_refused", route

    def test_a_symlink_out_of_the_allowed_folders_is_not_listed(self, client, home, run_root):
        # Not below /tmp either: the server's own folders (uploads) are readable.
        (home / "run42" / "leak").symlink_to("/usr")
        (home / "run42" / "inside").symlink_to(home / "run42" / "star")
        names = {e["name"] for e in _post(client, "tree", root=run_root).json()["entries"]}
        assert "leak" not in names
        assert "inside" in names

    def test_template_builds_and_validates_the_template(self, client):
        response = _post(client, "template", draft=_draft(SHEET, QUANT_DC), remote=False)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"template", "yaml", "template_id", "warnings"}
        assert body["template_id"] == "custom/lab-qc"
        assert body["template"]["template"]["template_id"] == "custom/lab-qc"
        assert body["yaml"].startswith("# Defined with the Depictio Project Builder.")
        assert "{DATA_ROOT}/samplesheet.csv" in body["yaml"]
        assert body["warnings"] == []

    def test_template_of_an_image_warns_about_the_bucket_folder(self, client):
        body = _post(client, "template", draft=_draft(SHEET, IMAGES)).json()
        assert len(body["warnings"]) == 1 and "s3_base_folder" in body["warnings"][0]

    def test_template_for_a_prefix_warns_about_bounds(self, client):
        bounded = {**QUANT_DC, "max_depth": 2}
        body = _post(client, "template", draft=_draft(bounded), remote=True).json()
        assert "local folders only" in body["warnings"][0]

    def test_template_a_draft_the_rules_refuse_is_a_422_with_the_code(self, client):
        response = _post(client, "template", draft=_draft(SHEET, IMAGES), remote=True)
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "inline_template_invalid"
        assert "Images are uploaded from a folder on this computer" in body["detail"]

    def test_template_with_duplicate_tags_is_refused_by_name(self, client):
        response = _post(client, "template", draft=_draft(SHEET, {**QUANT_DC, "tag": "sheet"}))
        assert response.status_code == 422
        assert response.json()["code"] == "inline_template_invalid"
        assert "'sheet'" in response.json()["detail"]

    def test_a_draft_of_the_wrong_shape_is_the_frameworks_422_without_a_code(self, client):
        response = _post(client, "template", draft={"name": ""})
        assert response.status_code == 422
        assert "code" not in response.json()
        assert isinstance(response.json()["detail"], list)

    def test_a_draft_with_an_unknown_field_is_refused(self, client):
        response = _post(client, "template", draft={**_draft(SHEET), "dashboards": ["x"]})
        assert response.status_code == 422


# ── the caller ───────────────────────────────────────────────────────────────

ROUTE_BODIES = {
    "tree": {"root": {"data_root": "/nowhere"}},
    "suggest": {"root": {"data_root": "/nowhere"}, "path": "a.csv"},
    "match": {"root": {"data_root": "/nowhere"}, "collection": SHEET},
    "tracks_manifest": {"root": {"data_root": "/nowhere"}, "files": ["a.bam"]},
    "template": {"draft": _draft(SHEET)},
    "metadata": {"repo_url": "https://github.com/nf-core/rnaseq"},
}


class TestWhoMayAsk:
    @pytest.mark.parametrize("route", BUILDER_PATHS)
    def test_no_user_is_a_401(self, caller, client, route):
        caller.user = None
        response = client.post(f"{PREFIX}/{route}", json=ROUTE_BODIES[route])
        assert response.status_code == 401
        assert response.json() == {"detail": "User not found."}

    @pytest.mark.parametrize("route", BUILDER_PATHS)
    def test_no_token_is_a_401_from_the_real_dependency(self, monkeypatch, route):
        """Not overridden: the module's own dependency, with no single-user or public mode."""
        monkeypatch.setattr(
            user_routes,
            "settings",
            SimpleNamespace(auth=SimpleNamespace(is_public_mode=False, is_single_user_mode=False)),
        )
        app = FastAPI()
        app.include_router(builder_endpoint_router, prefix=PREFIX)
        response = TestClient(app, base_url=LOOPBACK).post(
            f"{PREFIX}/{route}", json=ROUTE_BODIES[route]
        )
        assert response.status_code == 401

    @pytest.mark.parametrize("route", BUILDER_PATHS)
    def test_public_mode_is_for_administrators_only(self, monkeypatch, caller, client, route):
        public = MagicMock()
        public.auth.is_public_mode = True
        monkeypatch.setattr(routes, "settings", public)
        caller.user = _user(is_admin=False)
        response = client.post(f"{PREFIX}/{route}", json=ROUTE_BODIES[route])
        assert response.status_code == 403
        assert "public/demo mode" in response.json()["detail"]
        assert "Project creation" in response.json()["detail"]

    def test_an_administrator_passes_the_public_mode_gate(self, monkeypatch, caller, client):
        public = MagicMock()
        public.auth.is_public_mode = True
        monkeypatch.setattr(routes, "settings", public)
        assert _post(client, "template", draft=_draft(SHEET)).status_code == 200

    def test_a_non_administrator_may_build_a_template_when_public_mode_is_off(self, caller, client):
        caller.user = _user(is_admin=False)
        assert _post(client, "template", draft=_draft(SHEET)).status_code == 200


class TestLocalFolderGates:
    def test_local_folders_are_refused_when_the_server_does_not_read_its_own_disk(
        self, client, tmp_path
    ):
        write_tree(tmp_path / "run42", RUN_TREE)
        for route, extra in (
            ("tree", {}),
            ("suggest", {"path": "samplesheet.csv"}),
            ("match", {"collection": SHEET}),
        ):
            response = _post(client, route, root={"data_root": str(tmp_path / "run42")}, **extra)
            assert response.status_code == 422, route
            assert response.json()["code"] == "local_folders_off", route

    def test_a_foreign_host_is_refused_for_a_local_folder(self, remote_client, run_root):
        for route, extra in (
            ("tree", {}),
            ("suggest", {"path": "samplesheet.csv"}),
            ("match", {"collection": SHEET}),
        ):
            response = _post(remote_client, route, root=run_root, **extra)
            assert response.status_code == 403, route
            assert response.json()["code"] == "non_loopback_host", route
            assert "can only be used from this computer" in response.json()["detail"]

    @pytest.mark.parametrize("host", ["localhost:8058", "127.0.0.1:8058", "[::1]:8058"])
    def test_a_loopback_host_is_accepted(self, caller, run_root, host):
        client = TestClient(_app(caller), base_url=f"http://{host}")
        assert _post(client, "tree", root=run_root).status_code == 200

    def test_a_rebinding_host_name_is_refused(self, caller, run_root):
        client = TestClient(_app(caller), base_url="http://localhost.evil.example:8058")
        response = _post(client, "tree", root=run_root)
        assert (response.status_code, response.json()["code"]) == (403, "non_loopback_host")

    def test_a_local_folder_is_for_an_administrator(self, caller, client, run_root):
        caller.user = _user(is_admin=False)
        response = _post(client, "tree", root=run_root)
        assert (response.status_code, response.json()["code"]) == (403, "local_admin_only")

    @pytest.mark.parametrize(
        ("rel", "code"),
        [
            ("escape", "local_path_outside"),
            ("run42/../../outside", "local_path_outside"),
            (".hidden-runs/run1", "local_path_hidden"),
            ("depictio-local", "local_path_denied"),
            ("nope", "local_path_missing"),
            ("run42/samplesheet.csv", "local_path_not_a_folder"),
        ],
    )
    def test_a_folder_the_policy_refuses_is_a_422_with_its_code(self, client, home, rel, code):
        response = _post(client, "tree", root={"data_root": f"{home}/{rel}"})
        assert (response.status_code, response.json()["code"]) == (422, code)

    def test_a_tilde_path_is_the_servers_home(self, client, home, monkeypatch):
        monkeypatch.setenv("HOME", str(home))
        response = _post(client, "tree", root={"data_root": "~/run42"})
        assert response.status_code == 200
        assert response.json()["root_label"] == str((home / "run42").resolve())

    def test_a_huge_folder_is_refused_for_a_match_but_can_still_be_browsed(
        self, client, home, run_root, monkeypatch
    ):
        """A match walks the folder, so the size cap applies; browsing a parent
        folder and picking a file must keep working for a home folder of any size."""
        from depictio.api.v1.endpoints.projects_endpoints import from_run

        monkeypatch.setattr(from_run, "MAX_LOCAL_RUN_FILES", len(RUN_TREE) - 1)
        refused = _post(client, "match", root=run_root, collection=SHEET)
        assert (refused.status_code, refused.json()["code"]) == (422, "local_run_too_large")
        assert _post(client, "tree", root=run_root).status_code == 200
        assert _post(client, "suggest", root=run_root, path="samplesheet.csv").status_code == 200

    def test_a_relative_path_is_not_a_local_folder(self, client, home):
        response = _post(client, "tree", root={"data_root": "run42"})
        assert (response.status_code, response.json()["code"]) == (422, "data_root_unsupported")

    def test_the_gates_do_not_apply_to_what_reads_no_folder(self, remote_client, caller, home):
        """A template is built from the draft alone, so any caller may ask, wherever from."""
        caller.user = _user(is_admin=False)
        assert _post(remote_client, "template", draft=_draft(SHEET)).status_code == 200

    def test_storage_settings_typed_in_for_a_private_bucket_are_validated(self, client):
        spec = {"data_root": S3_ROOT, "storage": {"endpoint_url": 3}}
        response = _post(client, "tree", root=spec)
        assert (response.status_code, response.json()["code"]) == (422, "storage_invalid")

    def test_storage_settings_without_keys_are_refused(self, client):
        spec = {"data_root": S3_ROOT, "storage": {"endpoint_url": "https://s3.example.org"}}
        response = _post(client, "tree", root=spec)
        assert response.status_code == 422
        assert "access key" in response.json()["detail"].lower()

    def test_a_secret_of_the_wrong_type_is_not_answered_back(self, client):
        storage = {
            "endpoint_url": "https://s3.example.org",
            "access_key_id": "AKIA-EXAMPLE",
            "secret_access_key": {"value": "SECRET-VALUE-0123"},
        }
        response = _post(client, "tree", root={"data_root": S3_ROOT, "storage": storage})
        assert response.status_code == 422
        assert "SECRET-VALUE-0123" not in response.text


# ── an s3:// prefix ──────────────────────────────────────────────────────────


@pytest.fixture
def s3(monkeypatch):
    """The megatest prefix served by the stub, with its bucket on the administrator's list."""
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", S3_BUCKET)
    return install_s3_listing(monkeypatch, MEGATEST_TREE, key_prefix=S3_KEY_PREFIX)


class TestOnAnS3Prefix:
    def test_tree_lists_the_prefix_for_any_caller(self, caller, remote_client, s3):
        caller.user = _user(is_admin=False)
        body = _post(remote_client, "tree", root={"data_root": S3_ROOT}).json()
        assert body["is_remote"] is True and body["root_label"] == S3_ROOT
        assert [e["name"] for e in body["entries"]] == [
            "input",
            "multiqc",
            "pipeline_info",
            "qiime2",
        ]

    def test_suggest_and_match_read_the_same_prefix(self, client, s3):
        root = {"data_root": S3_ROOT}
        suggestion = _post(client, "suggest", root=root, path="input/samplesheet.csv").json()
        assert suggestion["type"] == "table" and suggestion["format"] == "csv"
        collection = {
            **QUANT_DC,
            "tag": "levels",
            "regex": r"^qiime2/barplot/level-\d\.csv$",
            "props": {"kind": "table", "format": "csv", "separator": ","},
        }
        matched = _post(client, "match", root=root, collection=collection).json()
        assert matched["files"] == ["qiime2/barplot/level-2.csv"]

    def test_match_over_a_prefix_says_bounds_do_not_apply(self, client, s3):
        collection = {**QUANT_DC, "regex": r"^.*\.csv$", "max_depth": 0}
        body = _post(client, "match", root={"data_root": S3_ROOT}, collection=collection).json()
        # A depth of 0 would keep the root's own files only.
        assert body["files"] == ["input/samplesheet.csv", "qiime2/barplot/level-2.csv"]
        assert body["warnings"] == [
            "max_depth and ignore apply to local folders only: an S3 prefix is listed whole."
        ]

    def test_the_prefix_is_listed_once_for_the_questions_that_follow(self, client, s3):
        root = {"data_root": S3_ROOT}
        _post(client, "tree", root=root)
        _post(client, "tree", root=root, path="input")
        _post(client, "suggest", root=root, path="input/samplesheet.csv")
        _post(client, "match", root=root, collection=SHEET)
        assert len(s3.listings) == 1

    def test_refresh_lists_the_prefix_again(self, client, s3):
        _post(client, "tree", root={"data_root": S3_ROOT})
        _post(client, "tree", root={"data_root": S3_ROOT, "refresh": True})
        assert len(s3.listings) == 2
        # And the fresh listing is the one kept.
        _post(client, "tree", root={"data_root": S3_ROOT})
        assert len(s3.listings) == 2

    def test_another_caller_does_not_share_the_listing(self, caller, client, s3):
        _post(client, "tree", root={"data_root": S3_ROOT})
        caller.user = _user()
        _post(client, "tree", root={"data_root": S3_ROOT})
        assert len(s3.listings) == 2

    def test_another_prefix_is_listed_on_its_own(self, client, s3):
        _post(client, "tree", root={"data_root": S3_ROOT})
        _post(client, "tree", root={"data_root": f"{S3_ROOT}/input"})
        assert len(s3.listings) == 2

    def test_a_bucket_the_administrator_did_not_list_is_refused_before_any_client_is_built(
        self, monkeypatch, client
    ):
        monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "some-other-bucket")
        monkeypatch.setattr(
            S3Target, "client", lambda _target: pytest.fail("an S3 client was built")
        )
        response = _post(client, "tree", root={"data_root": "s3://private-bucket/run1"})
        assert response.status_code == 422
        assert response.json()["code"] == "s3_refused"
        assert "s3://private-bucket/run1" in response.json()["detail"]

    def test_a_malformed_prefix_is_a_422(self, client):
        response = _post(client, "tree", root={"data_root": "s3://"})
        assert response.status_code == 422

    def test_other_schemes_are_refused_by_name(self, client):
        response = _post(client, "tree", root={"data_root": "https://example.org/run1"})
        assert (response.status_code, response.json()["code"]) == (422, "data_root_unsupported")

    def test_a_template_for_a_prefix_refuses_indexed_files_and_images(self, client):
        response = _post(client, "template", draft=_draft(SHEET, IMAGES), remote=True)
        assert response.status_code == 422 and response.json()["code"] == "inline_template_invalid"


# ── repository metadata ──────────────────────────────────────────────────────

REPO = "https://github.com/nf-core/rnaseq"
RAW = "https://raw.githubusercontent.com/nf-core/rnaseq/HEAD"
CRATE = {
    "@graph": [
        {"@id": "ro-crate-metadata.json", "about": {"@id": "./"}},
        {"@id": "./", "name": "nf-core/rnaseq", "version": "3.14.0", "description": "RNA-seq"},
    ]
}


class TestMetadata:
    @pytest.fixture
    def gateway(self, monkeypatch):
        """The remote-fetch gateway, answering from a few documents."""
        asked: list[str] = []

        def text(url, **kwargs):
            asked.append(url)
            if url == f"{RAW}/ro-crate-metadata.json":
                return json.dumps(CRATE)
            raise remote_fetch.RemoteFetchFailed("Could not fetch the provided URL.")

        def blob(url, **kwargs):
            asked.append(url)
            if url.endswith("_logo_light.png"):
                return b"\x89PNG"
            raise remote_fetch.RemoteFetchFailed("Could not fetch the provided URL.")

        monkeypatch.setattr(remote_fetch, "fetch_validated_text", text)
        monkeypatch.setattr(remote_fetch, "fetch_validated_bytes", blob)
        return asked

    def test_it_returns_what_the_repository_says_through_the_gateway(self, client, gateway):
        response = _post(client, "metadata", repo_url=REPO)
        assert response.status_code == 200
        body = response.json()
        assert body["repository_url"] == REPO
        assert (body["name"], body["version"]) == ("nf-core/rnaseq", "3.14.0")
        assert body["engine"] == "nextflow"
        assert body["catalog"] == {"name": "nf-core", "url": REPO}
        assert body["logo_light"].startswith("data:image/png;base64,")
        assert body["logo_dark"] == body["logo_light"]
        assert body["sources"] == ["nf-core", "ro-crate", "logo"]
        assert body["blocked"] is False
        assert f"{RAW}/ro-crate-metadata.json" in gateway

    def test_a_policy_refusal_is_reported_not_raised(self, monkeypatch, client):
        def refuse(url, **kwargs):
            raise remote_fetch.RemoteURLRejected("host not allowed")

        monkeypatch.setattr(remote_fetch, "fetch_validated_text", refuse)
        monkeypatch.setattr(remote_fetch, "fetch_validated_bytes", refuse)
        response = _post(client, "metadata", repo_url=REPO)
        assert response.status_code == 200
        assert response.json()["blocked"] is True

    @pytest.mark.parametrize("url", ["", "   ", "ftp://github.com/a/b", "github.com/a/b"])
    def test_a_url_that_is_not_http_is_a_400(self, client, gateway, url):
        response = _post(client, "metadata", repo_url=url)
        assert (response.status_code, response.json()["code"]) == (400, "repo_url_invalid")
        assert gateway == []

    def test_another_host_is_answered_without_fetching_anything(self, client, gateway):
        body = _post(client, "metadata", repo_url="https://gitlab.com/a/b").json()
        assert body == {
            "repository_url": "https://gitlab.com/a/b",
            "sources": [],
            "blocked": False,
        }
        assert gateway == []

    def test_a_very_long_url_is_refused_by_the_model(self, client, gateway):
        response = _post(client, "metadata", repo_url="https://github.com/" + "a" * 600)
        assert response.status_code == 422
        assert gateway == []


# ── capabilities, track manifests and the v2 options ─────────────────────────


class TestCapabilities:
    @pytest.mark.parametrize("enabled", [True, False])
    def test_realtime_is_what_the_server_does_with_the_flag(self, monkeypatch, client, enabled):
        from depictio.api.v1.configs.config import settings

        monkeypatch.setattr(settings.events, "enabled", enabled)
        body = client.get(f"{PREFIX}/capabilities").json()
        assert body["mode"] == "server"
        assert body["realtime"]["events_enabled"] is enabled
        assert (body["realtime"]["reason"] is None) is enabled
        assert {"type": "genomic_tracks", "available": False} == {
            k: v for k, v in body["dc_types"][6].items() if k != "reason"
        }

    def test_capabilities_need_a_caller(self, caller, client):
        caller.user = None
        assert client.get(f"{PREFIX}/capabilities").status_code == 401

    def test_capabilities_are_behind_the_public_mode_gate(self, monkeypatch, caller, client):
        public = MagicMock()
        public.auth.is_public_mode = True
        monkeypatch.setattr(routes, "settings", public)
        caller.user = _user(is_admin=False)
        assert client.get(f"{PREFIX}/capabilities").status_code == 403


class TestTracksManifest:
    def test_picked_tracks_become_a_manifest(self, client, run_root):
        response = _post(
            client,
            "tracks_manifest",
            root=run_root,
            files=["variants/S1.vcf.gz", "variants/S1.vcf.gz.tbi", "variants/S2.vcf.gz"],
        )
        assert response.status_code == 200
        body = response.json()
        assert [row["uri"] for row in body["rows"]] == ["variants/S1.vcf.gz", "variants/S2.vcf.gz"]
        assert body["rows"][0]["index_uri"] == "variants/S1.vcf.gz.tbi"
        assert body["tsv"].startswith("track_id\tsample\tformat\turi\tindex_uri\tname\n")
        assert "need an index" in body["warnings"][0]

    def test_a_path_leaving_the_root_is_a_400(self, client, run_root):
        response = _post(client, "tracks_manifest", root=run_root, files=["../escape.bam"])
        assert (response.status_code, response.json()["code"]) == (400, "builder_path_refused")

    def test_no_track_among_the_files_is_a_422(self, client, run_root):
        response = _post(client, "tracks_manifest", root=run_root, files=["samplesheet.csv"])
        assert (response.status_code, response.json()["code"]) == (422, "tracks_none")

    def test_the_local_folder_gates_apply(self, remote_client, run_root):
        response = _post(remote_client, "tracks_manifest", root=run_root, files=["a.bam"])
        assert response.status_code == 403


class TestTemplateOptions:
    def test_wildcards_links_and_reader_options_reach_the_template(self, client):
        quant = {
            **QUANT_DC,
            "regex": r"^star/{sample}/quant\.tsv$",
            "wildcards": [{"name": "sample", "regex": "[^/]+"}],
        }
        sheet = {
            **SHEET,
            "metatype": "Metadata",
            "props": {**SHEET["props"], "reader": {"comment_prefix": "#", "null_values": ["NA"]}},
        }
        draft = {
            **_draft(sheet, quant),
            "data_management_platform_project_url": "https://lims.example.org/p/9",
            "links": [
                {
                    "source_tag": "sheet",
                    "source_column": "sample",
                    "target_tag": "quant",
                    "target_field": "sample",
                }
            ],
        }
        response = _post(client, "template", draft=draft)
        assert response.status_code == 200, response.text
        template = response.json()["template"]
        collections = template["workflows"][0]["data_collections"]
        assert collections[0]["config"]["dc_specific_properties"]["polars_kwargs"] == {
            "separator": ",",
            "comment_prefix": "#",
            "null_values": ["NA"],
        }
        assert collections[1]["config"]["scan"]["scan_parameters"]["regex_config"]["wildcards"] == [
            {"name": "sample", "wildcard_regex": "[^/]+"}
        ]
        assert template["links"][0]["target_type"] == "table"
        assert template["data_management_platform_project_url"] == "https://lims.example.org/p/9"

    def test_an_unavailable_kind_is_refused_with_its_reason(self, client):
        tracks = {
            "tag": "tracks",
            "type": "genomic_tracks",
            "mode": "single",
            "path": "tracks.tsv",
            "props": {"kind": "genomic_tracks"},
        }
        response = _post(client, "template", draft=_draft(tracks))
        assert response.status_code == 422
        assert "no genome-browser track collections yet" in response.json()["detail"]

    def test_a_bad_wildcard_is_refused_with_the_code(self, client):
        quant = {
            **QUANT_DC,
            "regex": r"^{SAMPLE}\.tsv$",
            "wildcards": [{"name": "SAMPLE", "regex": "x"}],
        }
        response = _post(client, "template", draft=_draft(quant))
        assert (response.status_code, response.json()["code"]) == (422, "inline_template_invalid")
        assert "reads as a template variable" in response.json()["detail"]


# ── where the router is mounted ──────────────────────────────────────────────


class TestMountedOnTheMainRouter:
    @pytest.fixture
    def main_client(self, caller) -> TestClient:
        """The API's real router (every endpoint router, in its real order)."""
        app = FastAPI()
        app.include_router(routers.router, prefix="/depictio/api/v1")
        app.dependency_overrides[get_user_or_anonymous] = caller
        return TestClient(app, base_url=LOOPBACK)

    def test_tree_resolves_to_the_builder_route(self, main_client, run_root):
        response = main_client.post(f"{PREFIX}/tree", json={"root": run_root})
        assert response.status_code == 200
        assert response.json()["root_label"] == run_root["data_root"]

    @pytest.mark.parametrize("route", BUILDER_PATHS)
    def test_every_builder_path_is_answered_by_the_builder_router(self, route):
        scope = {
            "type": "http",
            "method": "POST",
            "path": f"/projects/builder/{route}",
            "root_path": "",
            "headers": [],
        }
        for included in routers.router.routes:
            match, _child = included.matches(scope)
            if match == Match.FULL:
                break
        else:  # pragma: no cover
            pytest.fail(f"nothing answers POST /projects/builder/{route}")
        original = getattr(included, "original_router", None)
        if original is not None:
            assert original is builder_endpoint_router
        else:  # an older FastAPI flattens the included routes
            assert included.endpoint in {r.endpoint for r in builder_endpoint_router.routes}

    def test_the_projects_routes_still_answer_their_own_paths(self):
        for path in ("/projects/create", "/projects/some-id/export_template"):
            scope = {"type": "http", "method": "POST", "path": path, "root_path": "", "headers": []}
            first = next(r for r in routers.router.routes if r.matches(scope)[0] == Match.FULL)
            assert getattr(first, "original_router", None) is not builder_endpoint_router

    def test_the_builder_is_documented_under_its_own_tag(self, main_client):
        paths = main_client.app.openapi()["paths"]
        for route in BUILDER_PATHS:
            operation = paths[f"{PREFIX}/{route}"]["post"]
            assert operation["tags"] == ["Project Builder"]

    def test_a_get_is_not_a_builder_route(self, main_client):
        assert main_client.get(f"{PREFIX}/tree").status_code in (404, 405)

    def test_capabilities_resolve_to_the_builder_not_a_project_id(self, main_client):
        response = main_client.get(f"{PREFIX}/capabilities")
        assert response.status_code == 200
        assert response.json()["mode"] == "server"
