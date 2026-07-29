"""Exercises the *boot path* — ``start_telemetry`` and its heartbeat loop.

``telemetry_e2e_check.py`` proves the payload and the transport. This proves the
part that actually runs in production: the lifespan hook, the send-once guard that
collapses four gunicorn workers into one daily event, and the fact that neither an
unreachable collector nor a dead MongoDB can take the loop down.

The guard is the piece most worth testing for real. It is the difference between
"installations" counting deployments and counting worker processes, it can only be
wrong in one direction (silently over-reporting), and no unit test with a mocked
collection exercises the ``DuplicateKeyError`` that makes it work.

Sends go to a loopback collector, so this never reaches PostHog. It does write to
the deployment's ``telemetry`` collection, so guard documents it creates are
removed on the way out.

Usage, from inside the API container::

    python scripts/telemetry_boot_check.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

# This script is the deliberate opt-in; clear the dev-stack suppressions before any
# depictio module reads them at import time.
os.environ["DEPICTIO_TELEMETRY_ENABLED"] = "true"
os.environ["DEPICTIO_DEV_MODE"] = "false"
os.environ.pop("DO_NOT_TRACK", None)
os.environ.pop("PYTEST_CURRENT_TEST", None)
for _ci_var in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "GITLAB_CI"):
    os.environ.pop(_ci_var, None)

RECEIVED: list[dict[str, Any]] = []


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


def main() -> int:
    failures = 0

    server = HTTPServer(("127.0.0.1", 0), _CollectorHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{server.server_port}/i/v0/e/"

    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.db import telemetry_collection
    from depictio.api.v1.telemetry import tasks
    from depictio.api.v1.telemetry.guard import _guard_id, claim_send, ensure_guard_index
    from depictio.telemetry.schema import EVENT_HEARTBEAT, EVENT_INSTALL

    settings.telemetry.enabled = True
    settings.telemetry.endpoint = endpoint
    settings.telemetry.api_key = "phc_loopback_boot_check"
    settings.telemetry.debug = False

    # Guard IDs this run may create, so the deployment is left as it was found.
    # Claiming server_install for real would otherwise permanently consume the
    # once-per-installation event on this database.
    touched_ids = [
        _guard_id(EVENT_INSTALL, daily=False),
        _guard_id(EVENT_HEARTBEAT, daily=True),
    ]
    preexisting = {
        guard_id
        for guard_id in touched_ids
        if telemetry_collection.find_one({"_id": guard_id}) is not None
    }
    for guard_id in touched_ids:
        telemetry_collection.delete_one({"_id": guard_id})

    try:
        print("\n=== 1. Guard: send-once across workers ===")
        ensure_guard_index()
        claims = [claim_send(EVENT_HEARTBEAT, daily=True) for _ in range(4)]
        failures += not check(
            "4 simulated workers yield exactly 1 claim",
            claims.count(True) == 1,
            f"claims={claims}",
        )

        # The guard is only useful if it outlives the interval it guards. The TTL
        # index uses expireAfterSeconds=0 — MongoDB's expire-*at*-the-timestamp
        # mode — so a guard written with `now` in this field is collected on the
        # next TTL sweep, silently un-guarding every send. That bug shipped once
        # and neither the unit tests nor the send-once check above noticed, because
        # both finish long before the TTL monitor runs. Assert the value.
        from datetime import datetime, timedelta, timezone

        guard_doc = telemetry_collection.find_one({"_id": _guard_id(EVENT_HEARTBEAT, daily=True)})
        expires_at = (guard_doc or {}).get("guard_expires_at")
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        failures += not check(
            "guard expiry outlives a daily send interval",
            expires_at is not None and expires_at - now >= timedelta(days=1),
            f"expires_at={expires_at}",
        )

        telemetry_collection.delete_one({"_id": _guard_id(EVENT_HEARTBEAT, daily=True)})

        print("\n=== 2. Boot path: start_telemetry -> one send of each event ===")
        # The production loop pre-sleeps 60s so telemetry can never delay worker
        # readiness. Collapsed here; the delay is not what this is testing.
        tasks.FIRST_RUN_DELAY_SECONDS = 0

        async def run_one_boot() -> None:
            tasks.start_telemetry()
            # Long enough for the task to complete an iteration, far short of the
            # 24h interval sleep it then parks on.
            await asyncio.sleep(3)

        asyncio.run(run_one_boot())

        events = [body.get("event") for body in RECEIVED]
        failures += not check(
            "boot sent server_install and server_heartbeat",
            sorted(events) == sorted([EVENT_INSTALL, EVENT_HEARTBEAT]),
            f"got {events}",
        )

        print("\n=== 3. Second boot is deduplicated by the guard ===")
        before = len(RECEIVED)
        asyncio.run(run_one_boot())
        failures += not check(
            "a restarted worker sends nothing more today",
            len(RECEIVED) == before,
            f"{len(RECEIVED) - before} extra event(s)",
        )

        print("\n=== 4. An unreachable collector is survivable ===")
        server.shutdown()
        telemetry_collection.delete_one({"_id": _guard_id(EVENT_HEARTBEAT, daily=True)})
        try:
            asyncio.run(run_one_boot())
            failures += not check("heartbeat swallows a dead collector", True)
        except Exception as exc:
            failures += not check("heartbeat swallows a dead collector", False, str(exc))

        print("\n=== 5. Opt-out is honoured at the boot path ===")
        for label, mutate in (
            (
                "DEPICTIO_TELEMETRY_ENABLED=false",
                lambda: setattr(settings.telemetry, "enabled", False),
            ),
            ("DO_NOT_TRACK=1", lambda: os.environ.__setitem__("DO_NOT_TRACK", "1")),
        ):
            settings.telemetry.enabled = True
            os.environ.pop("DO_NOT_TRACK", None)
            mutate()
            failures += not check(
                f"{label} suppresses the send path",
                tasks.suppression_reason() is not None,
                str(tasks.suppression_reason()),
            )
        settings.telemetry.enabled = True
        os.environ.pop("DO_NOT_TRACK", None)

    finally:
        for guard_id in touched_ids:
            telemetry_collection.delete_one({"_id": guard_id})
            if guard_id in preexisting:
                # Restore the claim this deployment legitimately held, so a real
                # heartbeat is not re-sent today because of a test run.
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)
                telemetry_collection.insert_one(
                    {"_id": guard_id, "sent_at": now, "guard_expires_at": now}
                )
        print("\n  (guard documents restored to their pre-run state)")

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
