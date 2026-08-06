"""The kill switches. Every send path consults :func:`telemetry_allowed` first.

Telemetry defaults to on, which only stays defensible if turning it off is
trivial, honoured everywhere, and honest about it. There are two distinct kinds
of suppression here and they exist for different reasons:

*Consent* — ``DEPICTIO_TELEMETRY_ENABLED=false`` and the cross-vendor
``DO_NOT_TRACK`` convention (consoledonottrack.com). These are the operator
saying no, and they win unconditionally.

*Data hygiene* — CI, pytest and ``DEPICTIO_MONGODB_WIPE``. These are not consent
signals; they suppress sends because the resulting numbers would be wrong.
Depictio's own CI boots the API on nearly every workflow and users' pipelines run
``depictio-cli`` on every commit, so automation would otherwise dominate the
install count, and a wiped database has just thrown away the instance identity
that makes an install countable in the first place.
"""

import os
from enum import Enum
from typing import Final

from depictio.telemetry.env import detect_ci, detect_pytest

#: Cross-vendor opt-out convention shared by a number of CLI tools.
#: See https://consoledonottrack.com — any non-empty value other than "0" means no.
DO_NOT_TRACK_ENV: Final[str] = "DO_NOT_TRACK"


class SuppressionReason(str, Enum):
    """Why a telemetry send was skipped.

    A ``str`` enum so the value can go straight into a log line or the admin
    preview endpoint without extra formatting.
    """

    DISABLED = "disabled_by_config"
    DO_NOT_TRACK = "do_not_track_env"
    CI = "ci_environment"
    TESTING = "test_environment"
    WIPE = "database_wipe_mode"


def do_not_track() -> bool:
    """True when ``DO_NOT_TRACK`` asks us not to send anything.

    Treats any non-empty value except ``"0"`` and ``"false"`` as opting out, which
    is the permissive reading — someone who sets this variable at all means it.
    """
    raw = os.getenv(DO_NOT_TRACK_ENV, "").strip().lower()
    return bool(raw) and raw not in ("0", "false")


def telemetry_allowed(
    *,
    enabled: bool,
    wipe: bool = False,
) -> SuppressionReason | None:
    """Return the reason telemetry must not be sent, or ``None`` if it may be.

    Returning the *reason* rather than a bare bool is deliberate: callers log it
    and the admin preview endpoint displays it, so an operator wondering why no
    events appear gets a precise answer instead of having to guess which switch
    is active.

    Args:
        enabled: The resolved config flag (``settings.telemetry.enabled`` on the
            server, the equivalent env read in the CLI).
        wipe: Whether the deployment booted with ``DEPICTIO_MONGODB_WIPE`` set.
            Server-only; the CLI has no database to wipe.
    """
    if not enabled:
        return SuppressionReason.DISABLED
    if do_not_track():
        return SuppressionReason.DO_NOT_TRACK
    if detect_pytest():
        return SuppressionReason.TESTING
    if detect_ci():
        return SuppressionReason.CI
    if wipe:
        return SuppressionReason.WIPE
    return None
