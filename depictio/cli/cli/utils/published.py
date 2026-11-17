"""Refuse to ingest into a project published read-only on the server (#1303).

The server answers 409 on every write to a published project, but the CLI
uploads data to S3 before it registers it: without this check an ingestion
would push files and then fail half-way. A project that does not exist yet
cannot be published, so only an existing one is looked up.
"""

from __future__ import annotations

from typing import Any

from depictio.cli.cli.utils.api_calls import api_get_project_from_name


def published_lock_of(project_name: str, CLI_config: Any) -> dict | None:
    """The server's ``published_lock`` for ``project_name``, or None."""
    try:
        response = api_get_project_from_name(project_name, CLI_config)
    except Exception:
        return None
    if getattr(response, "status_code", None) != 200:
        return None
    try:
        lock = (response.json() or {}).get("published_lock")
    except ValueError:
        return None
    return lock if isinstance(lock, dict) else None


def published_lock_message(project_name: str, lock: dict) -> str:
    reason = f" ({lock['reason']})" if lock.get("reason") else ""
    return (
        f"Project '{project_name}' is published read-only on this server{reason}. "
        "Nothing was ingested. An administrator must unlock it first, or publish "
        "the change as a new release."
    )
