"""What agent tools send back: untrusted text marked as data, results cut to a budget."""

from __future__ import annotations

import json
import re
from typing import Any

# C0/C1 control characters except tab and newline, the Unicode bidi overrides
# and isolates, directional marks and zero-width characters. Bidi overrides can
# make text read differently to a model than to a human reviewer, and
# zero-width characters can hide instructions inside innocent-looking text.
_STRIP_RE = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]"
)

TRUNCATION_MARKER = "... [truncated]"


def clean_text(text: str) -> str:
    """Drop control, bidi and zero-width characters; keep newlines and tabs."""
    return _STRIP_RE.sub("", text)


def untrusted(text: str | None) -> dict[str, str] | None:
    """Wrap user-authored text so agents read it as data, never as instructions.

    Every free-text field a tool returns (comment bodies, titles, text
    components, cell values) goes through this. ``None`` stays ``None`` so
    optional fields need no special casing.
    """
    if text is None:
        return None
    return {"untrusted": clean_text(str(text))}


def json_size(obj: Any) -> int:
    return len(json.dumps(obj, default=str, ensure_ascii=False))


def _shrink(node: Any, target: int) -> Any:
    """Return a copy of ``node`` whose JSON dump aims to fit in ``target`` chars."""
    if json_size(node) <= target:
        return node
    if isinstance(node, str):
        keep = max(target - len(TRUNCATION_MARKER) - 2, 0)
        # Escaped characters (quotes, newlines) take more room once dumped.
        while keep > 0:
            over = json_size(node[:keep] + TRUNCATION_MARKER) - target
            if over <= 0:
                break
            keep = max(keep - over, 0)
        return node[:keep] + TRUNCATION_MARKER
    if isinstance(node, list):
        # Keep the head of the list: tools return rows and items in their
        # most useful order (sorted, paginated), so the tail is what goes.
        kept: list[Any] = []
        used = 2
        for item in node:
            size = json_size(item) + 2
            if used + size > target:
                break
            kept.append(item)
            used += size
        if not kept and node:
            kept = [_shrink(node[0], target - 2)]
        return kept
    if isinstance(node, dict):
        out = dict(node)
        # Repeatedly shrink the largest value until the dict fits or nothing
        # can shrink any more (a dict of many small scalars).
        for _ in range(len(out) * 2):
            excess = json_size(out) - target
            if excess <= 0:
                break
            key = max(out, key=lambda k: json_size(out[k]))
            current = json_size(out[key])
            shrunk = _shrink(out[key], max(current - excess, 0))
            if json_size(shrunk) >= current:
                break
            out[key] = shrunk
        return out
    return node


def fit_to_budget(obj: Any, max_chars: int) -> tuple[Any, bool]:
    """Cut ``obj`` down until its JSON dump fits in ``max_chars``.

    Lists lose items from the end, long strings are cut with a marker, dicts
    shrink their largest values first. Returns ``(obj, truncated)``. When the
    structure cannot shrink enough (many small keys), the JSON text itself is
    cut and returned as a string.
    """
    if json_size(obj) <= max_chars:
        return obj, False
    shrunk = _shrink(obj, max_chars)
    if json_size(shrunk) <= max_chars:
        return shrunk, True
    text = json.dumps(obj, default=str, ensure_ascii=False)
    return _shrink(text, max_chars), True
