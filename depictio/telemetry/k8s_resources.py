"""Kubernetes resource-quantity parsing.

The Helm chart states replica count and CPU/memory requests/limits the same
way it already states ``deployment_kind`` — as plain env vars, verbatim from
``values.yaml`` — because that is what the chart already knows at template
time, at zero runtime cost and with no new Kubernetes RBAC permissions or
Python dependencies. Parsing happens here, in Python, rather than in the
chart's Go templates, which have no real string-math support for the several
notations Kubernetes accepts for the same quantity ("0.5" and "500m" are both
half a CPU core; "1Gi" and "1024Mi" are both the same amount of memory).

A string that fails to parse becomes ``None`` and is never echoed back
verbatim — this is the one place in the telemetry pipeline that touches an
operator-typed string, so it is validated on the way in rather than trusted,
the same discipline :mod:`depictio.telemetry.env` applies to
``DEPICTIO_TELEMETRY_DEPLOYMENT_KIND``.
"""

import re
from typing import Final

_CPU_MILLI_RE: Final = re.compile(r"^(\d+(?:\.\d+)?)m$")
_MEMORY_RE: Final = re.compile(r"^(\d+(?:\.\d+)?)([EPTGMK]i?)?$")

#: Binary (1024-based) suffixes, as Kubernetes spells them.
_BINARY_MULTIPLIERS: Final[dict[str, int]] = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "Pi": 1024**5,
    "Ei": 1024**6,
}
#: Decimal (1000-based) suffixes.
_DECIMAL_MULTIPLIERS: Final[dict[str, int]] = {
    "K": 1000,
    "M": 1000**2,
    "G": 1000**3,
    "T": 1000**4,
    "P": 1000**5,
    "E": 1000**6,
}


def parse_cpu_millicores(raw: str | None) -> int | None:
    """Parse a Kubernetes CPU quantity ("500m", "0.5", "2") into millicores.

    Returns ``None`` for anything that does not parse, rather than raising —
    a malformed operator-typed value must degrade the field, not the payload.
    """
    if not raw:
        return None
    raw = raw.strip()
    milli_match = _CPU_MILLI_RE.match(raw)
    if milli_match:
        return round(float(milli_match.group(1)))
    try:
        cores = float(raw)
    except ValueError:
        return None
    if cores < 0:
        return None
    return round(cores * 1000)


def parse_memory_mib(raw: str | None) -> int | None:
    """Parse a Kubernetes memory quantity ("1Gi", "512Mi", "1G") into MiB.

    Returns ``None`` for anything that does not parse.
    """
    if not raw:
        return None
    match = _MEMORY_RE.match(raw.strip())
    if not match:
        return None
    value_str, suffix = match.groups()
    try:
        value = float(value_str)
    except ValueError:
        return None
    if value < 0:
        return None
    if suffix is None:
        total_bytes = value
    elif suffix in _BINARY_MULTIPLIERS:
        total_bytes = value * _BINARY_MULTIPLIERS[suffix]
    elif suffix in _DECIMAL_MULTIPLIERS:
        total_bytes = value * _DECIMAL_MULTIPLIERS[suffix]
    else:
        return None
    return round(total_bytes / (1024**2))
