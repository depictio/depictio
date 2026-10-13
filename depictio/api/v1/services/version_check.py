"""Release check: tell admins when a newer Depictio version exists.

The API asks the GitHub Releases API of ``settings.version_check.repository``
every ``interval_hours`` and keeps the answer in a singleton document
(``_id: "version_check"``) in ``instance_settings``, next to the branding one.
Only admins are shown the result (``/utils/server-info``, ``/utils/version-check``);
the request itself carries nothing about the installation.

Who decides whether it runs
---------------------------
Three layers, highest first:

1. ``DEPICTIO_VERSION_CHECK_ENABLED`` when set. The operator's word is final and
   the admin toggle is locked (``locked_by_env``): someone who forbids outbound
   calls must not have that undone from a web form.
2. The admin's choice, stored as ``enabled_override`` in the document above.
3. On.

Why every worker runs the loop
------------------------------
Same reasoning as ``telemetry/guard.py``: gunicorn runs several workers and
Kubernetes may add replicas, and gating on the initialization election would mean
only a deployment's very first boot ever checks. So each process runs
:func:`periodic_version_check`, and an atomic claim on ``next_check_at`` (see
:func:`_claim`) lets exactly one of them hit GitHub per interval. That matters
beyond politeness: unauthenticated GitHub calls are limited to 60 an hour per IP,
and every pod of a deployment usually shares one.

Reads go through a short TTL cache so ``/utils/server-info``, which the SPA calls
on page load, never adds a Mongo round-trip per request. Writes invalidate it
in-process only, so other workers catch up within the TTL (5 s); the admin panel's
own view (:func:`admin_view`) skips the cache so a PUT or "Check now" is never
shown reverted. A failed read is not cached: an outage must not pin ``{}``, which
:func:`is_enabled` would read as "no override, on", over an admin's "off".
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Final

import httpx
from pymongo.errors import DuplicateKeyError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.branding import get_instance_settings_collection
from depictio.models.timestamps import utc_now_naive
from depictio.version import get_version

_DOC_ID: Final[str] = "version_check"

#: Delay before a worker's first iteration, for the reason given in
#: ``telemetry/tasks.py``: startup work must never cost a worker its health check.
FIRST_RUN_DELAY_SECONDS: Final[int] = 60

#: How often each worker re-evaluates. Much shorter than the check interval on
#: purpose: an admin switching the check on from /admin takes effect within a tick
#: instead of needing a restart, and the claim keeps the real cadence at
#: ``interval_hours``.
TICK_SECONDS: Final[int] = 15 * 60

_GITHUB_API: Final[str] = "https://api.github.com"
_RELEASES_PAGE_SIZE: Final[int] = 30

_CACHE_TTL_SECONDS: Final[float] = 5.0
_cache: tuple[float, dict[str, Any]] | None = None


# ── Version parsing ───────────────────────────────────────────────────────────

# `.bumpversion.cfg` produces `X.Y.Z` and `X.Y.Z-bN`; tags carry a `v` prefix.
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-b(\d+))?$")


def parse_version(value: str | None) -> tuple[int, int, int, int, int] | None:
    """Sortable key for ``X.Y.Z`` / ``X.Y.Z-bN`` (optionally ``v``-prefixed).

    A beta sorts below the release it precedes: ``1.15.1-b3 < 1.15.1``. The fourth
    element is 0 for a beta and 1 for a final release, which is what makes that
    hold, and the fifth is the beta number. ``None`` for anything else; a tag
    that does not look like ours is ignored rather than guessed at.
    """
    if not value:
        return None
    match = _VERSION_RE.match(value.strip())
    if not match:
        return None
    major, minor, patch, beta = match.groups()
    if beta is None:
        return (int(major), int(minor), int(patch), 1, 0)
    return (int(major), int(minor), int(patch), 0, int(beta))


def is_newer(candidate: str | None, current: str | None) -> bool:
    """True when both parse and ``candidate`` is strictly newer than ``current``."""
    cand, cur = parse_version(candidate), parse_version(current)
    return cand is not None and cur is not None and cand > cur


def _is_beta(version: str | None) -> bool:
    parsed = parse_version(version)
    return parsed is not None and parsed[3] == 0


# ── Stored state ──────────────────────────────────────────────────────────────


def invalidate_version_check_cache() -> None:
    global _cache
    _cache = None


def _read_state(*, cached: bool = True) -> dict[str, Any]:
    """The stored document, or ``{}`` when absent or MongoDB is unreachable.

    Only a successful read is cached. A failed one returns ``{}`` uncached so the
    next call retries and a transient outage never sticks for a whole TTL window.
    """
    global _cache
    now = time.monotonic()
    if cached and _cache and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    try:
        state = get_instance_settings_collection().find_one({"_id": _DOC_ID}) or {}
    except Exception as exc:
        logger.debug(f"Version check: state unavailable: {exc}")
        return {}
    _cache = (now, state)
    return state


def _override(state: dict[str, Any] | None = None) -> bool | None:
    value = (_read_state() if state is None else state).get("enabled_override")
    return value if isinstance(value, bool) else None


def locked_by_env() -> bool:
    """True when the operator forced the check on or off through the environment."""
    return settings.version_check.enabled is not None


def is_enabled(state: dict[str, Any] | None = None) -> bool:
    """Effective on/off: env if set, else the admin's choice, else on.

    ``state`` is a document the caller already read, so one view stays consistent.
    """
    env_value = settings.version_check.enabled
    if env_value is not None:
        return env_value
    override = _override(state)
    return True if override is None else override


def set_override(enabled: bool | None) -> None:
    """Store (or, with ``None``, clear) the admin's on/off choice.

    Callers must refuse when :func:`locked_by_env` is true; this does not.
    """
    update: dict[str, Any] = (
        {"$set": {"enabled_override": enabled}}
        if enabled is not None
        else {"$unset": {"enabled_override": ""}}
    )
    get_instance_settings_collection().update_one({"_id": _DOC_ID}, update, upsert=True)
    invalidate_version_check_cache()


# ── Fetching ──────────────────────────────────────────────────────────────────


def _naive_utc(value: datetime) -> datetime:
    """``value`` as naive UTC, like every other timestamp the API stores."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_github_date(value: str | None) -> datetime | None:
    """GitHub's ``2026-01-02T03:04:05Z`` as a naive UTC datetime."""
    if not value:
        return None
    try:
        return _naive_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _release_record(release: dict[str, Any]) -> dict[str, Any] | None:
    tag = release.get("tag_name")
    if not isinstance(tag, str) or parse_version(tag) is None:
        return None
    return {
        "version": tag.strip().removeprefix("v"),
        "tag": tag,
        "url": release.get("html_url"),
        "published_at": _parse_github_date(release.get("published_at")),
        "name": release.get("name") or tag,
    }


def _short_error(exc: Exception) -> str:
    """A one-line reason safe to show an admin. No URLs, no response bodies."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (403, 429):
            return f"GitHub rate limit or access denied (HTTP {status})"
        return f"GitHub returned HTTP {status}"
    if isinstance(exc, httpx.TimeoutException):
        return "Timed out reaching GitHub"
    if isinstance(exc, httpx.RequestError):
        return "Could not reach GitHub"
    return f"Unexpected response from GitHub ({type(exc).__name__})"


async def _fetch_latest_release(current: str) -> dict[str, Any] | None:
    """The newest release for the channel ``current`` is on.

    A stable install follows ``/releases/latest``, which GitHub already restricts
    to published, non-prerelease releases. A beta install has to look at the list
    instead, since the newest thing for it may well be a later beta; drafts are
    skipped and the highest parsable version wins (the list is ordered by
    creation date, which a backported release can break).

    Raises on network, HTTP and JSON errors; the caller turns those into
    ``last_error``. Returns ``None`` when GitHub answered but nothing parsable.
    """
    cfg = settings.version_check
    base = f"{_GITHUB_API}/repos/{cfg.repository}/releases"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"depictio/{current}",
    }
    async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
        if _is_beta(current):
            response = await client.get(
                base, params={"per_page": _RELEASES_PAGE_SIZE}, headers=headers
            )
            response.raise_for_status()
            candidates = [
                record
                for release in response.json()
                if isinstance(release, dict) and not release.get("draft")
                if (record := _release_record(release)) is not None
            ]
            return max(candidates, key=lambda r: parse_version(r["version"]), default=None)

        response = await client.get(f"{base}/latest", headers=headers)
        response.raise_for_status()
        payload = response.json()
        return _release_record(payload) if isinstance(payload, dict) else None


# ── Scheduling ────────────────────────────────────────────────────────────────


def _claim(now: datetime) -> bool:
    """Take the right to check now. At most one process wins per interval.

    One atomic upsert: it matches only when ``next_check_at`` is due or missing and
    pushes it a full interval forward. A check is also due when the version that
    last checked is not the one running: an upgrade makes the stored "latest
    release" stale on the spot (it was fetched before the release the instance now
    runs), and the admin panel would show "latest 1.17.3" next to "current 1.17.4"
    for up to a full interval. The version is stored by the same upsert, so two
    workers cannot both see it as changed. "Missing" includes a non-date value: a backup
    restore writes this document back with its datetimes as strings, which neither
    ``$lte`` nor ``$exists: False`` would match, so the claim would fail for good.
    When the document exists but is not due, the
    filter matches nothing and the upsert's insert collides on ``_id``, which is
    how the losers learn someone else holds the slot. MongoDB being unreachable
    means no check, not an unguarded one.
    """
    interval = timedelta(hours=settings.version_check.interval_hours)
    running = get_version()
    try:
        get_instance_settings_collection().find_one_and_update(
            {
                "_id": _DOC_ID,
                "$or": [
                    {"next_check_at": {"$lte": now}},
                    {"next_check_at": {"$not": {"$type": "date"}}},
                    {"checked_version": {"$ne": running}},
                ],
            },
            {"$set": {"next_check_at": now + interval, "checked_version": running}},
            upsert=True,
        )
    except DuplicateKeyError:
        return False
    except Exception as exc:
        logger.debug(f"Version check: could not claim a check slot: {exc}")
        return False
    return True


def _persist(
    now: datetime,
    *,
    latest: dict[str, Any] | None,
    error: str | None,
    force: bool,
) -> None:
    """Record the outcome. Never raises.

    ``latest`` is only written when a fetch produced one, so a failed check keeps
    the previous answer instead of blanking the banner over a transient outage.

    ``next_check_at`` is deliberately not rewound on failure: the claim already
    pushed it a full interval out, so a failing check (GitHub down, rate limit)
    retries next interval rather than every tick, which is what keeps a shared-IP
    rate limit from being hammered. A forced run has not claimed, so it sets the
    same value itself.
    """
    update: dict[str, Any] = {
        "checked_at": now,
        "last_error": error,
        "checked_version": get_version(),
    }
    if latest is not None:
        update["latest"] = latest
    if force:
        update["next_check_at"] = now + timedelta(hours=settings.version_check.interval_hours)
    try:
        get_instance_settings_collection().update_one(
            {"_id": _DOC_ID}, {"$set": update}, upsert=True
        )
    except Exception as exc:
        logger.debug(f"Version check: could not store the result: {exc}")
    invalidate_version_check_cache()


async def run_version_check(*, force: bool = False) -> dict[str, Any]:
    """Check GitHub for a newer release and return the admin view. Never raises.

    Without ``force`` the check first claims the interval slot and returns
    straight away when another process holds it. ``force`` (the admin's "Check
    now") skips the claim but still pushes ``next_check_at`` out.
    """
    now = utc_now_naive()
    if not force and not _claim(now):
        return admin_view()

    current = get_version()
    latest: dict[str, Any] | None = None
    error: str | None = None
    try:
        latest = await _fetch_latest_release(current)
        if latest is None:
            error = "No release with a recognisable version found"
    except Exception as exc:
        error = _short_error(exc)
        logger.debug(f"Version check failed: {type(exc).__name__}: {exc}")

    _persist(now, latest=latest, error=error, force=force)
    return admin_view()


async def periodic_version_check() -> None:
    """Run in every worker for the life of the process; the claim picks the one
    that actually checks. Each tick is wrapped so that nothing (MongoDB down, a
    bad payload) can end the loop and silently stop the checks."""
    await asyncio.sleep(FIRST_RUN_DELAY_SECONDS)
    while True:
        try:
            if is_enabled():
                await run_version_check()
        except Exception as exc:
            logger.debug(f"Version check: iteration failed: {exc}")
        await asyncio.sleep(TICK_SECONDS)


# ── Views ─────────────────────────────────────────────────────────────────────


def _iso(value: Any) -> str | None:
    """Naive-UTC ISO string without offset, like every other API timestamp (the
    frontend appends 'Z')."""
    if not isinstance(value, datetime):
        return None
    return _naive_utc(value).isoformat(timespec="seconds")


def _latest_fields(state: dict[str, Any], enabled: bool) -> dict[str, Any]:
    latest = state.get("latest") or {}
    latest_version = latest.get("version")
    return {
        "update_available": bool(enabled and is_newer(latest_version, get_version())),
        "latest_version": latest_version,
        "release_url": latest.get("url"),
        "published_at": _iso(latest.get("published_at")),
        "checked_at": _iso(state.get("checked_at")),
        "last_error": state.get("last_error"),
    }


def admin_view() -> dict[str, Any]:
    """Everything the /admin panel shows. Reads uncached, see the module docstring."""
    state = _read_state(cached=False)
    enabled = is_enabled(state)
    cfg = settings.version_check
    return {
        "enabled": enabled,
        "env_enabled": cfg.enabled,
        "override": _override(state),
        "locked_by_env": locked_by_env(),
        "interval_hours": cfg.interval_hours,
        "repository": cfg.repository,
        "current_version": get_version(),
        **_latest_fields(state, enabled),
    }


def public_block() -> dict[str, Any]:
    """The subset embedded in ``/utils/server-info`` for admins."""
    enabled = is_enabled()
    return {
        "enabled": enabled,
        "locked_by_env": locked_by_env(),
        **_latest_fields(_read_state(), enabled),
    }
