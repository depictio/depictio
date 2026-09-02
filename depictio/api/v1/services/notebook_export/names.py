"""Python identifiers for the generated notebook.

marimo requires every global to be defined by exactly one cell, so each
funnel stage, group, figure, card and table needs its own name. Names are
derived from what the reader sees in the dashboard (a DC tag, a component
title, a column) and de-duplicated by the allocator; nothing in the notebook
is ever called ``df`` or ``fig``, which the code-mode snippets use locally.
"""

from __future__ import annotations

import builtins
import keyword
import re
import unicodedata

# Names the notebook's own scaffolding claims, plus everything a code-mode
# snippet expects to find in scope. A generated global must never shadow them.
RESERVED_NAMES: frozenset[str] = frozenset(
    {
        "marimo",
        "app",
        "mo",
        "pl",
        "px",
        "go",
        "pd",
        "np",
        "datetime",
        "col",
        "lit",
        "df",
        "fig",
        "client",
        "DASHBOARD_ID",
        "DepictioClient",
        "depictio_state",
        "metric_card",
    }
    | set(keyword.kwlist)
    | set(dir(builtins))
)

_NON_IDENT = re.compile(r"[^a-z0-9]+")


def slug(text: object, *, max_len: int = 40, fallback: str = "item") -> str:
    """A lowercase ``snake_case`` fragment usable inside an identifier.

    Accents are stripped (``Espèce`` → ``espece``), anything that is not a
    letter or digit becomes one underscore, and the result never starts with a
    digit or is empty.
    """
    raw = "" if text is None else str(text)
    ascii_text = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    frag = _NON_IDENT.sub("_", ascii_text.lower()).strip("_")
    if not frag:
        frag = fallback
    if frag[0].isdigit():
        frag = f"{fallback}_{frag}"
    frag = frag[:max_len].rstrip("_") or fallback
    return frag


class NameAllocator:
    """Hands out unique, reserved-safe identifiers.

    ``claim("fig", "Bill shape")`` → ``fig_bill_shape``; a second component
    with the same title gets ``fig_bill_shape_2``.
    """

    def __init__(self, reserved: frozenset[str] = RESERVED_NAMES) -> None:
        self._taken: set[str] = set(reserved)

    def claim(self, prefix: str, hint: object, *, fallback: str = "item") -> str:
        base = f"{slug(prefix)}_{slug(hint, fallback=fallback)}" if prefix else slug(hint)
        candidate = base
        n = 2
        while candidate in self._taken:
            candidate = f"{base}_{n}"
            n += 1
        self._taken.add(candidate)
        return candidate

    def reserve(self, name: str) -> None:
        self._taken.add(name)

    def __contains__(self, name: str) -> bool:
        return name in self._taken
