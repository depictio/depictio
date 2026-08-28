"""Scheduled MongoDB backups.

Off by default, because a snapshot is the size of the whole database and a
deployment that has not sized its backup volume should not start filling it on
upgrade. Admins turn it on from Admin > Backups; the environment only supplies
the default (see ``get_backup_schedule_config``).

Every API worker runs the loop; correctness lives in the MongoDB claim, not in
worker election. See ``claim_auto_backup_slot`` for why gating on the
initialization election would silently never fire.
"""

import asyncio

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.backup_endpoints.routes import (
    _create_mongodb_backup,
    _write_backup_file,
    claim_auto_backup_slot,
    get_backup_schedule_config,
    parse_time_of_day,
    prune_expired_backups,
)

#: Upper bound on how long a due backup waits for a worker to notice it. Polling
#: faster than the interval keeps a scheduled backup close to its due time even
#: though each worker's loop starts at an arbitrary phase, and bounds how long a
#: schedule change made in the UI takes to be picked up.
_MAX_POLL_SECONDS = 15 * 60
_MIN_POLL_SECONDS = 60


def _poll_seconds(interval_hours: int) -> int:
    return max(_MIN_POLL_SECONDS, min(interval_hours * 3600, _MAX_POLL_SECONDS))


async def run_scheduled_backup() -> str | None:
    """Take one scheduled backup if it is due. Returns the backup ID, or None."""
    config = get_backup_schedule_config()
    if not config["enabled"]:
        return None
    anchor_minutes = parse_time_of_day(config["time_of_day"])
    if claim_auto_backup_slot(config["interval_hours"] * 3600, anchor_minutes) is None:
        return None

    backup = await _create_mongodb_backup("scheduler", automatic=True)
    backup_id = backup["backup_metadata"]["backup_id"]
    filename = _write_backup_file(backup, backup_id)
    prune_expired_backups()

    logger.info(
        f"Scheduled backup created: {filename} "
        f"({backup['backup_metadata']['total_documents']} documents)"
    )
    return backup_id


async def periodic_backup() -> None:
    """Poll for a due scheduled backup forever.

    The loop runs even when the schedule is off, and re-reads the configuration
    on every tick: that is what lets an admin enable scheduled backups from the
    UI without restarting the API. An idle tick is one indexed MongoDB read.

    A failure never breaks the loop: the claim has already moved the due time
    forward, so a failed attempt costs one interval and the next tick retries.
    """
    logger.info("Scheduled backup loop started")

    while True:
        interval_hours = None
        try:
            config = get_backup_schedule_config()
            interval_hours = config["interval_hours"]
            if config["enabled"]:
                await run_scheduled_backup()
        except Exception as exc:
            logger.error(f"Scheduled backup failed: {exc}")
        await asyncio.sleep(_poll_seconds(interval_hours or 24))


def start_backup_tasks() -> None:
    """Start the scheduled-backup loop."""
    asyncio.create_task(periodic_backup())
