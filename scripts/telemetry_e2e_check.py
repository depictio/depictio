"""End-to-end check for anonymous installation telemetry.

Runs the *real* send path — the real payload builder against the real MongoDB, the
real gates, the real HTTP client — against a throwaway collector started in this
process, so an operator (or a maintainer touching the telemetry code) can prove the
pipeline works without sending anything to PostHog.

Why a loopback collector rather than mocks: the unit tests already patch
:func:`depictio.telemetry.posthog.capture` and therefore cannot catch a broken
endpoint, a payload the collector would reject, or a gate that silently suppresses
in a real deployment. This exercises everything up to and including the socket.

Usage, from inside the API container::

    python scripts/telemetry_e2e_check.py             # loopback collector, safe
    python scripts/telemetry_e2e_check.py --live      # really send to PostHog

``--live`` sends one ``server_install``/``server_heartbeat`` pair to the configured
collector and prints the distinct_id so the resulting events can be found — and
removed — in the PostHog UI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

# The gates suppress under pytest/dev-mode and without an explicit opt-in. This
# script *is* the deliberate opt-in, so clear the two dev-stack suppressions
# before any depictio module reads them at import time.
os.environ["DEPICTIO_TELEMETRY_ENABLED"] = "true"
os.environ["DEPICTIO_DEV_MODE"] = "false"
os.environ.pop("DO_NOT_TRACK", None)
os.environ.pop("PYTEST_CURRENT_TEST", None)
for _ci_var in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "GITLAB_CI"):
    os.environ.pop(_ci_var, None)

RECEIVED: list[dict[str, Any]] = []


class _CollectorHandler(BaseHTTPRequestHandler):
    """Accepts a PostHog-shaped capture and records it."""

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            RECEIVED.append(json.loads(raw))
        except json.JSONDecodeError:
            RECEIVED.append({"_unparseable": raw.decode("utf-8", "replace")})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"Ok"}')

    def log_message(self, *args: Any) -> None:
        """Silence the default stderr access log."""


def start_collector() -> tuple[HTTPServer, str]:
    """Start the throwaway collector on an ephemeral port."""
    server = HTTPServer(("127.0.0.1", 0), _CollectorHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/i/v0/e/"


def check(label: str, ok: bool, detail: str = "") -> bool:
    """Print one check line and pass the result through."""
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{f' — {detail}' if detail else ''}")
    return ok


#: Values that legitimately appear in a payload and so must not be treated as
#: leaks. Everything else configured on this deployment is fair game.
_ALLOWED_LEAK_VALUES: frozenset[str] = frozenset({"docker-compose", "kubernetes", "devcontainer"})

#: Settings sub-trees excluded from the leak scan, each for a specific reason —
#: not because they are inconvenient, but because a hit there could not be a leak.
_LEAK_SCAN_EXCLUDED_PREFIXES: tuple[tuple[str, str], ...] = (
    # Depictio's own project token and collector URL. Ours, and meant to travel.
    ("telemetry.", "the telemetry config is what we intend to send"),
    # MongoDB collection *names* — "dashboards", "projects", "workflows". Generic
    # schema vocabulary that is identical on every deployment and collides with the
    # payload's own field names, so a match here carries no information about the
    # operator. The connection details (host, credentials, db_name) are outside
    # this sub-tree and remain scanned.
    ("mongodb.collections.", "collection names are shared schema vocabulary"),
)


def _walk_settings(node: Any, path: str = "") -> list[tuple[str, str]]:
    """Yield every ``(dotted path, string value)`` in the settings tree."""
    from pydantic import BaseModel

    found: list[tuple[str, str]] = []
    if isinstance(node, BaseModel):
        for name in type(node).model_fields:
            try:
                found += _walk_settings(getattr(node, name), f"{path}.{name}" if path else name)
            except Exception:
                # A computed/validated property that raises is not a value that can
                # reach a payload either, so skipping it loses no coverage.
                continue
    elif isinstance(node, dict):
        for key, value in node.items():
            found += _walk_settings(value, f"{path}.{key}")
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            found += _walk_settings(value, f"{path}[{index}]")
    elif isinstance(node, str):
        found.append((path, node))
    return found


def forbidden_strings() -> list[tuple[str, str]]:
    """Every configured string on this deployment that must not reach a payload.

    Rather than hand-listing a few secrets — which goes stale the moment a config
    field is added — this walks the whole live settings tree. Any hostname, URL,
    bucket, password or key this deployment actually holds becomes an assertion, so
    a future payload field that reads the wrong setting fails here.
    """
    import platform

    from depictio.api.v1.configs.config import settings

    candidates: list[tuple[str, str]] = [("hostname", platform.node())]
    candidates += _walk_settings(settings)

    return [
        (label, value)
        for label, value in candidates
        # Short values collide with legitimate content ("v1", "0", "true"), so only
        # strings distinctive enough for a hit to mean something are checked.
        if value
        and len(value) >= 8
        and value not in _ALLOWED_LEAK_VALUES
        and not any(label.startswith(prefix) for prefix, _ in _LEAK_SCAN_EXCLUDED_PREFIXES)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Send to the real configured collector instead of a loopback one.",
    )
    args = parser.parse_args()

    failures = 0

    print("\n=== 1. Gates ===")
    from depictio.telemetry.gates import telemetry_allowed

    reason = telemetry_allowed(enabled=True, wipe=False)
    failures += not check("telemetry is not suppressed", reason is None, str(reason))

    from depictio.api.v1.telemetry.tasks import suppression_reason

    server_reason = suppression_reason()
    failures += not check("server send path is open", server_reason is None, str(server_reason))

    print("\n=== 2. Identity ===")
    from depictio.api.v1.telemetry.identity import get_or_create_instance_id

    instance_id, created_at = get_or_create_instance_id()
    failures += not check("instance id resolved", bool(instance_id), instance_id)
    again, _ = get_or_create_instance_id()
    failures += not check("instance id is stable across calls", again == instance_id)

    print("\n=== 3. Payload ===")
    from depictio.api.v1.telemetry.payload import build_heartbeat_properties

    _, properties = build_heartbeat_properties()
    payload = properties.model_dump(mode="json", exclude_none=True)
    print(json.dumps(payload, indent=2, sort_keys=True))

    serialised = json.dumps(payload).lower()
    secrets = forbidden_strings()
    leaked = [(label, value) for label, value in secrets if value.lower() in serialised]
    failures += not check(
        f"payload leaks none of the {len(secrets)} configured strings on this deployment",
        not leaked,
        "; ".join(f"{label}={value!r}" for label, value in leaked),
    )

    print("\n=== 4. Transport ===")
    from depictio.telemetry.constants import DEFAULT_API_KEY
    from depictio.telemetry.posthog import acapture
    from depictio.telemetry.schema import EVENT_HEARTBEAT, EVENT_INSTALL

    if args.live:
        from depictio.api.v1.configs.config import settings

        endpoint = settings.telemetry.endpoint
        api_key = settings.telemetry.api_key or DEFAULT_API_KEY
        print(f"  LIVE send to {endpoint}")
        print(f"  distinct_id = {instance_id}  (find/delete these events by this ID)")
    else:
        server, endpoint = start_collector()
        api_key = "phc_loopback_test_key"
        print(f"  loopback collector at {endpoint}")

    async def send_both() -> list[bool]:
        return [
            await acapture(event, instance_id, payload, api_key=api_key, endpoint=endpoint)
            for event in (EVENT_INSTALL, EVENT_HEARTBEAT)
        ]

    results = asyncio.run(send_both())
    failures += not check("server_install accepted", results[0])
    failures += not check("server_heartbeat accepted", results[1])

    if not args.live:
        server.shutdown()  # type: ignore[possibly-undefined]
        failures += not check(
            "collector received both events", len(RECEIVED) == 2, str(len(RECEIVED))
        )
        if RECEIVED:
            body = RECEIVED[0]
            failures += not check("body carries the api key", body.get("api_key") == api_key)
            failures += not check("body event name", body.get("event") == EVENT_INSTALL)
            failures += not check("body distinct_id", body.get("distinct_id") == instance_id)
            failures += not check(
                "person profiles suppressed",
                body.get("properties", {}).get("$process_person_profile") is False,
            )
            failures += not check("body carries a timestamp", bool(body.get("timestamp")))

    print("\n=== 5. CLI version reporting ===")
    # `cli_versions_seen` is the one payload field fed by an inbound *request
    # header* rather than by settings or a database count, which makes it the only
    # place attacker-controlled text can reach an outbound payload. Both ends are
    # unit tested; this exercises the recorder and the reader together, including
    # what happens when the header is hostile.
    from depictio.api.v1.telemetry.cli_versions import (
        CLI_VERSIONS_DOC_ID,
        record_cli_version,
    )
    from depictio.api.v1.telemetry.payload import recent_cli_versions

    from depictio.api.v1.db import telemetry_collection  # isort: skip

    versions_doc_existed = telemetry_collection.find_one({"_id": CLI_VERSIONS_DOC_ID}) is not None
    try:
        record_cli_version("9.9.9-e2echeck")
        failures += not check(
            "a plausible version reaches the payload",
            "9.9.9-e2echeck" in recent_cli_versions(),
            str(recent_cli_versions()),
        )

        hostile = [
            "1.0.0; DROP TABLE users",
            "../../etc/passwd",
            "alice@internal.example.org",
            "<script>alert(1)</script>",
            "x" * 500,
        ]
        for value in hostile:
            record_cli_version(value)
        reported = recent_cli_versions()
        failures += not check(
            "hostile version headers never reach the payload",
            all(value not in reported for value in hostile),
            str(reported),
        )
    finally:
        if not versions_doc_existed:
            telemetry_collection.delete_one({"_id": CLI_VERSIONS_DOC_ID})
        else:
            # Drop only the keys this check introduced, leaving real observations.
            telemetry_collection.update_one(
                {"_id": CLI_VERSIONS_DOC_ID},
                {"$unset": {"versions.9_9_9-e2echeck": ""}},
            )

    print("\n=== 6. CLI event ===")
    from depictio.cli.cli.utils.telemetry import build_properties

    cli_payload = build_properties("data process", succeeded=True, duration_seconds=3.2)
    print(json.dumps(cli_payload, indent=2, sort_keys=True))
    failures += not check("cli command path preserved", cli_payload["command"] == "data process")
    failures += not check("cli duration bucketed", cli_payload["duration_bucket"] == "1-10s")

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
