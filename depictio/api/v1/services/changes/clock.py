"""Ingestion records still stamp the host's local clock.

``ingestion_runs.started_at``, ``Aggregation.aggregation_time``,
``MultiQCReport.processed_at`` and a workflow run's ``registration_time`` come
from ``datetime.now()``, while every other API timestamp is naive UTC. Under Docker the two agree; under
``depictio local up`` they are hours apart, so a run would read as hours in
the future and sort after a later dashboard version. The changes views turn
them into naive UTC before showing or ordering them: they are written by the
API and its worker, which run on the host whose clock this is.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def local_to_utc(value: Any) -> Any:
    """A naive local-clock datetime (or ISO string) as naive UTC; anything else as is."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if not isinstance(value, datetime):
        return value
    # A naive datetime's astimezone() reads it as the host's local time.
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def utc_to_local(value: datetime) -> datetime:
    """The inverse, to query local-clock fields with a UTC cursor."""
    return value.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
