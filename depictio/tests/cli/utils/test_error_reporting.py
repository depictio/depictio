"""One report per failure without -v: the ✗ line carries the detail, the log stays quiet.

Without -v the CLI logger is at ERROR, so a failure logged at ERROR and also said in a
✗ line printed twice, and sometimes only the log line had the detail.
"""

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest
import typer

from depictio.cli.cli.utils import config as config_utils
from depictio.cli.cli.utils.api_calls import api_sync_project_config_to_server
from depictio.cli.cli_logging import multiqc_logging, setup_logging
from depictio.models.models.cli import CLIConfig

USER_ID = "507f1f77bcf86cd799439011"


@pytest.fixture
def cli_config() -> CLIConfig:
    return CLIConfig(  # type: ignore[call-arg]
        user={
            "email": "test@example.com",
            "is_admin": False,
            "id": USER_ID,
            "token": {
                "user_id": USER_ID,
                "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test",
                "refresh_token": "refresh-token-example",
                "token_type": "bearer",
                "token_lifetime": "short-lived",
                "expire_datetime": "2025-12-31T23:59:59",
                "refresh_expire_datetime": "2025-12-31T23:59:59",
                "name": "test_token",
                "created_at": "2025-06-30T18:00:00",
                "logged_in": False,
            },
        },
        api_base_url="https://api.depictio.dev",
        s3_storage={
            "service_name": "minio",
            "service_port": 9000,
            "external_host": "localhost",
            "external_port": 9000,
            "external_protocol": "http",
            "root_user": "minio",
            "root_password": "minio123",
            "bucket": "depictio-bucket",
        },
    )


@pytest.fixture(autouse=True)
def _cli_logger_restored():
    cli_logger = logging.getLogger("depictio-cli")
    handlers, level = cli_logger.handlers[:], cli_logger.level
    yield
    cli_logger.handlers[:] = handlers
    cli_logger.setLevel(level)


def _cli(capsys, verbose: bool = False):
    """The CLI's logging, set up in the test itself: setup_logging binds its handler to
    the stderr of the moment, and capsys replaces it between a fixture and the test."""
    setup_logging(verbose=verbose, verbose_level="INFO")
    return capsys


def _logged_in(cli_config: CLIConfig):
    return (
        patch.object(config_utils, "api_login", return_value={"success": True}),
        patch.object(config_utils, "load_depictio_config", return_value=cli_config),
    )


def test_an_invalid_project_file_names_each_problem_in_its_x_line(capsys, cli_config, tmp_path):
    quiet = _cli(capsys)
    project = tmp_path / "project.yaml"
    project.write_text("name: demo\ncolour: red\n")
    login, load = _logged_in(cli_config)

    with login, load, pytest.raises(typer.Exit) as exit_info:
        config_utils.validate_project_config_and_check_S3_storage(
            CLI_config_path="cli.yaml", project_config_path=str(project)
        )

    out, err = quiet.readouterr()
    assert exit_info.value.exit_code == 1
    assert "✗ Project configuration validation failed" in out
    assert str(project) in out
    assert "colour: Extra inputs are not permitted" in out
    # pydantic's input dump and documentation link stay out of the line.
    assert "input_value" not in out and "errors.pydantic.dev" not in out
    assert err == ""


def test_an_invalid_template_project_is_one_x_line(capsys, cli_config):
    quiet = _cli(capsys)
    login, load = _logged_in(cli_config)

    with login, load, pytest.raises(typer.Exit):
        config_utils.validate_template_project_config(
            CLI_config_path="cli.yaml",
            resolved_config={"name": "demo", "workflows": [{"name": "wf", "bogus": 1}]},
        )

    out, err = quiet.readouterr()
    assert out.count("✗") == 1
    assert "workflows.0." in out
    assert err == ""


def test_a_project_the_server_refuses_is_one_x_line_with_its_reason(capsys, cli_config):
    quiet = _cli(capsys)
    not_found = httpx.Response(404, json={"detail": "not found"})
    refused = httpx.Response(
        200, json={"success": False, "message": "Duplicate workflow_tag(s) [python/wf]"}
    )
    with (
        patch("depictio.cli.cli.utils.api_calls.api_get_project_from_name", return_value=not_found),
        patch("depictio.cli.cli.utils.api_calls.api_create_project", return_value=refused),
        pytest.raises(typer.Exit),
    ):
        api_sync_project_config_to_server(
            CLI_config=cli_config, ProjectConfig={"name": "demo"}, update=False
        )

    out, err = quiet.readouterr()
    assert out.count("✗") == 1
    # Escaped: Rich would read the bracketed span as markup and drop it.
    assert "Failed to create project on server: Duplicate workflow_tag(s) [python/wf]" in out
    assert err == ""


class TestMultiQCLogging:
    """MultiQC's own lines only at -v, and no second copy of the CLI's records."""

    @pytest.fixture(autouse=True)
    def _multiqc(self):
        pytest.importorskip("multiqc")

    @staticmethod
    def _run_multiqc() -> None:
        # What multiqc.parse_logs does first: its handler on the root logger, then its logs.
        from multiqc.core.log_and_rich import init_log

        init_log()
        logging.getLogger("multiqc.core.file_search").info("Search path: /data/multiqc.parquet")

    def test_its_info_lines_are_quiet_without_v(self, capsys):
        quiet = _cli(capsys)
        with multiqc_logging():
            self._run_multiqc()

        assert "Search path" not in quiet.readouterr().err

    def test_its_info_lines_show_with_v(self, capsys):
        verbose = _cli(capsys, verbose=True)
        with multiqc_logging():
            self._run_multiqc()

        assert "Search path: /data/multiqc.parquet" in verbose.readouterr().err

    def test_the_root_logger_is_put_back(self, capsys):
        quiet = _cli(capsys)
        root = logging.getLogger()
        handlers, level = root.handlers[:], root.level

        with multiqc_logging():
            self._run_multiqc()
        logging.getLogger("depictio-cli").error("one failure")

        assert root.handlers == handlers and root.level == level
        assert quiet.readouterr().err.count("one failure") == 1


def test_an_unreadable_multiqc_report_is_one_x_line_naming_it(capsys, monkeypatch):
    quiet = _cli(capsys)
    from depictio.cli.cli.utils import multiqc_processor as mp

    monkeypatch.delenv("DEPICTIO_INGEST_MULTIQC_PARSE_WORKERS", raising=False)
    monkeypatch.setattr(
        mp, "_parse_multiqc_worker", MagicMock(side_effect=ValueError("corrupt [report]"))
    )

    mp._parse_multiqc_files(["run1/multiqc.parquet"])

    out, err = quiet.readouterr()
    assert out.count("✗") == 1
    assert "Could not read MultiQC report run1/multiqc.parquet: corrupt [report]" in out
    assert err == ""


class TestApiLoginStatus:
    """api_login says which HTTP status the server answered: the token is not always why."""

    URL = "https://api.depictio.dev/depictio/api/v1/cli/validate_cli_config"

    @pytest.fixture
    def login(self, cli_config):
        from depictio.cli.cli.utils import api_calls

        def _login(response: httpx.Response) -> tuple[dict, list[str]]:
            client = MagicMock()
            client.post.return_value = response
            with (
                patch.object(api_calls, "load_depictio_config", return_value=cli_config),
                patch.object(api_calls, "get_http_client", return_value=client),
                patch.object(api_calls, "rich_print_checked_statement") as printer,
            ):
                result = api_calls.api_login("cli.yaml")
            return result, [str(call.args[0]) for call in printer.call_args_list]

        return _login

    def test_a_valid_token(self, login):
        result, _ = login(httpx.Response(200, json={"success": True, "is_admin": True}))

        assert result["success"] is True
        assert result["status_code"] == 200
        assert result["is_admin"] is True

    def test_a_token_the_server_does_not_know(self, login):
        result, _ = login(httpx.Response(200, json={"success": False, "message": "expired"}))

        assert result == {"success": False, "status_code": 200}

    @pytest.mark.parametrize("status", [401, 403])
    def test_a_refused_token(self, login, status):
        result, printed = login(httpx.Response(status, json={"detail": "Invalid token"}))

        assert result == {"success": False, "status_code": status}
        assert printed[-1].startswith("Depictio CLI configuration is invalid: ")

    @pytest.mark.parametrize("status", [404, 502])
    def test_another_answer_names_its_status_not_the_configuration(self, login, status):
        page = "<html><body>nginx error page</body></html>"
        result, printed = login(httpx.Response(status, text=page))

        assert result == {"success": False, "status_code": status}
        assert printed[-1] == f"The server answered HTTP {status} to {self.URL}"
        assert not any("nginx error page" in line for line in printed)
