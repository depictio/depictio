"""Play an inbound migration request against a running local stack, to watch the live push.

The request is a real document in ``migration_requests``; each status change goes
through ``migration_import._set_request``, the code that announces it to admin
browsers. Open http://127.0.0.1:<port>/projects (or Admin > Migrations) first:

    pending   toast "A project needs a decision" + a yellow banner with Review
    imported  toast "A project was received"     + a banner with Details
    failed    toast "An import failed"           + a banner with Details and a cross

The stack only pushes when started with events on, and shows the Migrations
controls when migration is on:

    DEPICTIO_EVENTS_ENABLED=true DEPICTIO_MIGRATION_UI_ENABLED=true \\
      depictio local up --port 8143

Nothing here needs a second instance.

    uv run --extra dev python depictio/dev_scripts/demo_migration_event.py
    ... --steps pending,imported --pause 6 --keep
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def _local_env(port_mongo: int, port_redis: int) -> None:
    """The settings a script needs to reach the local stack's Mongo and Redis."""
    defaults = {
        "DEPICTIO_CONTEXT": "server",
        "DEPICTIO_AUTH_SINGLE_USER_MODE": "true",
        "DEPICTIO_MONGODB_SERVICE_NAME": "127.0.0.1",
        "DEPICTIO_MONGODB_SERVICE_PORT": str(port_mongo),
        "DEPICTIO_EVENTS_ENABLED": "true",
        "DEPICTIO_EVENTS_REDIS_HOST": "127.0.0.1",
        "DEPICTIO_EVENTS_REDIS_PORT": str(port_redis),
        # Required by the settings validator; the script never touches S3.
        "DEPICTIO_S3_ROOT_USER": "demo-user",
        "DEPICTIO_S3_ROOT_PASSWORD": "demo-secret-not-used-9f3k2l1x",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--mongo-port", type=int, default=27018)
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--project", default="Penguins from the lab", help="project name shown")
    parser.add_argument(
        "--source", default="https://dev.depictio.embl.org", help="sender shown in the banner"
    )
    parser.add_argument(
        "--steps",
        default="pending,imported",
        help="comma list of statuses to play: pending, importing, imported, failed",
    )
    parser.add_argument("--pause", type=float, default=6.0, help="seconds between steps")
    parser.add_argument("--keep", action="store_true", help="leave the request in place at the end")
    args = parser.parse_args()

    _local_env(args.mongo_port, args.redis_port)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from bson import ObjectId

    from depictio.api.v1.services import migration_import
    from depictio.models.models.migration import MigrationRequest

    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    allowed = {"pending", "importing", "imported", "failed"}
    if not steps or not set(steps) <= allowed:
        parser.error(f"--steps takes {sorted(allowed)}")

    collection = migration_import._db().migration_requests_collection
    request_id = ObjectId()
    request = MigrationRequest(
        source_name="demo",
        source_instance="demo",
        source_url=args.source,
        project_name=args.project,
        status="pending",
    )
    doc = request.model_dump(exclude={"id"})
    doc["_id"] = request_id
    # The row first, then the announcement the inbound route makes after its insert.
    collection.insert_one(doc)
    first, *rest = steps
    collection.update_one({"_id": request_id}, {"$set": {"status": first}})
    migration_import.announce_request(doc, first)
    print(f"{first:<10} request {request_id}")

    for status in rest:
        time.sleep(args.pause)
        migration_import._set_request(request_id, status=status)
        print(f"{status:<10} request {request_id}")

    if not args.keep:
        time.sleep(args.pause)
        collection.delete_one({"_id": request_id})
        print("removed    (use --keep to leave it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
