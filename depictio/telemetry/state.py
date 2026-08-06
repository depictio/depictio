"""Persistent anonymous ID for the CLI.

Counting CLI *installations* rather than CLI *invocations* needs an ID that
survives across runs, which means a file on disk. This is the first thing the CLI
ever writes under ``~/.depictio`` — today that directory is a read-only config
location as far as the CLI is concerned (``cli/cli/utils/common.py`` only ever
reads ``CLI.yaml`` from it) — so the write has to be defensive.

Three failure modes are all handled by degrading rather than raising, because a
telemetry file is never a good enough reason to fail a user's command:

* **Read-only or absent ``$HOME``** — common in containers and CI. Falls back to
  an in-memory ID flagged ``ephemeral``, so such runs are visibly
  over-counted at the collector rather than silently inflating install numbers
  with no way to tell.
* **Concurrent invocations** — two CLIs starting at once must not interleave
  writes into a half-written file. Written to a temporary file in the same
  directory and moved into place with :func:`os.replace`, which is atomic on
  POSIX, so a reader sees either the old file or the new one.
* **Corrupt file** — hand-edited or truncated by a full disk. Treated as absent
  and rewritten.
"""

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Final, NamedTuple

logger = logging.getLogger("depictio-telemetry")

#: Overrides the state directory outright. Documented for operators who keep
#: ``$HOME`` read-only but still want stable counting.
STATE_DIR_ENV: Final[str] = "DEPICTIO_TELEMETRY_STATE_DIR"

STATE_FILENAME: Final[str] = "telemetry.json"

#: Key under which the anonymous ID is stored.
_ID_KEY: Final[str] = "anonymous_id"

#: Key recording that the first-run telemetry notice has been displayed.
#:
#: Deliberately separate from the ID. Keying the notice off "the ID did not exist
#: until now" looks equivalent and is not: a first invocation from a script or a
#: cron job creates the ID while showing nothing, and every later interactive run
#: then thinks the user has already been told. The disclosure would be skipped for
#: exactly the users whose first contact with the CLI was automated.
_NOTICE_KEY: Final[str] = "notice_shown"


class AnonymousId(NamedTuple):
    """An anonymous CLI ID plus whether it survived to disk."""

    value: str
    ephemeral: bool


def state_dir() -> Path:
    """Directory the telemetry state file lives in.

    Prefers an explicit override, then the XDG state location for people who keep
    a tidy home directory, and finally ``~/.depictio`` — which is where the CLI
    already looks for its config, so operators only have one Depictio directory to
    know about.
    """
    override = os.getenv(STATE_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    xdg_state = os.getenv("XDG_STATE_HOME", "").strip()
    if xdg_state:
        return Path(xdg_state).expanduser() / "depictio"

    return Path.home() / ".depictio"


def state_path() -> Path:
    """Full path to the telemetry state file."""
    return state_dir() / STATE_FILENAME


def _read_state(path: Path) -> dict:
    """Parse the state file, or ``{}`` if absent, unreadable or malformed."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.debug("Telemetry state file %s is not valid JSON; regenerating", path)
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _read_id(path: Path) -> str | None:
    """Read the stored ID, or ``None`` if absent, unreadable or malformed."""
    stored = _read_state(path).get(_ID_KEY)
    if isinstance(stored, str) and stored:
        return stored
    return None


def _write_state(path: Path, updates: dict) -> bool:
    """Merge ``updates`` into the state file atomically. False on any IO failure.

    Read-modify-write, so writing one key cannot drop another: the ID and the
    notice flag are set at different moments by different code paths. Two CLIs
    racing can still lose one update, the worst outcome being a notice shown
    twice, which is why nothing here takes a lock.

    The temporary file is created in the destination directory so that
    :func:`os.replace` stays within one filesystem, where it is atomic.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        state = _read_state(path)
        state.update(updates)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".telemetry-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle)
            os.replace(tmp_name, path)
        except OSError:
            # Leave no debris behind if the move failed.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except OSError as exc:
        logger.debug("Could not persist telemetry state to %s: %s", path, exc)
        return False
    return True


def first_run_notice_shown() -> bool:
    """Whether the CLI has already disclosed telemetry to this user.

    True on any failure to find out. A notice repeated because the flag could not
    be read is worse than one missed: users mute what repeats.
    """
    try:
        return _read_state(state_path()).get(_NOTICE_KEY) is True
    except (OSError, RuntimeError):
        return True


def mark_first_run_notice_shown() -> None:
    """Record that the notice has been displayed. Never raises."""
    try:
        _write_state(state_path(), {_NOTICE_KEY: True})
    except (OSError, RuntimeError) as exc:
        logger.debug("Could not record the telemetry notice as shown: %s", exc)


def get_or_create_anonymous_id() -> AnonymousId:
    """Return this machine's anonymous CLI ID, creating and storing it if needed.

    Never raises. When the ID cannot be persisted the returned tuple is flagged
    ``ephemeral`` so the caller can report that, and the collector can discount
    those events instead of treating each one as a fresh installation.
    """
    value = uuid.uuid4().hex
    try:
        path = state_path()
    except (OSError, RuntimeError) as exc:
        # ``Path.home()`` raises RuntimeError when the home directory cannot be
        # resolved at all — no $HOME and no passwd entry, which happens in
        # scratch containers.
        logger.debug("Could not resolve telemetry state location: %s", exc)
        return AnonymousId(value, ephemeral=True)

    existing = _read_id(path)
    if existing is not None:
        return AnonymousId(existing, ephemeral=False)

    if _write_state(path, {_ID_KEY: value}):
        return AnonymousId(value, ephemeral=False)
    return AnonymousId(value, ephemeral=True)
