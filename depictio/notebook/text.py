"""A text tile's live values, filled in the way the viewer fills them.

A text tile can print values the server computes under the dashboard's
filters: ``{{name}}`` for a value it declares under ``values:`` (a column
aggregated like a card), ``{{param:KEY}}`` for one of the run's pipeline
parameters. ``bulk_compute_cards`` answers both for the tile's index; this
module puts the answers into the markdown, formatted as the viewer's
``textValues.ts`` / ``card/metrics/format.ts`` print them.

Pure Python (no server imports): it runs in the reader's kernel.
"""

from __future__ import annotations

import math
import re
from typing import Any

# textValues.ts's PLACEHOLDER: `{{name}}` (what `values:` allows), `{{param:KEY}}`
# and `{{legend:column}}` (a colour key, which the export resolves at export time).
PLACEHOLDER = re.compile(
    r"\{\{(param:[A-Za-z0-9_.-]+|legend:[A-Za-z0-9_.-]+|[a-z][a-z0-9_]{0,11})\}\}"
)

MISSING_VALUE = "\N{EN DASH}"


def _trim(text: str) -> str:
    return text.rstrip("0").rstrip(".") if "." in text else text


def _fixed(v: float, digits: int) -> str:
    """``Intl.NumberFormat('en-US', {maximumFractionDigits: digits})``."""
    return _trim(f"{v:,.{digits}f}")


def _significant(v: float, digits: int) -> str:
    """``Intl.NumberFormat('en-US', {maximumSignificantDigits: digits})``, never scientific."""
    if v == 0:
        return "0"
    places = max(0, digits - 1 - int(math.floor(math.log10(abs(v)))))
    return _trim(f"{round(v, places):,.{places}f}")


def format_card_number(v: float) -> str:
    """``formatCardNumber``: decimals that shrink as the magnitude grows."""
    if not math.isfinite(v):
        return "\N{EM DASH}"
    if float(v).is_integer():
        return f"{int(v):,}"
    a = abs(v)
    if a >= 1000:
        return _fixed(v, 0)
    if a >= 100:
        return _fixed(v, 1)
    if a >= 1:
        return _fixed(v, 2)
    if a >= 0.001:
        return _significant(v, 3)
    if a >= 0.0001:
        return _significant(v, 2)
    return f"{v:.2e}"


_SI_UNITS = ((1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k"))


def _si(v: float) -> str:
    a = abs(v)
    for i, (unit, suffix) in enumerate(_SI_UNITS):
        if a < unit:
            continue
        scaled = round(v / unit * 10) / 10
        if abs(scaled) >= 1000 and i > 0:
            up, up_suffix = _SI_UNITS[i - 1]
            return f"{_fixed(v / up, 1)}{up_suffix}"
        return f"{_fixed(scaled, 1)}{suffix}"
    return format_card_number(v)


def format_number(v: float, fmt: str | None = None) -> str:
    """``formatNumber``: ``percent``, ``integer``, ``si``, ``decimals:N``, else a card's."""
    if not math.isfinite(v):
        return "\N{EM DASH}"
    f = (fmt or "").strip()
    if f == "percent":
        pct = v * 100
        a = abs(pct)
        if a >= 10:
            return f"{_fixed(pct, 0)}%"
        if a >= 1 or pct == 0:
            return f"{_fixed(pct, 1)}%"
        return f"{_significant(pct, 2)}%"
    if f == "integer":
        return f"{int(round(v)) or 0:,}"
    if f == "si":
        return _si(v)
    m = re.fullmatch(r"decimals:([0-6])", f)
    if m:
        if float(v).is_integer():
            return f"{int(v):,}"
        return f"{v:,.{int(m.group(1))}f}"
    return format_card_number(v)


def format_text_value(value: Any, fmt: str | None = None) -> str:
    """``formatTextValue``: a dash for a missing value, a string as is."""
    if value is None:
        return MISSING_VALUE
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if not math.isfinite(value):
        return MISSING_VALUE
    return format_number(float(value), fmt)


def fill_text(
    template: str,
    values: dict[str, Any] | None,
    formats: dict[str, str] | None = None,
    legends: dict[str, str] | None = None,
) -> str:
    """``template`` with every placeholder replaced by its formatted value.

    ``values`` is the tile's entry of ``bulk_compute_cards``' ``values``
    (``{name: v, "param:KEY": v}``), ``formats`` each declared value's own
    ``format``, ``legends`` the rendered colour key per ``legend:column``.
    A placeholder with no answer prints a dash, as the viewer does.
    """
    values = values or {}
    formats = formats or {}
    legends = legends or {}

    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key.startswith("legend:"):
            return legends.get(key, "")
        return format_text_value(
            values.get(key), None if key.startswith("param:") else formats.get(key)
        )

    return PLACEHOLDER.sub(sub, template)
