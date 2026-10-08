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

import pytest
from typer.testing import CliRunner

from depictio.cli.cli.commands import template as template_cmd
from depictio.cli.depictio_cli import app

runner = CliRunner()


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
            app,
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
