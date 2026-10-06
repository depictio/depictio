"""`depictio-cli run --result-json`, and the error when nothing names the project.

The result file is what `depictio local up` reads to open the dashboard a run
made, or the project a second run of the same directory found. Every server call
is mocked, so this runs offline.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from depictio.cli.cli.commands.run import register_run_command


@pytest.fixture
def app():
    application = typer.Typer()
    register_run_command(application)
    return application


@pytest.fixture
def data_root(tmp_path):
    root = tmp_path / "results"
    root.mkdir()
    return root


def _invoke(app, harness, data_root, *flags):
    patches = [
        *harness.patches(),
        patch(
            "depictio.cli.cli.commands.run._resolve_viewer_url",
            MagicMock(return_value="http://viewer"),
        ),
    ]
    for p in patches:
        p.start()
    try:
        return CliRunner().invoke(
            app,
            [
                "--template",
                "nf-core/ampliseq/2.16.0",
                "--data-root",
                str(data_root),
                "--skip-server-check",
                "--skip-s3-check",
                *flags,
            ],
        )
    finally:
        for p in patches:
            p.stop()


def test_a_successful_run_names_its_project_and_dashboards(app, data_root, tmp_path, make_harness):
    harness = make_harness(data_root, remote_locations=[])
    harness.remote_doc["_id"] = "p1"
    harness.resolve = MagicMock(
        return_value=(
            {"name": harness.project.name, "workflows": []},
            MagicMock(template_id="nf-core/ampliseq/2.16.0"),
            MagicMock(),
            [data_root / "dashboard.yaml"],
            {},
        )
    )
    harness.import_dashboards.return_value = [
        {"path": "dashboard.yaml", "success": True, "dashboard_id": "d1", "title": "Ampliseq"}
    ]
    result_file = tmp_path / "result.json"

    result = _invoke(app, harness, data_root, "--result-json", str(result_file))

    assert result.exit_code == 0, result.output
    assert json.loads(result_file.read_text()) == {
        "status": "success",
        "project": {"name": harness.project.name, "id": "p1", "url": "http://viewer/projects/p1"},
        "dashboards": [{"title": "Ampliseq", "id": "d1", "url": "http://viewer/dashboard/d1"}],
        "template_id": "nf-core/ampliseq/2.16.0",
    }


def test_an_existing_project_is_named_with_its_dashboards(app, data_root, tmp_path, make_harness):
    harness = make_harness(data_root, remote_locations=[str(data_root)])
    harness.remote_doc["_id"] = "p1"
    harness.sync = MagicMock(return_value={"action": "exists"})
    listing = MagicMock(status_code=200)
    listing.json.return_value = [
        {"dashboard_id": "d1", "title": "Ampliseq", "project_id": "p1"},
        {"dashboard_id": "d9", "title": "Someone else's", "project_id": "p9"},
    ]
    result_file = tmp_path / "result.json"

    with patch("httpx.get", MagicMock(return_value=listing)):
        result = _invoke(app, harness, data_root, "--result-json", str(result_file))

    assert result.exit_code == 2
    written = json.loads(result_file.read_text())
    assert written["status"] == "exists"
    assert written["project"]["id"] == "p1"
    assert written["project"]["locations"] == [str(data_root)]
    assert [d["id"] for d in written["dashboards"]] == ["d1"]
    harness.scan.assert_not_called()


def test_without_result_json_nothing_is_written_or_looked_up(app, data_root, make_harness):
    harness = make_harness(data_root, remote_locations=[str(data_root)])
    harness.sync = MagicMock(return_value={"action": "exists"})

    with patch("httpx.get") as http_get:
        result = _invoke(app, harness, data_root)

    assert result.exit_code == 2
    http_get.assert_not_called()


def test_a_directory_no_pipeline_claims_says_what_would_work(app, data_root):
    result = CliRunner().invoke(app, ["--data-root", str(data_root)])

    assert result.exit_code == 1
    output = " ".join(result.output.split())
    assert f"Could not tell which pipeline produced {data_root}" in output
    assert "Pass --template" in output
    assert "--project-config-path" in output
