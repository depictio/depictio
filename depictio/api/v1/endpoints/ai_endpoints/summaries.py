"""Section-summary support: digest trimming, context hashing, Mongo cache.

The summarize flow is client-context driven: the browser sends what the
user actually sees (card values, trimmed figure data, table rows — filters
applied), so the server never re-renders anything. This module owns the
three server-side responsibilities around that payload:

- **Trim** the digests (defense in depth on top of client-side caps) so a
  pathological payload can't blow the prompt budget.
- **Hash** the visible context. The hash keys the cache and powers the
  staleness badge: the client recomputes it and compares with the stored
  entry's hash — mismatch means data/filters changed since generation.
- **Cache** summaries in the ``ai_summaries`` Mongo collection, keyed
  ``(dashboard_id, section, context_hash)``. Summaries are derived
  artifacts — deliberately NOT stored on ``DashboardData`` so the dashboard
  model, YAML round-trip and save payload stay untouched.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.ai_endpoints.schemas import (
    SummaryComponent,
    SummaryEntry,
)

logger = logging.getLogger(__name__)

# Per-digest caps applied recursively. Lists keep head+tail so the LLM sees
# the value range; strings keep a prefix.
MAX_LIST_ITEMS = 60
MAX_STRING_CHARS = 400
MAX_DIGEST_CHARS = 8_000


def trim_digest(value: Any, *, max_list: int = MAX_LIST_ITEMS, max_str: int = MAX_STRING_CHARS):
    """Recursively cap list lengths and string sizes inside a digest."""
    if isinstance(value, str):
        if len(value) > max_str:
            return value[:max_str] + f"… [{len(value) - max_str} chars trimmed]"
        return value
    if isinstance(value, list):
        if len(value) > max_list:
            head = max_list // 2
            tail = max_list - head
            kept = value[:head] + value[-tail:]
            trimmed = [trim_digest(v, max_list=max_list, max_str=max_str) for v in kept]
            trimmed.insert(head, f"… [{len(value) - max_list} items trimmed]")
            return trimmed
        return [trim_digest(v, max_list=max_list, max_str=max_str) for v in value]
    if isinstance(value, dict):
        return {k: trim_digest(v, max_list=max_list, max_str=max_str) for k, v in value.items()}
    return value


def trim_component(component: SummaryComponent) -> SummaryComponent:
    digest = trim_digest(component.digest)
    # Whole-digest character budget: serialize and hard-cap.
    as_json = json.dumps(digest, default=str)
    if len(as_json) > MAX_DIGEST_CHARS:
        digest = as_json[:MAX_DIGEST_CHARS] + "… [digest truncated]"
    return component.model_copy(update={"digest": digest})


def compute_context_hash(
    section: str | None,
    filters: list[dict[str, Any]],
    components: list[SummaryComponent],
) -> str:
    """Stable hash of the visible context (post-trim, order-insensitive).

    Components are keyed by id and filters serialized sorted so cosmetic
    reordering doesn't read as staleness.
    """
    payload = {
        "section": section,
        "filters": sorted(
            (json.dumps(f, sort_keys=True, default=str) for f in filters),
        ),
        "components": {
            c.id: json.dumps(
                {"type": c.type, "title": c.title, "digest": c.digest},
                sort_keys=True,
                default=str,
            )
            for c in components
        },
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _collection():
    """Resolved lazily so tests can monkeypatch depictio.api.v1.db."""
    from depictio.api.v1.db import ai_summaries_collection

    return ai_summaries_collection


def get_cached(dashboard_id: str, section: str | None, context_hash: str) -> dict[str, Any] | None:
    return _collection().find_one(
        {
            "dashboard_id": dashboard_id,
            "section": section,
            "context_hash": context_hash,
        }
    )


def put_cache(
    dashboard_id: str,
    section: str | None,
    context_hash: str,
    summary_md: str,
    model: str,
) -> dict[str, Any]:
    entry = {
        "dashboard_id": dashboard_id,
        "section": section,
        "context_hash": context_hash,
        "summary_md": summary_md,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    # One summary per (dashboard, section): the latest generation replaces
    # prior hashes so the collection can't grow unboundedly per section.
    _collection().replace_one(
        {"dashboard_id": dashboard_id, "section": section},
        entry,
        upsert=True,
    )
    return entry


def latest_for_dashboard(dashboard_id: str) -> list[SummaryEntry]:
    entries = _collection().find({"dashboard_id": dashboard_id})
    return [
        SummaryEntry(
            section=e.get("section"),
            summary_md=e.get("summary_md", ""),
            generated_at=e.get("generated_at", ""),
            model=e.get("model", ""),
            context_hash=e.get("context_hash", ""),
        )
        for e in entries
    ]


def summarize_section_messages(
    section: str | None,
    filters: list[dict[str, Any]],
    components: list[SummaryComponent],
) -> list[dict]:
    """Prompt for the section summary."""
    section_label = section or "the dashboard (no section)"
    filters_block = (
        "\n".join(f"- {json.dumps(f, default=str)}" for f in filters)
        if filters
        else "(no active filters)"
    )
    lines = []
    for c in components:
        digest_json = json.dumps(c.digest, default=str)
        lines.append(f"### {c.title or c.id} ({c.type})\n{digest_json}")
    components_block = "\n\n".join(lines) if lines else "(no components)"

    budget = settings.ai.max_context_chars
    if len(components_block) > budget:
        components_block = components_block[:budget] + "… [context truncated]"

    system = f"""You summarize one section of a data dashboard for its viewers.

You receive the rendered state of every component in the section — card
values, figure data (Plotly traces), table rows — exactly as the user sees
it, with the currently-active filters applied.

Write a concise Markdown summary (3-8 sentences, optionally one short
bullet list) that:
- states the key numbers and what they mean together,
- calls out notable patterns, outliers or imbalances visible in the data,
- mentions when active filters scope the view ("among the filtered rows…").

Do NOT describe chart types or dashboard mechanics ("this bar chart
shows…") — talk about the data. No headings, no preamble, no code fences.

SECTION: {section_label}

ACTIVE FILTERS:
{filters_block}

COMPONENTS:
{components_block}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Summarize section: {section_label}"},
    ]
