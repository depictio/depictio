"""Anonymous telemetry for the CLI.

Answers two questions the project cannot otherwise see: how many people have
``depictio-cli`` installed (PyPI download counts conflate CI runs, mirrors and
re-installs), and which of its ~35 commands anyone actually uses.

The privacy-critical piece is :func:`resolve_command_path`. A CLI's argv is full
of things that must never leave the machine — file paths, project names, S3
buckets, occasionally a token someone pasted into the wrong flag. Rather than try
to strip those out, the command path is reconstructed by walking the CLI's *own*
command tree and keeping only tokens that match a registered command or
sub-command name. Anything unrecognised terminates the walk. A sanitiser has to
anticipate every bad input; this cannot emit a string that is not already a
command name in this codebase.

Version and identity also travel as request headers on calls the user is already
making (see ``generate_api_headers``), which is why this module staying silent —
disabled, offline, ``DO_NOT_TRACK`` — still leaves the server able to report which
CLI versions are in use.
"""

import os
import sys
import time
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Any, Final

from depictio.cli.cli_logging import logger
from depictio.telemetry.buckets import bucket_seconds
from depictio.telemetry.constants import (
    CLI_TIMEOUT_SECONDS,
    DEFAULT_API_KEY,
    DEFAULT_ENDPOINT,
)
from depictio.telemetry.env import detect_ci, detect_deployment_kind, platform_info
from depictio.telemetry.gates import telemetry_allowed
from depictio.telemetry.schema import EVENT_CLI_COMMAND, CliCommandProperties
from depictio.telemetry.state import (
    first_run_notice_shown,
    get_or_create_anonymous_id,
    mark_first_run_notice_shown,
)

#: Opt-out, matching the server's variable name.
ENABLED_ENV: Final[str] = "DEPICTIO_TELEMETRY_ENABLED"
ENDPOINT_ENV: Final[str] = "DEPICTIO_TELEMETRY_ENDPOINT"
API_KEY_ENV: Final[str] = "DEPICTIO_TELEMETRY_API_KEY"

#: Placeholder used when argv matched no known command (a bare ``depictio-cli``,
#: or a typo). Recorded rather than dropped so the collector can see how often
#: people invoke the CLI without getting anywhere.
UNKNOWN_COMMAND: Final[str] = "<none>"

#: Collector token shipped with the CLI. Sourced from the one shared constant so
#: the CLI and the server cannot drift onto different projects.
_DEFAULT_API_KEY: Final[str] = DEFAULT_API_KEY


def cli_version() -> str:
    """Installed ``depictio-cli`` version, or ``"dev"`` from a source checkout.

    Same resolution the startup banner and the ``version`` command already use.
    """
    try:
        return _pkg_version("depictio-cli")
    except PackageNotFoundError:
        return "dev"


def _env_flag(name: str, default: bool) -> bool:
    """Read a boolean env var with the same truthiness rules as pydantic-settings."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def resolve_command_path(argv: list[str], root_command: Any) -> str:
    """Reconstruct the command path from argv, keeping only registered names.

    Walks ``argv`` alongside the Click command tree. A token is kept only if it
    names a sub-command of the group reached so far; the first token that does not
    ends the walk. Options (anything starting with ``-``) are skipped, and their
    values are never examined — an option value is exactly the kind of
    user-supplied string this function exists to keep out.

    Args:
        argv: Arguments after the program name, i.e. ``sys.argv[1:]``.
        root_command: The Click command produced from the Typer app.

    Returns:
        A space-joined command path such as ``"data process"``, or
        :data:`UNKNOWN_COMMAND` if nothing matched.
    """
    parts: list[str] = []
    node = root_command

    for token in argv:
        if token.startswith("-"):
            # An option. Its value may follow as a separate token, but since only
            # registered command names are ever kept, a stray value simply fails
            # to match and ends the walk — which is the safe outcome.
            continue

        get_command = getattr(node, "get_command", None)
        if get_command is None:
            # Reached a leaf command; anything further is an argument.
            break

        try:
            child = get_command(None, token)
        except Exception:
            child = None

        if child is None:
            break

        parts.append(token)
        node = child

    return " ".join(parts) if parts else UNKNOWN_COMMAND


def suppression_reason() -> str | None:
    """Why CLI telemetry is off right now, or ``None`` if it is on."""
    reason = telemetry_allowed(enabled=_env_flag(ENABLED_ENV, default=True))
    if reason is not None:
        return reason.value
    if not os.getenv(API_KEY_ENV) and not _DEFAULT_API_KEY:
        return "no_api_key_configured"
    return None


#: Shown once, on the run that creates the anonymous ID. Kept short: an opt-out
#: notice that scrolls a user's real output off the screen gets muted rather than
#: read.
_FIRST_RUN_NOTICE: Final[str] = (
    "\nDepictio collects anonymous usage data (which command ran, whether it "
    "succeeded, OS and version).\n"
    "No file paths, arguments, project names or credentials are ever sent.\n"
    "Opt out with DEPICTIO_TELEMETRY_ENABLED=false or DO_NOT_TRACK=1. "
    "Details: https://github.com/depictio/depictio/blob/main/docs/telemetry.md\n"
)


def maybe_print_first_run_notice() -> None:
    """Tell the user about telemetry, once, the first time they run the CLI.

    Telemetry that defaults to enabled has to be visible to the person it counts.
    The server states it in its boot logs on every start; the CLI has no logs an
    operator reads, so it says it here instead — the convention Homebrew, .NET and
    Next.js all follow.

    Silent when telemetry is off, since there is then nothing to disclose. Written
    to stderr and gated on *stderr* being a terminal, so a piped command still
    tells the person at the keyboard while leaving stdout clean for whatever is
    reading it. Never raises — a notice must not be able to break a command.

    The "shown" flag is only written once the notice actually reaches a terminal.
    A first invocation from a script or a cron job therefore leaves it unset, and
    the user still gets told the first time they run the CLI themselves.
    """
    try:
        if suppression_reason() is not None:
            return

        if not sys.stderr.isatty() or first_run_notice_shown():
            return

        print(_FIRST_RUN_NOTICE, file=sys.stderr)
        mark_first_run_notice_shown()
    except Exception as exc:
        logger.debug(f"CLI telemetry notice failed: {exc}")


def build_properties(command: str, *, succeeded: bool, duration_seconds: float) -> dict[str, Any]:
    """Assemble the ``cli_command`` payload.

    Validated through the pydantic model in :mod:`depictio.telemetry.schema`, which
    forbids extra fields — so this cannot grow an undeclared key that the docs and
    the leak test would not see.
    """
    platform = platform_info()
    anon = get_or_create_anonymous_id()

    properties = CliCommandProperties(
        depictio_version=cli_version(),
        deployment_kind=detect_deployment_kind(),
        os=platform["os"],
        arch=platform["arch"],
        python_version=platform["python_version"],
        command=command,
        succeeded=succeeded,
        duration_bucket=bucket_seconds(duration_seconds),
        is_ci=detect_ci(),
        id_ephemeral=anon.ephemeral,
    )
    return properties.model_dump(mode="json")


def send_command_event(command: str, *, succeeded: bool, duration_seconds: float) -> None:
    """Report one command invocation. Never raises, never blocks for long.

    Called from a ``finally`` on the way out of the process, under a 2s timeout, so
    a slow or unreachable collector delays the user's shell prompt by at most that
    — and a broken collector cannot fail their command at all.
    """
    try:
        if suppression_reason() is not None:
            return

        from depictio.telemetry.posthog import capture

        anon = get_or_create_anonymous_id()
        capture(
            EVENT_CLI_COMMAND,
            anon.value,
            build_properties(command, succeeded=succeeded, duration_seconds=duration_seconds),
            api_key=os.getenv(API_KEY_ENV) or _DEFAULT_API_KEY,
            endpoint=os.getenv(ENDPOINT_ENV) or DEFAULT_ENDPOINT,
            timeout=CLI_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.debug(f"CLI telemetry send failed: {exc}")


class CommandTimer:
    """Times a command invocation for the duration bucket."""

    def __init__(self) -> None:
        self._start = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self._start
