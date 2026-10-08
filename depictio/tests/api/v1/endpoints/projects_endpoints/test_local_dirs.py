"""Tests for GET /projects/local_dirs, the switch that turns local folders on, and
the capability flag ``/auth/me/optional`` gives the viewer.

Local folders are on only in server context, in single-user mode, with
``DEPICTIO_LOCAL_DATA_ROOTS`` set; the listing answers only a loopback ``Host``
and an administrator. Every refusal is ``{detail, code}``.
"""

import json
import os
import tempfile

import pytest
from bson import ObjectId
from fastapi import HTTPException
from starlette.requests import Request

from depictio.api.v1.configs import settings_models
from depictio.api.v1.endpoints.projects_endpoints import local_dirs, routes
from depictio.models.models.users import UserBase


def _user(is_admin: bool = True) -> UserBase:
    return UserBase(id=ObjectId(), email="me@example.com", is_admin=is_admin)


def _request(host: str | None = "localhost:8058") -> Request:
    headers = [(b"host", host.encode())] if host is not None else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    """Importing the CLI app sets ``DEPICTIO_CONTEXT=CLI`` for the whole process."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS", raising=False)
    monkeypatch.delenv("DEPICTIO_AUTH_SINGLE_USER_MODE", raising=False)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """An allowed root holding runs, a hidden folder, a denied local home and links."""
    root = tmp_path / "home"
    (root / "results" / "run42" / "pipeline_info").mkdir(parents=True)
    (root / "results" / "run43" / "multiqc" / "multiqc_data").mkdir(parents=True)
    (root / "results" / "notes").mkdir()
    (root / "results" / "README.txt").write_text("not a folder")
    (root / "results" / ".snapshots").mkdir()
    (root / "depictio-local").mkdir()
    (root / ".ssh").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "results" / "escape").symlink_to(outside)
    (root / "results" / "latest").symlink_to(root / "results" / "run42")

    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(root))
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(root / "depictio-local"))
    return root


def _list(path=None, *, host="localhost:8058", user=None):
    return local_dirs.list_local_dirs(path, request=_request(host), current_user=user or _user())


def _refused(path=None, **kwargs) -> local_dirs.CodedHTTPException:
    with pytest.raises(local_dirs.CodedHTTPException) as exc:
        _list(path, **kwargs)
    return exc.value


# ── the switch ───────────────────────────────────────────────────────────────


def test_local_folders_are_off_by_default():
    assert settings_models.LocalDataConfig().roots == ""
    assert settings_models.local_data_policy() is None
    assert settings_models.local_data_roots_enabled() is False


def test_roots_alone_do_not_turn_them_on(monkeypatch, tmp_path):
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(tmp_path))
    assert settings_models.local_data_policy() is None


def test_never_in_cli_context(monkeypatch, home):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
    assert settings_models.local_data_policy() is None


def test_on_with_single_user_mode_and_roots(home):
    policy = settings_models.local_data_policy()
    assert policy is not None
    assert policy.roots == (os.path.realpath(home),)
    # The local home, the user's ~/.depictio and the keys are denied.
    assert os.path.realpath(home / "depictio-local") in policy.denied
    assert os.path.realpath(os.path.expanduser("~/.depictio")) in policy.denied
    auth = settings_models.AuthConfig()
    assert os.path.realpath(auth.keys_dir) in policy.denied
    assert os.path.realpath(auth.cli_config_dir) in policy.denied
    assert os.path.realpath(settings_models.BackupConfig().backup_path) in policy.denied
    # Uploads land in the temporary directory: readable, never a root.
    assert os.path.realpath(tempfile.gettempdir()) in policy.server_dirs


def test_roots_are_comma_separated(monkeypatch, home, tmp_path):
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", f" {home} , {tmp_path / 'outside'},")
    assert settings_models.LocalDataConfig().root_list == [str(home), str(tmp_path / "outside")]


# ── the listing ──────────────────────────────────────────────────────────────


def test_without_a_path_the_roots_are_listed(home):
    listing = _list()
    assert (listing.path, listing.root, listing.parent) == (None, None, None)
    assert [(e.name, e.path) for e in listing.entries] == [("home", os.path.realpath(home))]


def test_sub_directories_sorted_with_hidden_and_escaping_ones_left_out(home):
    listing = _list(str(home / "results"))
    real = os.path.realpath(home / "results")
    assert listing.path == real
    assert listing.root == os.path.realpath(home)
    assert listing.parent == os.path.realpath(home)
    # Not README.txt (a file), not .snapshots (hidden), not escape (leaves the root).
    assert [e.name for e in listing.entries] == ["latest", "notes", "run42", "run43"]
    by_name = {e.name: e for e in listing.entries}
    # A link that stays inside reads as its target.
    assert by_name["latest"].path == os.path.join(real, "run42")
    assert by_name["run42"].looks_like_run and by_name["run43"].looks_like_run
    assert not by_name["notes"].looks_like_run
    assert listing.truncated is False


def test_has_children_counts_only_folders_the_listing_would_show(home, tmp_path):
    results = home / "results"
    (results / "notes" / ".git").mkdir()  # hidden
    (results / "notes" / "draft.txt").write_text("a file")
    (results / "linked-out").mkdir()
    (results / "linked-out" / "elsewhere").symlink_to(tmp_path / "outside")  # escapes
    by_name = {e.name: e for e in _list(str(results)).entries}
    # run42 holds pipeline_info/, latest is a link to it.
    assert by_name["run42"].has_children and by_name["latest"].has_children
    assert not by_name["notes"].has_children
    assert not by_name["linked-out"].has_children


def test_the_roots_say_whether_they_hold_folders(home):
    assert [e.has_children for e in _list().entries] == [True]


def test_the_listing_says_whether_the_folder_is_a_run(home):
    assert _list(str(home / "results" / "run42")).looks_like_run is True
    assert _list(str(home / "results")).looks_like_run is False
    assert _list().looks_like_run is False


def _make(base, paths: list[str]):
    """Each path under ``base``: a folder when it ends in ``/``, else a file."""
    for rel in paths:
        path = base / rel
        if rel.endswith("/"):
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x")
    return base


@pytest.mark.parametrize(
    "paths",
    [
        ["multiqc/multiqc_data/"],
        ["multiqc/multiqc.parquet"],
        ["multiqc/multiqc_report.html"],
        ["multiqc/Project_42_multiqc_report.html"],
        # nf-core layouts, one folder down.
        ["multiqc/star_salmon/multiqc_report.html", "multiqc/star_salmon/multiqc_report_data/"],
        ["multiqc/star_salmon/multiqc_report_data/"],
        ["multiqc/fastqc/multiqc_data/"],
        ["multiqc/aggregate/multiqc.parquet"],
    ],
)
def test_a_multiqc_folder_holding_multiqc_output_is_a_run(home, paths):
    run = _make(home / "results" / "candidate", paths)
    assert _list(str(run)).looks_like_run is True
    by_name = {e.name: e for e in _list(str(home / "results")).entries}
    assert by_name["candidate"].looks_like_run is True


@pytest.mark.parametrize(
    "paths",
    [
        # The catalog's own multiqc/: recipes, not a report.
        ["multiqc/fastqc.yaml", "multiqc/bowtie2.yaml", "multiqc/CLAUDE.md"],
        ["multiqc/fastqc/recipe.yaml"],
        ["multiqc/"],
        ["multiqc/report.html"],
        # A file named like the data folder, a report two folders down.
        ["multiqc/multiqc_data"],
        ["multiqc/a/b/multiqc_report.html"],
        ["multiqc/__pycache__/multiqc_report.html"],
    ],
)
def test_a_multiqc_folder_without_multiqc_output_is_not_a_run(home, paths):
    folder = _make(home / "results" / "lookalike", paths)
    assert _list(str(folder)).looks_like_run is False
    by_name = {e.name: e for e in _list(str(home / "results")).entries}
    assert by_name["lookalike"].looks_like_run is False


def test_only_the_first_sub_folders_of_multiqc_are_looked_into(home, monkeypatch):
    monkeypatch.setattr(local_dirs, "MULTIQC_MAX_SUB_FOLDERS", 2)
    folder = _make(
        home / "results" / "wide", ["multiqc/a/", "multiqc/b/", "multiqc/c/multiqc_data/"]
    )
    listed = []
    real_scandir = os.scandir

    def counting(path):
        listed.append(os.path.relpath(path, folder))
        return real_scandir(path)

    monkeypatch.setattr(local_dirs.os, "scandir", counting)
    assert local_dirs.looks_like_run(str(folder)) is False
    assert listed == ["multiqc", os.path.join("multiqc", "a"), os.path.join("multiqc", "b")]


@pytest.mark.parametrize("error", [PermissionError("no"), OSError("gone")])
def test_an_unreadable_multiqc_folder_is_not_a_marker(home, monkeypatch, error):
    folder = _make(home / "results" / "locked", ["multiqc/multiqc_data/"])
    real_scandir = os.scandir

    def scandir(path):
        if os.path.basename(path) == "multiqc":
            raise error
        return real_scandir(path)

    monkeypatch.setattr(local_dirs.os, "scandir", scandir)
    assert _list(str(folder)).looks_like_run is False


def test_a_marker_the_policy_refuses_does_not_count(home, tmp_path):
    _make(tmp_path / "outside", ["multiqc_data/"])
    folder = home / "results" / "linked"
    folder.mkdir()
    (folder / "pipeline_info").symlink_to(tmp_path / "outside")
    (folder / "multiqc").symlink_to(tmp_path / "outside")
    assert _list(str(folder)).looks_like_run is False


def test_noise_folders_are_not_listed_and_are_no_children(home):
    notes = home / "results" / "notes"
    _make(notes, ["__pycache__/", "node_modules/pkg/", "__MACOSX/"])
    assert _list(str(notes)).entries == []
    by_name = {e.name: e for e in _list(str(home / "results")).entries}
    assert by_name["notes"].has_children is False


def test_a_denied_folder_is_not_listed(home):
    names = [e.name for e in _list(str(home)).entries]
    assert "depictio-local" not in names
    assert names == ["results"]


def test_a_root_has_no_parent(home):
    listing = _list(str(home))
    assert listing.parent is None
    assert listing.root == listing.path == os.path.realpath(home)


def test_tilde_paths_are_the_servers_home(monkeypatch, home):
    monkeypatch.setenv("HOME", str(home))
    listing = _list("~/results")
    assert listing.path == os.path.realpath(home / "results")


def test_more_than_the_cap_is_truncated(monkeypatch, home):
    monkeypatch.setattr(local_dirs, "MAX_ENTRIES", 2)
    listing = _list(str(home / "results"))
    assert [e.name for e in listing.entries] == ["latest", "notes"]
    assert listing.truncated is True


def test_exactly_the_cap_is_not_truncated(monkeypatch, home):
    monkeypatch.setattr(local_dirs, "MAX_ENTRIES", 4)
    assert _list(str(home / "results")).truncated is False


def test_an_unreadable_folder_lists_as_empty(monkeypatch, home):
    def _denied(_path):
        raise PermissionError("no")

    monkeypatch.setattr(local_dirs.os, "scandir", _denied)
    listing = _list(str(home / "results"))
    assert listing.entries == []
    assert listing.truncated is False


# ── refusals ─────────────────────────────────────────────────────────────────


def test_404_when_off(tmp_path):
    refused = _refused(str(tmp_path))
    assert (refused.status_code, refused.code) == (404, "local_folders_off")


@pytest.mark.parametrize(
    ("rel", "code"),
    [
        ("../outside", "local_path_outside"),
        ("results/escape", "local_path_outside"),
        ("depictio-local", "local_path_denied"),
        (".ssh", "local_path_hidden"),
        ("results/.snapshots", "local_path_hidden"),
        ("results/nope", "local_path_missing"),
        ("results/README.txt", "local_path_not_a_folder"),
    ],
)
def test_404_for_every_path_it_will_not_list(home, rel, code):
    refused = _refused(f"{home}/{rel}")
    assert (refused.status_code, refused.code) == (404, code)
    assert str(home / "outside") not in refused.detail


def test_404_for_a_relative_path(home):
    assert _refused("results").code == "local_path_not_absolute"


def test_403_for_a_non_admin(home):
    refused = _refused(str(home), user=_user(is_admin=False))
    assert (refused.status_code, refused.code) == (403, "local_admin_only")


@pytest.mark.parametrize("host", ["evil.example:8058", "depictio-backend:8058", "", None])
def test_403_for_a_host_that_is_not_this_machine(home, host):
    refused = _refused(str(home), host=host)
    assert (refused.status_code, refused.code) == (403, "non_loopback_host")


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("localhost", True),
        ("localhost:8058", True),
        ("LOCALHOST:8058", True),
        ("127.0.0.1:8058", True),
        ("127.1.2.3", True),
        ("[::1]:8058", True),
        ("::1", True),
        ("localhost.evil.example", False),
        ("127.0.0.1.nip.io:8058", False),
        ("10.0.0.5:8058", False),
        ("[::1", False),
        (None, False),
    ],
)
def test_is_loopback_host(host, loopback):
    assert local_dirs.is_loopback_host(host) is loopback


# ── the route ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_route_answers_a_refusal_with_detail_and_code(home):
    response = await routes.get_local_dirs(
        _request("evil.example"), path=str(home), current_user=_user()
    )
    assert response.status_code == 403
    body = json.loads(response.body)
    assert set(body) == {"detail", "code"}
    assert body["code"] == "non_loopback_host"


@pytest.mark.asyncio
async def test_the_route_lists(home):
    listing = await routes.get_local_dirs(_request(), path=str(home), current_user=_user())
    assert [e.name for e in listing.entries] == ["results"]


@pytest.mark.asyncio
async def test_the_route_needs_a_user():
    with pytest.raises(HTTPException) as exc:
        await routes.get_local_dirs(_request(), path=None, current_user=None)
    assert exc.value.status_code == 401


# ── the capability flag ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_me_optional_carries_the_flag_and_never_a_path(monkeypatch, home):
    from depictio.api.v1.endpoints.user_endpoints import routes as user_routes

    monkeypatch.setattr(user_routes.settings.auth, "single_user_mode", False)
    on = await user_routes.get_current_user_info_optional(token=None)
    assert on["local_data_roots_enabled"] is True
    assert str(home) not in json.dumps(on, default=str)
    assert os.path.realpath(home) not in json.dumps(on, default=str)

    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS")
    off = await user_routes.get_current_user_info_optional(token=None)
    assert off["local_data_roots_enabled"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("public", "credentialed", "enabled"),
    [
        ("", "", False),
        (" , ", "", False),
        ("open-data/runs", "", True),
        ("", "lab-data", True),
    ],
)
async def test_me_optional_says_whether_s3_can_be_browsed_never_which_bucket(
    monkeypatch, public, credentialed, enabled
):
    from depictio.api.v1.endpoints.user_endpoints import routes as user_routes

    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", public)
    monkeypatch.setenv("DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS", credentialed)
    body = await user_routes.get_current_user_info_optional(token=None)
    assert body["remote_browse_enabled"] is enabled
    for name in ("open-data", "lab-data"):
        assert name not in json.dumps(body, default=str)


def test_invalid_remote_settings_turn_browsing_off(monkeypatch):
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "open-data")
    monkeypatch.setenv("DEPICTIO_REMOTE_TIMEOUT_S", "not-a-number")
    assert settings_models.remote_browse_enabled() is False
