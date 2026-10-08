"""Tests for `depictio template export`'s bundle unpacking.

The server builds the archive; the CLI only unpacks it. What matters here is
that a hostile bundle (zip-slip: a member such as ``../evil.yaml``) is refused
before anything is written, and that a well-formed one lands under
``<output_dir>/<template_id>/``.
"""

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from depictio.cli.cli.commands import template as template_cmd

runner = CliRunner()


@pytest.fixture(autouse=True)
def _cli_context(monkeypatch):
    """Keep the CLI's process-wide context flip out of the other tests.

    Importing ``depictio.cli.depictio_cli`` sets ``DEPICTIO_CONTEXT=CLI`` on
    the process, and ``depictio.models.config`` caches whatever the context
    is at its first import (CLI context makes data-location validators
    check that directories exist). Import the models config first so its
    cache holds the session default, then scope the CLI value to this test:
    the app is imported lazily by the helpers below, and monkeypatch puts
    the variable back afterwards.
    """
    import depictio.models.config  # noqa: F401

    monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")


def _cli_app():
    from depictio.cli.depictio_cli import app

    return app


def _zip_bytes(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class _FakeClient:
    """Stands in for httpx.Client: any POST returns the canned bundle."""

    def __init__(self, content: bytes):
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers=None, json=None):
        return SimpleNamespace(content=self._content, raise_for_status=lambda: None)


def _export(output_dir: Path, bundle: bytes):
    with (
        patch(
            "depictio.cli.cli.utils.common.load_depictio_config",
            return_value=SimpleNamespace(api_base_url="http://api.test"),
        ),
        patch("depictio.cli.cli.utils.common.generate_api_headers", return_value={}),
        patch.object(template_cmd.httpx, "Client", return_value=_FakeClient(bundle)),
    ):
        return runner.invoke(
            _cli_app(),
            [
                "template",
                "export",
                "6824cb3b89d2b72169309737",
                "--template-id",
                "lab/tool/1",
                "--config",
                "cfg.yaml",
                "-o",
                str(output_dir),
                "--api",
                "http://api.test",
            ],
        )


def test_well_formed_bundle_unpacks_under_template_id(tmp_path):
    bundle = _zip_bytes({"template.yaml": "name: x\n", "dashboards/base.yaml": "title: t\n"})

    result = _export(tmp_path, bundle)

    assert result.exit_code == 0, result.output
    target = tmp_path / "lab" / "tool" / "1"
    assert (target / "template.yaml").read_text() == "name: x\n"
    assert (target / "dashboards" / "base.yaml").read_text() == "title: t\n"


@pytest.mark.parametrize(
    "hostile", ["../evil.yaml", "/etc/evil.yaml", "dashboards/../../evil.yaml"]
)
def test_zip_slip_member_is_refused_and_nothing_written(tmp_path, hostile):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    bundle = _zip_bytes({"template.yaml": "name: x\n", hostile: "boom\n"})

    result = _export(output_dir, bundle)

    assert result.exit_code == 1
    assert "outside" in result.output
    # Members are validated before anything is created: neither the escaped
    # member nor the rest of the bundle landed anywhere.
    assert list(output_dir.iterdir()) == []
    assert not (tmp_path / "evil.yaml").exists()
    assert not Path("/etc/evil.yaml").exists()


def test_members_within_accepts_nested_and_rejects_escapes(tmp_path):
    ok = zipfile.ZipFile(io.BytesIO(_zip_bytes({"a/b/c.yaml": "x"})))
    assert template_cmd._members_within(ok, tmp_path / "t") == ["a/b/c.yaml"]

    for name in ("a/../../c.yaml", "/abs.yaml", "C:\\win.yaml", "..\\up.yaml"):
        bad = zipfile.ZipFile(io.BytesIO(_zip_bytes({name: "x"})))
        with pytest.raises(ValueError, match="outside"):
            template_cmd._members_within(bad, tmp_path / "t")


def test_corrupt_bundle_is_reported_not_traced(tmp_path):
    result = _export(tmp_path, b"not a zip")

    assert result.exit_code == 1
    assert "not a valid zip" in result.output
    assert list(tmp_path.iterdir()) == []


# ── Request shape and failure paths ─────────────────────────────────────────

PROJECT_ID = "6824cb3b89d2b72169309737"
BASE_ARGS = ["-t", "lab/tool/1", "-c", "cfg.yaml"]


class _RecordingClient(_FakeClient):
    """httpx.Client stand-in that records the POST it receives.

    ``error`` shapes the failure: an ``httpx.RequestError`` is raised by the
    call itself (transport failure), any other exception is raised by
    ``raise_for_status()`` on the returned response (HTTP error status).
    """

    def __init__(self, content: bytes = b"", error: Exception | None = None):
        super().__init__(content)
        self.error = error
        self.calls: list[dict] = []

    def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if isinstance(self.error, httpx.RequestError):
            raise self.error

        def _raise_for_status():
            if self.error is not None:
                raise self.error

        return SimpleNamespace(content=self._content, raise_for_status=_raise_for_status)


def _http_error(status: int, text: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://api.test/export")
    response = httpx.Response(status, text=text, request=request)
    return httpx.HTTPStatusError("status error", request=request, response=response)


def _invoke(args: list[str], client, config_error: Exception | None = None):
    """Run ``template export`` with the CLI config and HTTP client stubbed.

    The stubbed config reports ``api_base_url=http://from-config:9999`` so a
    test can tell whether the command used ``--api`` or fell back to it.
    """
    with (
        patch(
            "depictio.cli.cli.utils.common.load_depictio_config",
            return_value=SimpleNamespace(api_base_url="http://from-config:9999"),
            side_effect=config_error,
        ),
        patch(
            "depictio.cli.cli.utils.common.generate_api_headers",
            return_value={"Authorization": "Bearer t0k"},
        ),
        patch.object(template_cmd.httpx, "Client", return_value=client),
    ):
        return runner.invoke(_cli_app(), ["template", "export", PROJECT_ID, *args])


def test_request_carries_every_option_to_the_export_endpoint(tmp_path):
    client = _RecordingClient(_zip_bytes({"template.yaml": "name: x\n"}))

    result = _invoke(
        [
            *BASE_ARGS,
            "-o",
            str(tmp_path),
            "--api",
            "http://api.test",
            "--version",
            "2.1.0",
            "--description",
            "Exported for review",
            "--data-root",
            "/data/run42",
        ],
        client,
    )

    assert result.exit_code == 0, result.output
    # An explicit --api wins over the CLI config's api_base_url.
    assert client.calls == [
        {
            "url": f"http://api.test/depictio/api/v1/projects/{PROJECT_ID}/export_template",
            "headers": {"Authorization": "Bearer t0k"},
            "json": {
                "template_id": "lab/tool/1",
                "version": "2.1.0",
                "description": "Exported for review",
                "data_root": "/data/run42",
            },
        }
    ]


def test_optional_fields_default_to_none_and_version_to_1_0_0(tmp_path):
    client = _RecordingClient(_zip_bytes({"template.yaml": "name: x\n"}))

    result = _invoke([*BASE_ARGS, "-o", str(tmp_path), "--api", "http://api.test"], client)

    assert result.exit_code == 0, result.output
    assert client.calls[0]["json"] == {
        "template_id": "lab/tool/1",
        "version": "1.0.0",
        "description": None,
        "data_root": None,
    }


def test_api_url_falls_back_to_the_cli_config(tmp_path):
    """Without --api the command targets the API the CLI config was made for."""
    client = _RecordingClient(_zip_bytes({"template.yaml": "name: x\n"}))

    result = _invoke([*BASE_ARGS, "-o", str(tmp_path)], client)

    assert result.exit_code == 0, result.output
    assert client.calls[0]["url"] == (
        f"http://from-config:9999/depictio/api/v1/projects/{PROJECT_ID}/export_template"
    )


def test_config_error_exits_with_a_hint_before_any_request(tmp_path):
    client = _RecordingClient()

    result = _invoke(
        [*BASE_ARGS, "-o", str(tmp_path)], client, config_error=FileNotFoundError("cfg.yaml")
    )

    assert result.exit_code == 1
    assert "Error loading CLI config" in result.output
    assert "depictio config" in result.output
    assert client.calls == []
    assert list(tmp_path.iterdir()) == []


def test_http_error_reports_status_and_server_detail(tmp_path):
    client = _RecordingClient(
        error=_http_error(422, '{"detail":"template_id must be slash-separated"}')
    )

    result = _invoke([*BASE_ARGS, "-o", str(tmp_path)], client)

    assert result.exit_code == 1
    assert "HTTP 422" in result.output
    assert "slash-separated" in result.output
    assert list(tmp_path.iterdir()) == []


def test_transport_error_is_reported_not_traced(tmp_path):
    client = _RecordingClient(error=httpx.ConnectError("connection refused"))

    result = _invoke([*BASE_ARGS, "-o", str(tmp_path)], client)

    assert result.exit_code == 1
    assert "connection refused" in result.output
    assert list(tmp_path.iterdir()) == []


def test_success_lists_the_unpacked_members(tmp_path):
    client = _RecordingClient(
        _zip_bytes({"template.yaml": "name: x\n", "dashboards/base.yaml": "title: t\n"})
    )

    result = _invoke([*BASE_ARGS, "-o", str(tmp_path)], client)

    assert result.exit_code == 0, result.output
    assert "Template bundle written to" in result.output
    assert "template.yaml" in result.output
    assert "dashboards/base.yaml" in result.output
    assert (tmp_path / "lab" / "tool" / "1" / "dashboards" / "base.yaml").exists()
