"""Exercises the CLI telemetry path through the real ``main()`` entry point.

Calls the same function the ``depictio-cli`` console script does, with a real argv
and a loopback collector, so what is asserted is the shipped behaviour rather than
a unit test's view of it.

The point of interest is the argument scrubbing. :func:`resolve_command_path`
reconstructs the command from the CLI's own Click tree instead of sanitising argv,
and the claim that makes is strong: *no string that is not already a command name
in Depictio's source can be emitted*. That is worth testing adversarially, so this
runs commands with credentials, paths and S3 URIs in the arguments and asserts none
of it reaches the collector.

Usage::

    python scripts/telemetry_cli_check.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

os.environ["DEPICTIO_TELEMETRY_ENABLED"] = "true"
os.environ["DEPICTIO_DEV_MODE"] = "false"
os.environ.pop("DO_NOT_TRACK", None)
os.environ.pop("PYTEST_CURRENT_TEST", None)
for _ci_var in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "GITLAB_CI"):
    os.environ.pop(_ci_var, None)

# A throwaway state directory, so the run neither reads nor writes the developer's
# real ``~/.depictio/telemetry.json``. Without this the script mutates the machine
# it is run on, and the once-per-machine events (``cli_install``) fire on the first
# run and never again, which makes the checks below pass or fail depending on
# whether anyone has run the script here before.
os.environ["DEPICTIO_TELEMETRY_STATE_DIR"] = tempfile.mkdtemp(prefix="depictio-cli-check-")

RECEIVED: list[dict[str, Any]] = []

#: Strings planted in argv that must never reach the collector. Each stands for a
#: category the docs promise is never sent: a path, a credential, an S3 URI, a
#: project name, a hostname.
CANARIES: tuple[str, ...] = (
    "/home/alice/cohort-secret.yaml",
    "hunter2SuperSecretToken",
    "s3://private-bucket-name/prefix",
    "AliceConfidentialProject",
    "internal.institute.example.org",
)


class _CollectorHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", 0))
        RECEIVED.append(json.loads(self.rfile.read(length)))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"Ok"}')

    def log_message(self, *args: Any) -> None:
        """Silence the default stderr access log."""


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{f' — {detail}' if detail else ''}")
    return ok


def run_cli(argv: list[str]) -> None:
    """Invoke the CLI's real ``main()`` with ``argv``, absorbing its exit.

    The CLI's own help/error output is discarded so the check results stay legible;
    what matters here is what reached the collector, not what reached the terminal.
    """
    import contextlib
    import io

    from depictio.cli.depictio_cli import main

    original_argv = sys.argv
    sys.argv = ["depictio-cli", *argv]
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            main()
    except SystemExit:
        # Typer exits this way for --help and for usage errors alike. Both are
        # ordinary CLI outcomes and both must still report.
        pass
    except BaseException as exc:
        print(f"    (command raised {type(exc).__name__}: {exc})")
    finally:
        sys.argv = original_argv


def main() -> int:
    failures = 0

    server = HTTPServer(("127.0.0.1", 0), _CollectorHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["DEPICTIO_TELEMETRY_ENDPOINT"] = f"http://127.0.0.1:{server.server_port}/i/v0/e/"
    os.environ["DEPICTIO_TELEMETRY_API_KEY"] = "phc_cli_loopback"

    from depictio.cli.cli.utils.telemetry import suppression_reason

    print("\n=== 1. Gate ===")
    reason = suppression_reason()
    failures += not check("CLI send path is open", reason is None, str(reason))

    print("\n=== 2. Invocations (argv carries canaries) ===")
    invocations: list[tuple[str, list[str], str]] = [
        ("bare --help", ["--help"], "<none>"),
        ("nested command", ["config", "show", "--help"], "config show"),
        (
            "command with a secret path",
            ["config", "show", "--CLI-config-path", CANARIES[0]],
            "config show",
        ),
        (
            "command with a token and an S3 URI",
            ["data", "process", "--token", CANARIES[1], "--s3", CANARIES[2]],
            "data process",
        ),
        (
            "unknown command with a project name",
            ["notacommand", CANARIES[3], "--host", CANARIES[4]],
            "<none>",
        ),
        # A *misspelled* sub-command under a real group. The walk must stop at the
        # group rather than pass the unrecognised token through — this is the
        # behaviour that keeps a typo'd argument from becoming an event property.
        ("misspelled sub-command", ["config", "shwo-nonsense", CANARIES[3]], "config"),
    ]

    for index, (label, argv, expected_command) in enumerate(invocations):
        before = len(RECEIVED)
        run_cli(argv)
        sent = RECEIVED[before:]
        # The very first invocation on a fresh state directory also reports the
        # one-off `cli_install`. Counted separately below rather than tolerated
        # here, so "one command, one command event" stays an exact assertion.
        commands = [event for event in sent if event.get("event") == "cli_command"]
        installs = [event for event in sent if event.get("event") == "cli_install"]

        expected_installs = 1 if index == 0 else 0
        failures += not check(
            f"{label}: emitted {expected_installs} install event(s)",
            len(installs) == expected_installs,
            f"got {len(installs)}",
        )
        if not check(
            f"{label}: emitted exactly one command event", len(commands) == 1, f"got {len(commands)}"
        ):
            failures += 1
            continue
        actual = commands[0].get("properties", {}).get("command")
        failures += not check(
            f"{label}: command == {expected_command!r}", actual == expected_command, repr(actual)
        )

    print("\n=== 3. Nothing from argv reached the collector ===")
    everything = json.dumps(RECEIVED)
    for canary in CANARIES:
        failures += not check(f"never sent {canary!r}", canary not in everything)
    # Also assert on fragments, so a partially-emitted value cannot slip past a
    # whole-string check.
    for fragment in ("alice", "hunter2", "private-bucket", "institute.example"):
        failures += not check(
            f"never sent fragment {fragment!r}", fragment not in everything.lower()
        )

    print("\n=== 4. Event shape ===")
    if RECEIVED:
        body = RECEIVED[-1]
        props = body.get("properties", {})
        failures += not check("event name", body.get("event") == "cli_command")
        failures += not check("has an anonymous distinct_id", bool(body.get("distinct_id")))
        failures += not check(
            "person profiles suppressed", props.get("$process_person_profile") is False
        )
        failures += not check("reports non-CI", props.get("is_ci") is False)
        print(json.dumps(props, indent=2, sort_keys=True))

    print("\n=== 5. Opt-out is honoured ===")
    for label, var in (
        ("DEPICTIO_TELEMETRY_ENABLED=false", "DEPICTIO_TELEMETRY_ENABLED"),
        ("DO_NOT_TRACK=1", "DO_NOT_TRACK"),
    ):
        os.environ["DEPICTIO_TELEMETRY_ENABLED"] = "true"
        os.environ.pop("DO_NOT_TRACK", None)
        os.environ[var] = "false" if var.startswith("DEPICTIO") else "1"
        before = len(RECEIVED)
        run_cli(["--help"])
        failures += not check(
            f"{label} sends nothing", len(RECEIVED) == before, f"{len(RECEIVED) - before} sent"
        )
    os.environ["DEPICTIO_TELEMETRY_ENABLED"] = "true"
    os.environ.pop("DO_NOT_TRACK", None)

    server.shutdown()
    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
