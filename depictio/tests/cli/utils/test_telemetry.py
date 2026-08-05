"""Tests for CLI telemetry, above all the command-path allowlist.

A CLI's argv is full of things that must never leave the machine: file paths,
project names, S3 URIs, occasionally a token pasted into the wrong flag. Rather
than sanitise, ``resolve_command_path`` reconstructs the command from the CLI's
own registered command tree and discards everything else. These tests are the
proof, so they lean heavily on hostile input.
"""

from unittest.mock import patch

import pytest

from depictio.cli.cli.utils.telemetry import (
    UNKNOWN_COMMAND,
    build_properties,
    cli_version,
    resolve_command_path,
    suppression_reason,
)


@pytest.fixture(scope="module")
def root_command():
    """The real Click command tree, so the allowlist is tested against reality."""
    from depictio.cli.depictio_cli import depictiocli

    return depictiocli


@pytest.fixture
def allow_telemetry(monkeypatch):
    """Lift the gates that make telemetry a no-op inside a test run.

    Running under pytest is itself a hard suppression, so anything exercising
    behaviour that only happens while telemetry is *on* has to say so explicitly.
    """
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.delenv("DEPICTIO_TELEMETRY_ENABLED", raising=False)
    with (
        patch("depictio.telemetry.gates.detect_pytest", return_value=False),
        patch("depictio.telemetry.gates.detect_ci", return_value=False),
    ):
        yield


class TestResolveCommandPathHappyCases:
    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["version"], "version"),
            (["commands"], "commands"),
            (["run"], "run"),
            (["data", "scan"], "data scan"),
            (["data", "process"], "data process"),
            (["dashboard", "import"], "dashboard import"),
            (["dashboard", "export"], "dashboard export"),
            (["backup", "create"], "backup create"),
            (["config", "show"], "config show"),
            (["dev", "catalog", "validate"], "dev catalog validate"),
        ],
    )
    def test_registered_commands_resolve(self, argv, expected, root_command):
        assert resolve_command_path(argv, root_command) == expected

    def test_global_options_are_skipped(self, root_command):
        assert resolve_command_path(["--verbose", "data", "scan"], root_command) == "data scan"

    def test_bare_invocation(self, root_command):
        assert resolve_command_path([], root_command) == UNKNOWN_COMMAND

    def test_group_without_subcommand_still_resolves(self, root_command):
        assert resolve_command_path(["data"], root_command) == "data"


class TestResolveCommandPathRejectsUserData:
    """Nothing a user typed may survive into the command path."""

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            # Option values — the most common carrier of paths and secrets.
            (["data", "process", "--project-config", "/home/alice/cohort.yaml"], "data process"),
            (["data", "process", "--token", "eyJhbGciOiJIUzI1NiJ9.SECRET"], "data process"),
            (["config", "show", "--CLI-config-path", "~/.depictio/CLI.yaml"], "config show"),
            # Positional arguments.
            (["data", "process", "/absolute/PATIENT_DATA.csv"], "data process"),
            (["dashboard", "export", "s3://private-bucket/key"], "dashboard export"),
            # Unrecognised tokens end the walk rather than being passed through.
            (["definitely-not-a-command"], UNKNOWN_COMMAND),
            (["data", "not-a-subcommand"], "data"),
            (["data", "scan", "extra", "junk"], "data scan"),
            # Injection-flavoured input.
            (["../../etc/passwd"], UNKNOWN_COMMAND),
            (["data", "$(curl evil.example)"], "data"),
            (["data", "scan; rm -rf /"], "data"),
        ],
    )
    def test_only_registered_names_survive(self, argv, expected, root_command):
        assert resolve_command_path(argv, root_command) == expected

    def test_result_is_always_command_names_only(self, root_command):
        """Whatever the input, every token in the output is a real command name."""
        hostile = [
            ["data", "process", "--project-config", "/etc/shadow"],
            ["dashboard", "import", "my-secret-project"],
            ["backup", "restore", "s3://bucket/backup.tgz", "--force"],
            ["\x00\x01binary"],
            ["--verbose", "--verbose-level", "SECRET"],
        ]
        for argv in hostile:
            resolved = resolve_command_path(argv, root_command)
            if resolved == UNKNOWN_COMMAND:
                continue
            for token in resolved.split(" "):
                assert token in argv, f"{token!r} was not even in argv"
                assert not token.startswith("-")
                assert "/" not in token


class TestCommandEventPayload:
    def test_payload_carries_no_argv_content(self, root_command):
        argv = [
            "data",
            "process",
            "--project-config",
            "/home/alice/SECRET.yaml",
            "--token",
            "hunter2",
        ]
        command = resolve_command_path(argv, root_command)
        payload = build_properties(command, succeeded=True, duration_seconds=3.2)

        blob = repr(payload).lower()
        for forbidden in ("alice", "secret", "hunter2", ".yaml", "/", "token"):
            assert forbidden not in blob

    def test_payload_keys_are_an_exact_allowlist(self):
        """Tripwire: extending the payload has to be a deliberate change here."""
        payload = build_properties("data scan", succeeded=True, duration_seconds=0.5)
        assert set(payload) == {
            "depictio_version",
            "deployment_kind",
            "os",
            "arch",
            "python_version",
            "command",
            "succeeded",
            "duration_bucket",
            "is_ci",
            "id_ephemeral",
        }

    def test_duration_is_bucketed_not_exact(self):
        payload = build_properties("data scan", succeeded=True, duration_seconds=42.7)
        assert payload["duration_bucket"] == "10-60s"
        assert "42" not in repr(payload)

    def test_failure_is_recorded(self):
        payload = build_properties("data scan", succeeded=False, duration_seconds=1.0)
        assert payload["succeeded"] is False


class TestCliSuppression:
    def test_do_not_track_suppresses(self, monkeypatch):
        monkeypatch.setenv("DO_NOT_TRACK", "1")
        monkeypatch.setenv("DEPICTIO_TELEMETRY_API_KEY", "phc_test")
        assert suppression_reason() == "do_not_track_env"

    def test_explicit_disable_suppresses(self, monkeypatch):
        monkeypatch.delenv("DO_NOT_TRACK", raising=False)
        monkeypatch.setenv("DEPICTIO_TELEMETRY_ENABLED", "false")
        monkeypatch.setenv("DEPICTIO_TELEMETRY_API_KEY", "phc_test")
        assert suppression_reason() == "disabled_by_config"

    def test_missing_api_key_suppresses(self, monkeypatch):
        """A build with no collector token at all must stay silent.

        The shipped default is non-empty, so this blanks it to exercise the
        fork-or-source-build case.
        """
        monkeypatch.delenv("DO_NOT_TRACK", raising=False)
        monkeypatch.delenv("DEPICTIO_TELEMETRY_ENABLED", raising=False)
        monkeypatch.delenv("DEPICTIO_TELEMETRY_API_KEY", raising=False)
        with (
            patch("depictio.cli.cli.utils.telemetry._DEFAULT_API_KEY", ""),
            patch("depictio.telemetry.gates.detect_pytest", return_value=False),
            patch("depictio.telemetry.gates.detect_ci", return_value=False),
        ):
            assert suppression_reason() == "no_api_key_configured"

    def test_shipped_default_routes_to_the_project(self, monkeypatch):
        """With no env overrides the CLI must reach Depictio's own collector.

        Guards the whole point of baking the token in: an empty default would
        leave every installed CLI permanently silent, and nothing else would say so.
        """
        from depictio.cli.cli.utils import telemetry as cli_telemetry
        from depictio.telemetry.constants import DEFAULT_API_KEY, DEFAULT_ENDPOINT

        assert cli_telemetry._DEFAULT_API_KEY == DEFAULT_API_KEY
        assert DEFAULT_API_KEY.startswith("phc_")
        assert DEFAULT_ENDPOINT.startswith("https://eu.i.posthog.com")

        monkeypatch.delenv("DO_NOT_TRACK", raising=False)
        monkeypatch.delenv("DEPICTIO_TELEMETRY_ENABLED", raising=False)
        monkeypatch.delenv("DEPICTIO_TELEMETRY_API_KEY", raising=False)
        with (
            patch("depictio.telemetry.gates.detect_pytest", return_value=False),
            patch("depictio.telemetry.gates.detect_ci", return_value=False),
        ):
            assert suppression_reason() is None

    def test_send_is_a_no_op_when_suppressed(self, monkeypatch):
        monkeypatch.setenv("DO_NOT_TRACK", "1")
        from depictio.cli.cli.utils import telemetry as cli_telemetry

        with patch("depictio.telemetry.posthog.capture") as mock_capture:
            cli_telemetry.send_command_event("data scan", succeeded=True, duration_seconds=1.0)
        mock_capture.assert_not_called()

    def test_send_never_raises_even_if_everything_breaks(self, monkeypatch):
        """A broken collector must not fail the user's command."""
        monkeypatch.delenv("DO_NOT_TRACK", raising=False)
        from depictio.cli.cli.utils import telemetry as cli_telemetry

        with patch.object(cli_telemetry, "suppression_reason", side_effect=RuntimeError("boom")):
            cli_telemetry.send_command_event("data scan", succeeded=True, duration_seconds=1.0)


class TestFirstRunNotice:
    """Telemetry on by default has to announce itself to the person it counts."""

    @staticmethod
    def _notice(*, tty: bool, capsys, monkeypatch, tmp_path) -> str:
        from depictio.cli.cli.utils import telemetry as cli_telemetry

        monkeypatch.setenv("DEPICTIO_TELEMETRY_STATE_DIR", str(tmp_path))
        with patch("sys.stderr.isatty", return_value=tty):
            cli_telemetry.maybe_print_first_run_notice()
        return capsys.readouterr().err

    def test_shown_once_on_the_run_that_creates_the_id(
        self, capsys, monkeypatch, tmp_path, allow_telemetry
    ):
        first = self._notice(tty=True, capsys=capsys, monkeypatch=monkeypatch, tmp_path=tmp_path)
        assert "DEPICTIO_TELEMETRY_ENABLED=false" in first
        assert "DO_NOT_TRACK=1" in first

        second = self._notice(tty=True, capsys=capsys, monkeypatch=monkeypatch, tmp_path=tmp_path)
        assert second == "", "an opt-out notice that repeats is one users learn to ignore"

    def test_silent_when_telemetry_is_suppressed(self, capsys, monkeypatch, tmp_path):
        """Nothing is being collected, so there is nothing to disclose."""
        monkeypatch.setenv("DO_NOT_TRACK", "1")
        assert (
            self._notice(tty=True, capsys=capsys, monkeypatch=monkeypatch, tmp_path=tmp_path) == ""
        )

    def test_silent_when_stderr_is_not_a_terminal(
        self, capsys, monkeypatch, tmp_path, allow_telemetry
    ):
        """Scripts, CI logs and redirected output stay clean."""
        assert (
            self._notice(tty=False, capsys=capsys, monkeypatch=monkeypatch, tmp_path=tmp_path) == ""
        )

    def test_never_raises(self, capsys, monkeypatch, tmp_path, allow_telemetry):
        """A disclosure must not be able to break the command it precedes."""
        from depictio.cli.cli.utils import telemetry as cli_telemetry

        with patch.object(
            cli_telemetry, "get_or_create_anonymous_id", side_effect=RuntimeError("boom")
        ):
            self._notice(tty=True, capsys=capsys, monkeypatch=monkeypatch, tmp_path=tmp_path)


class TestCliVersion:
    def test_returns_a_string(self):
        assert isinstance(cli_version(), str)
        assert cli_version()

    def test_falls_back_to_dev_when_not_installed(self):
        from importlib.metadata import PackageNotFoundError

        with patch(
            "depictio.cli.cli.utils.telemetry._pkg_version",
            side_effect=PackageNotFoundError,
        ):
            assert cli_version() == "dev"


class TestVersionHeader:
    def test_generate_api_headers_includes_the_cli_version(self):
        """Rides along on requests the user already makes, so the server can report
        which CLI versions are live without the CLI opening a connection."""
        from depictio.cli.cli.utils.common import generate_api_headers

        headers = generate_api_headers(
            {
                "user": {"token": {"access_token": "tok"}},
                "instance_label": "lab-workstation",
            }
        )
        assert headers["X-Depictio-CLI-Version"] == cli_version()
        assert headers["X-Depictio-CLI-Instance"] == "lab-workstation"
        assert headers["Authorization"] == "Bearer tok"
