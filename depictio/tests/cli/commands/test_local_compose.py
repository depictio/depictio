"""`depictio local export`, with the compose file download faked."""

import importlib.metadata
import urllib.error
from unittest.mock import MagicMock

import pytest

from depictio.cli.cli import local_compose, local_stack
from depictio.cli.cli.local_stack import LocalStackError, Paths
from depictio.cli.cli.utils import telemetry

COMPOSE = b"services: {}\n"


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path / "local")
    p.ensure_dirs()
    return p


@pytest.fixture
def source(tmp_path, monkeypatch):
    """A released wheel install: not a checkout, compose file downloaded (faked)."""
    site_packages = tmp_path / "site-packages"
    (site_packages / "depictio").mkdir(parents=True)
    fake = MagicMock()
    fake.download.return_value = COMPOSE
    fake.stop_all.return_value = ["api"]
    monkeypatch.setattr(local_compose, "package_root", lambda: site_packages / "depictio")
    monkeypatch.setattr(local_compose, "release_version", lambda: "9.8.7")
    monkeypatch.setattr(local_compose, "download", fake.download)
    monkeypatch.setattr(local_compose, "stop_all", fake.stop_all)
    monkeypatch.setattr(local_compose, "running_status", lambda _: {"mongo": False})
    fake.site_packages = site_packages
    return fake


def _fake_local_server(paths):
    """A stopped local server: data, keys, secrets and the conda-meta records."""
    (paths.home / "mongo" / "WiredTiger").write_text("wt")
    (paths.home / "s3" / "vol").mkdir(parents=True)
    (paths.home / "s3" / "mini.options").write_text(
        "ip=127.0.0.1\nip.bind=127.0.0.1\ns3.port=9123\nwebdav=false\n"
    )
    for name in local_compose.KEY_FILES:
        (paths.home / "keys" / name).write_text(name)
    meta = paths.env / "conda-meta"
    meta.mkdir(parents=True)
    for name, version in (("mongodb", "8.0.23"), ("seaweedfs", "4.46")):
        (meta / f"{name}-{version}-h0_0.json").write_text(
            f'{{"name": "{name}", "version": "{version}"}}'
        )
    local_stack.load_secrets(paths)


def _export(paths, out, log=None):
    local_compose.export_compose(paths, out, log=log or (lambda _: None))


def test_export_compose_copies_data_and_pins_the_local_versions(
    paths, tmp_path, monkeypatch, source
):
    _fake_local_server(paths)
    monkeypatch.setattr(local_compose.sys, "platform", "linux")
    out = tmp_path / "export"

    _export(paths, out)

    assert (out / "data" / "mongo" / "WiredTiger").read_text() == "wt"
    assert (out / "data" / "s3" / "vol").is_dir()
    options = (out / "data" / "s3" / "mini.options").read_text().splitlines()
    assert "ip.bind=0.0.0.0" in options and "s3.port=9000" in options
    assert "ip=127.0.0.1" in options and "ip.bind=127.0.0.1" not in options
    # The local server keeps its own options.
    assert "ip.bind=127.0.0.1" in (paths.home / "s3" / "mini.options").read_text()
    assert (out / "data" / "keys" / "private_key.pem").read_text() == "private_key.pem"
    override = (out / "docker-compose.override.yaml").read_text()
    assert "image: mongo:8.0.23" in override
    assert "image: chrislusf/seaweedfs:4.46" in override
    assert "./data/mongo:/data/db" in override
    assert f'user: "{local_compose.os.getuid()}:{local_compose.os.getgid()}"' in override
    env = (out / ".env").read_text()
    secrets = local_stack.load_secrets(paths)
    assert f"DEPICTIO_S3_ROOT_PASSWORD={secrets['s3_password']}" in env
    assert f"DEPICTIO_S3_ROOT_USER={local_stack.S3_USER}" in env
    assert "DEPICTIO_VERSION=9.8.7" in env.splitlines()
    assert oct((out / ".env").stat().st_mode & 0o777) == "0o600"
    # data/keys holds the token-signing key, copied with its mode.
    assert oct(out.stat().st_mode & 0o777) == "0o700"
    source.stop_all.assert_not_called()


def test_a_release_gets_the_compose_file_of_its_tag(paths, tmp_path, source):
    _fake_local_server(paths)
    out = tmp_path / "export"

    _export(paths, out)

    source.download.assert_called_once_with(
        "https://raw.githubusercontent.com/depictio/depictio/v9.8.7/docker-compose.yaml"
    )
    assert (out / "docker-compose.yaml").read_bytes() == COMPOSE


@pytest.mark.parametrize("version", [None, "9.8.7"], ids=["dev", "release"])
def test_a_checkout_uses_its_own_compose_file(paths, tmp_path, monkeypatch, source, version):
    # main carries the last release's number, whose tagged compose file may predate it.
    repo = tmp_path / "repo"
    (repo / "depictio").mkdir(parents=True)
    (repo / "docker-compose.yaml").write_text("services: {s3: {}}\n")
    monkeypatch.setattr(local_compose, "package_root", lambda: repo / "depictio")
    monkeypatch.setattr(local_compose, "release_version", lambda: version)
    _fake_local_server(paths)
    out = tmp_path / "export"

    _export(paths, out)

    assert (out / "docker-compose.yaml").read_text() == "services: {s3: {}}\n"
    source.download.assert_not_called()


def test_a_dev_build_outside_a_checkout_cannot_hand_over(paths, tmp_path, monkeypatch, source):
    monkeypatch.setattr(local_compose, "release_version", lambda: None)
    monkeypatch.setattr(local_compose, "running_status", lambda _: {"mongo": True})
    _fake_local_server(paths)
    out = tmp_path / "export"

    with pytest.raises(LocalStackError, match="released version .* or a source checkout"):
        _export(paths, out)

    # Nothing copied, and the server left running.
    assert not out.exists()
    source.stop_all.assert_not_called()


def test_a_running_server_is_stopped_then_exported(paths, tmp_path, monkeypatch, source):
    monkeypatch.setattr(local_compose, "running_status", lambda _: {"mongo": True})
    _fake_local_server(paths)
    out = tmp_path / "export"
    logged = []

    _export(paths, out, log=logged.append)

    source.stop_all.assert_called_once()
    assert len([line for line in logged if "Stopping" in line]) == 1
    assert (out / "data" / "mongo" / "WiredTiger").is_file()


def test_export_while_up_is_starting_fails_fast(paths, tmp_path, monkeypatch, source):
    monkeypatch.setattr(local_compose, "running_status", lambda _: {"mongo": True})
    _fake_local_server(paths)
    out = tmp_path / "export"
    held = local_stack.lock_for_startup(paths)
    try:
        with pytest.raises(LocalStackError, match="A `depictio local up` is starting this home"):
            _export(paths, out)
    finally:
        held.close()

    source.stop_all.assert_not_called()
    assert not out.exists()
    # Released: the export goes ahead, then releases the home for the next `up`.
    _export(paths, out)
    source.stop_all.assert_called_once()
    local_stack.lock_for_startup(paths).close()


def test_a_failed_download_names_the_url(monkeypatch):
    def urlopen(url, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(local_compose.urllib.request, "urlopen", urlopen)
    with pytest.raises(LocalStackError, match="Could not download https://x/y.yaml"):
        local_compose.download("https://x/y.yaml")


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        ({"depictio": "1.2.3", "depictio-cli": "1.2.3"}, "1.2.3"),
        ({"depictio-cli": "1.2.3"}, "1.2.3"),
        # A beta's package version, spelled as its tag and images are.
        ({"depictio": "1.2.3b1"}, "1.2.3-b1"),
        ({"depictio": "1.2.3.dev4"}, None),
        ({}, None),
    ],
)
def test_release_version_names_only_published_releases(monkeypatch, installed, expected):
    def version(dist):
        if dist not in installed:
            raise importlib.metadata.PackageNotFoundError(dist)
        return installed[dist]

    monkeypatch.setattr(telemetry, "_pkg_version", version)
    assert local_compose.release_version() == expected


def test_export_compose_runs_as_the_image_user_off_linux(paths, tmp_path, monkeypatch, source):
    _fake_local_server(paths)
    monkeypatch.setattr(local_compose.sys, "platform", "darwin")
    _export(paths, tmp_path / "export")
    assert "user:" not in (tmp_path / "export" / "docker-compose.override.yaml").read_text()


def test_export_compose_refuses_a_non_empty_directory(paths, tmp_path, source):
    _fake_local_server(paths)
    out = tmp_path / "export"
    out.mkdir()
    (out / "keep").write_text("x")
    with pytest.raises(LocalStackError, match="not empty"):
        _export(paths, out)


def test_an_out_that_is_a_file_is_refused_before_stopping_the_server(
    paths, tmp_path, monkeypatch, source
):
    monkeypatch.setattr(local_compose, "running_status", lambda _: {"mongo": True})
    _fake_local_server(paths)
    out = tmp_path / "export"
    out.write_text("x")

    with pytest.raises(LocalStackError, match="is a file"):
        _export(paths, out)
    source.stop_all.assert_not_called()


def test_an_unwritable_out_is_refused_before_stopping_the_server(
    paths, tmp_path, monkeypatch, source
):
    monkeypatch.setattr(local_compose, "running_status", lambda _: {"mongo": True})
    _fake_local_server(paths)
    parent = tmp_path / "ro"
    parent.mkdir()
    parent.chmod(0o555)
    try:
        with pytest.raises(LocalStackError, match="Cannot write to .*choose another --out"):
            _export(paths, parent / "sub")
    finally:
        parent.chmod(0o755)
    source.stop_all.assert_not_called()
