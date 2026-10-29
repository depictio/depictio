"""Order the values a filter offers.

A categorical filter lists the distinct values of a column. Sorted as strings,
a time course reads ``18h``, ``1h``, ``2h``, ``30min`` (the alphabet puts
``18h`` first and ``30min`` after ``2h``). Two rules fix that, shared by the
option endpoints and mirrored by ``orderCategoricalOptions`` (React):

* a companion column (``order_by`` on the filter) gives each value a key, and
  the values follow their keys: numbers when every key is one, else naturally;
* with no companion, values that all end in a duration (``30min``, ``2h``,
  ``GM_1d``) follow the duration. Anything else keeps its plain sort.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

#: Trailing duration of a label: ``30min``, ``2h``, ``1.5 hr``, ``3d``, ``45s``,
#: after an underscore, dash, dot, space or nothing (``GM_12h`` reads 12 hours,
#: ``REP12`` reads nothing). Same rule as ``depictio.recipes.lib.time_course``
#: and ``parseDurationHours`` in React.
_DURATION_RE = re.compile(
    r"(?:^|[_\-.\s])(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>s|sec|secs|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)$",
    re.IGNORECASE,
)
_UNIT_HOURS = {"s": 1 / 3600, "m": 1 / 60, "h": 1.0, "d": 24.0}
_NATURAL_SPLIT = re.compile(r"(\d+)")


def parse_duration_hours(label: str | None) -> float | None:
    """Hours in the trailing duration of ``label``, ``None`` when it ends in none."""
    if label is None:
        return None
    match = _DURATION_RE.search(str(label).strip())
    if not match:
        return None
    unit = match.group("unit").lower()
    key = "m" if unit.startswith("m") else unit[0]
    return float(match.group("value")) * _UNIT_HOURS[key]


def natural_key(text: str) -> list[Any]:
    """Sort key putting ``Sample_2`` before ``Sample_10`` (case-insensitive)."""
    return [int(p) if p.isdigit() else p.lower() for p in _NATURAL_SPLIT.split(text)]


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def order_values(
    values: Iterable[Any],
    keys: Mapping[str, Any] | None = None,
) -> list[str]:
    """The distinct ``values`` as strings, in filter order.

    ``keys`` maps a value to its order key (the companion column). Values with a
    key follow it, numerically when every key present is a number; a value with
    none goes last. Ties, and the no-``keys`` case, fall back on the duration
    the labels end in when every one has one, else on the plain string sort.
    """
    distinct = sorted({str(v) for v in values if v is not None})
    if keys:
        present = {v: keys[v] for v in distinct if keys.get(v) not in (None, "")}
        numeric = bool(present) and all(_is_number(k) for k in present.values())

        def keyed(v: str) -> tuple[Any, ...]:
            if v not in present:
                return (1, 0, natural_key(v))
            k = float(present[v]) if numeric else natural_key(str(present[v]))
            return (0, k, natural_key(v))

        return sorted(distinct, key=keyed)
    hours = {v: parse_duration_hours(v) for v in distinct}
    if distinct and all(h is not None for h in hours.values()):
        return sorted(distinct, key=lambda v: (hours[v], natural_key(v)))
    return distinct
