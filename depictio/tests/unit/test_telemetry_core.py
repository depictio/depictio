"""Tests for the shared telemetry core: bucketing, gates, env detection, state.

The privacy guarantees these cover are not incidental — they are the reason
telemetry can ship enabled by default. Treat a failure here as a release blocker,
not a flaky test.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from depictio.telemetry.buckets import LABELS, OVERFLOW_LABEL, bucket, bucket_seconds
from depictio.telemetry.env import (
    VALID_DEPLOYMENT_KINDS,
    detect_ci,
    detect_deployment_kind,
    platform_info,
)
from depictio.telemetry.gates import SuppressionReason, do_not_track, telemetry_allowed
from depictio.telemetry.k8s_resources import parse_cpu_millicores, parse_memory_mib
from depictio.telemetry.posthog import build_body, render_for_debug
from depictio.telemetry.state import (
    STATE_DIR_ENV,
    first_run_notice_shown,
    get_or_create_anonymous_id,
    mark_first_run_notice_shown,
    state_dir,
)


class TestBuckets:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0, "0"),
            (1, "1"),
            (2, "2-5"),
            (5, "2-5"),
            (6, "6-10"),
            (10, "6-10"),
            (11, "11-50"),
            (50, "11-50"),
            (51, "51-200"),
            (200, "51-200"),
            (201, OVERFLOW_LABEL),
            (10_000_000, OVERFLOW_LABEL),
        ],
    )
    def test_boundaries(self, value, expected):
        assert bucket(value) == expected

    def test_none_is_not_zero(self):
        """A failed count must stay distinguishable from a real zero.

        Conflating them would turn a broken query into a plausible data point.
        """
        assert bucket(None) == "unknown"
        assert bucket(None) != bucket(0)

    def test_negative_is_unknown(self):
        assert bucket(-1) == "unknown"

    def test_every_label_is_declared(self):
        """``LABELS`` must cover everything ``bucket`` can return."""
        produced = {bucket(n) for n in range(0, 500)}
        assert produced <= set(LABELS)

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0.0, "<1s"),
            (0.999, "<1s"),
            (1, "1-10s"),
            (9.9, "1-10s"),
            (10, "10-60s"),
            (59.9, "10-60s"),
            (60, "1-10m"),
            (599, "1-10m"),
            (600, "10m+"),
            (None, "unknown"),
        ],
    )
    def test_duration_buckets(self, seconds, expected):
        assert bucket_seconds(seconds) == expected


class TestGates:
    """Each kill switch must actually suppress, and report why."""

    def test_disabled_by_config(self, monkeypatch):
        monkeypatch.delenv("DO_NOT_TRACK", raising=False)
        assert telemetry_allowed(enabled=False) is SuppressionReason.DISABLED

    def test_do_not_track_wins_over_enabled(self, monkeypatch):
        monkeypatch.setenv("DO_NOT_TRACK", "1")
        assert telemetry_allowed(enabled=True) is SuppressionReason.DO_NOT_TRACK

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "anything"])
    def test_do_not_track_accepts_any_meaningful_value(self, monkeypatch, value):
        """Someone who sets this variable at all means it."""
        monkeypatch.setenv("DO_NOT_TRACK", value)
        assert do_not_track() is True

    @pytest.mark.parametrize("value", ["0", "false", "", "  "])
    def test_do_not_track_off_values(self, monkeypatch, value):
        monkeypatch.setenv("DO_NOT_TRACK", value)
        assert do_not_track() is False

    def test_ci_is_suppressed(self, monkeypatch):
        """CI must not be counted.

        Depictio's own workflows boot the API constantly and users run the CLI on
        every commit; counting that would swamp real installations.
        """
        monkeypatch.delenv("DO_NOT_TRACK", raising=False)
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        with patch("depictio.telemetry.gates.detect_pytest", return_value=False):
            assert telemetry_allowed(enabled=True) is SuppressionReason.CI

    def test_wipe_is_suppressed(self, monkeypatch):
        monkeypatch.delenv("DO_NOT_TRACK", raising=False)
        with (
            patch("depictio.telemetry.gates.detect_pytest", return_value=False),
            patch("depictio.telemetry.gates.detect_ci", return_value=False),
        ):
            assert telemetry_allowed(enabled=True, wipe=True) is SuppressionReason.WIPE

    def test_allowed_when_nothing_objects(self, monkeypatch):
        monkeypatch.delenv("DO_NOT_TRACK", raising=False)
        with (
            patch("depictio.telemetry.gates.detect_pytest", return_value=False),
            patch("depictio.telemetry.gates.detect_ci", return_value=False),
        ):
            assert telemetry_allowed(enabled=True) is None

    def test_running_under_pytest_is_suppressed(self):
        """Sanity check on the real environment: this very test run must be suppressed."""
        assert telemetry_allowed(enabled=True) is not None


class TestEnvDetection:
    def test_explicit_override_wins(self, monkeypatch):
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
        monkeypatch.setenv("DEPICTIO_TELEMETRY_DEPLOYMENT_KIND", "docker-compose")
        assert detect_deployment_kind() == "docker-compose"

    def test_every_valid_kind_round_trips(self, monkeypatch):
        """``VALID_DEPLOYMENT_KINDS`` must match the branches in the detector."""
        for kind in VALID_DEPLOYMENT_KINDS:
            monkeypatch.setenv("DEPICTIO_TELEMETRY_DEPLOYMENT_KIND", kind)
            assert detect_deployment_kind() == kind

    def test_unknown_override_falls_through_to_detection(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_TELEMETRY_DEPLOYMENT_KIND", "not-a-kind")
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
        assert detect_deployment_kind() == "kubernetes"

    def test_kubernetes_detected_from_injected_var(self, monkeypatch):
        monkeypatch.delenv("DEPICTIO_TELEMETRY_DEPLOYMENT_KIND", raising=False)
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
        assert detect_deployment_kind() == "kubernetes"

    def test_ci_detection(self, monkeypatch):
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setenv("CIRCLECI", "true")
        assert detect_ci() is True

    def test_platform_info_never_includes_the_hostname(self):
        """The hostname is personal-ish data and must never be in a payload."""
        import platform as platform_module

        info = platform_info()
        assert set(info) == {"os", "arch", "python_version"}
        node = platform_module.node()
        if node:
            assert node not in info.values()


class TestK8sResourceParsing:
    """The one place in the pipeline that touches an operator-typed string."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("500m", 500),
            ("100m", 100),
            ("0.5", 500),
            ("1", 1000),
            ("2", 2000),
            ("0.25", 250),
            (" 500m ", 500),
        ],
    )
    def test_cpu_parses_equivalent_notations(self, raw, expected):
        assert parse_cpu_millicores(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "not-a-quantity", "500x", "-1", "-100m"])
    def test_cpu_degrades_to_none_rather_than_raising(self, raw):
        assert parse_cpu_millicores(raw) is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1Gi", 1024),
            ("512Mi", 512),
            ("4Gi", 4096),
            ("1024Mi", 1024),
            ("2048Ki", 2),
            ("1048576", 1),  # bytes, no suffix
        ],
    )
    def test_memory_parses_binary_notations(self, raw, expected):
        assert parse_memory_mib(raw) == expected

    def test_memory_decimal_suffix_differs_from_binary(self):
        """1G (decimal) is less than 1Gi (binary) - the whole reason both exist."""
        assert parse_memory_mib("1G") < parse_memory_mib("1Gi")

    @pytest.mark.parametrize("raw", [None, "", "not-a-quantity", "1Xi", "-1Gi"])
    def test_memory_degrades_to_none_rather_than_raising(self, raw):
        assert parse_memory_mib(raw) is None


class TestState:
    def test_id_is_stable_across_calls(self, tmp_path, monkeypatch):
        """A rotating ID would make each invocation look like a new install."""
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path))
        first = get_or_create_anonymous_id()
        second = get_or_create_anonymous_id()
        assert first.value == second.value
        assert first.ephemeral is False

    def test_state_dir_override_is_honoured(self, tmp_path, monkeypatch):
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path / "custom"))
        assert state_dir() == tmp_path / "custom"

    def test_xdg_state_home_is_honoured(self, tmp_path, monkeypatch):
        monkeypatch.delenv(STATE_DIR_ENV, raising=False)
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        assert state_dir() == tmp_path / "depictio"

    def test_corrupt_file_is_regenerated_not_fatal(self, tmp_path, monkeypatch):
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path))
        path = tmp_path / "telemetry.json"
        path.write_text("{not json at all", encoding="utf-8")

        result = get_or_create_anonymous_id()
        assert result.value
        assert json.loads(path.read_text(encoding="utf-8"))["anonymous_id"] == result.value

    def test_unwritable_location_degrades_to_ephemeral(self, tmp_path, monkeypatch):
        """A read-only home must never fail the user's command.

        Flagged ephemeral so the collector can discount these rather than counting
        every invocation as a fresh installation.
        """
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path / "nested"))
        with patch("depictio.telemetry.state._write_state", return_value=False):
            result = get_or_create_anonymous_id()
        assert result.value
        assert result.ephemeral is True

    def test_write_is_atomic_and_leaves_no_debris(self, tmp_path, monkeypatch):
        """Concurrent CLIs must never observe a half-written file."""
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path))
        get_or_create_anonymous_id()
        leftovers = [p.name for p in Path(tmp_path).iterdir() if p.name.startswith(".telemetry-")]
        assert leftovers == []

    def test_directory_is_created_privately(self, tmp_path, monkeypatch):
        target = tmp_path / "statedir"
        monkeypatch.setenv(STATE_DIR_ENV, str(target))
        get_or_create_anonymous_id()
        if os.name == "posix":
            assert (target.stat().st_mode & 0o077) == 0

    def test_the_notice_flag_survives_writing_the_id(self, tmp_path, monkeypatch):
        """Both live in one file, written at different moments by different paths.

        A whole-file write of either key would drop the other: the ID would erase a
        notice already shown, or the notice would erase the ID and every later run
        would look like a fresh installation.
        """
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path))
        mark_first_run_notice_shown()
        anon = get_or_create_anonymous_id()

        assert first_run_notice_shown() is True
        assert get_or_create_anonymous_id().value == anon.value

    def test_the_notice_flag_is_not_set_by_creating_the_id(self, tmp_path, monkeypatch):
        """The disclosure is owed to whoever has not seen it, not to the machine.

        A first invocation from a script mints the ID while showing nothing, and
        the user must still be told the first time they run the CLI themselves.
        """
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path))
        get_or_create_anonymous_id()
        assert first_run_notice_shown() is False

    def test_an_unreadable_state_dir_claims_the_notice_was_shown(self, tmp_path, monkeypatch):
        """Failing towards silence: a notice repeated every run gets muted."""
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path))
        with patch("depictio.telemetry.state._read_state", side_effect=OSError("nope")):
            assert first_run_notice_shown() is True


class TestPostHogBody:
    def test_body_shape_matches_the_capture_api(self):
        body = build_body("some_event", "abc123", {"k": 1}, api_key="phc_test")
        assert body["api_key"] == "phc_test"
        assert body["event"] == "some_event"
        assert body["distinct_id"] == "abc123"
        assert body["properties"]["k"] == 1
        assert body["timestamp"].endswith("+00:00")

    def test_every_event_is_marked_anonymous(self):
        """Without this the collector creates a person profile per installation.

        That would contradict what docs/telemetry.md promises operators, and
        identified events cost up to 4x more than anonymous ones. Asserted on the
        shared builder, so no sender can omit it.
        """
        body = build_body("server_heartbeat", "inst", {}, api_key="phc_test")
        assert body["properties"]["$process_person_profile"] is False

    def test_caller_properties_cannot_override_the_anonymity_flag(self):
        body = build_body(
            "server_heartbeat",
            "inst",
            {"$process_person_profile": True},
            api_key="phc_test",
        )
        assert body["properties"]["$process_person_profile"] is False

    def test_debug_render_redacts_the_key(self):
        """The debug log is meant to be pasted into an issue; it must not leak the key."""
        rendered = render_for_debug(build_body("e", "d", {}, api_key="phc_super_secret"))
        assert "phc_super_secret" not in rendered
        assert "<redacted>" in rendered


class TestCaptureIdentifiesItself:
    """Every send must carry a User-Agent that is not httpx's default.

    PostHog classifies ``python-httpx/x.y.z`` as bot traffic. Every event Depictio
    sent before this was flagged ``Automation``, which hides it from any query
    that filters bots out — data that is ingested but invisible is
    indistinguishable from data that never arrived.
    """

    def _sent_headers(self, sender):
        client = MagicMock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        client.post.return_value = Mock(status_code=200)

        with patch("depictio.telemetry.posthog.httpx.Client", return_value=client):
            sender()
        return client.post.call_args.kwargs["headers"]

    def test_capture_sets_an_explicit_user_agent(self):
        from depictio.telemetry.posthog import capture

        headers = self._sent_headers(lambda: capture("e", "d", {}, api_key="phc_test"))
        assert "httpx" not in headers["User-Agent"].lower()
        assert "depictio" in headers["User-Agent"].lower()

    def test_the_async_sender_agrees_with_the_sync_one(self):
        """The server uses acapture; a header on only one path fixes only one channel."""
        from depictio.telemetry.posthog import _headers

        assert _headers()["User-Agent"] == "depictio-telemetry"


class TestDocsStayInSyncWithTheSchema:
    def test_generated_docs_are_committed_and_current(self):
        """``docs/telemetry.md`` must match the schema it documents.

        A privacy page that has drifted from the code it describes is worse than no
        page at all, so this is enforced rather than trusted.
        """
        import subprocess
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        script = repo_root / "scripts" / "gen_telemetry_docs.py"
        assert script.exists(), "the docs generator is missing"

        result = subprocess.run(
            [sys.executable, str(script), "--check"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"docs/telemetry.md is stale. Regenerate with "
            f"`python scripts/gen_telemetry_docs.py`.\n{result.stdout}{result.stderr}"
        )
