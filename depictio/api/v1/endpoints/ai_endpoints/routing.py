"""Choose the component type and data collection for a prompt.

The user writes the prompt first; the type and the collection are optional
pins. Whatever is left open is settled here, before generation, from the
project inventory (`context.build_project_inventory`):

1. No-LLM shortcuts when the type is pinned: exactly one fitting
   collection on the dashboard, else exactly one in the whole project.
2. Otherwise one LLM call (`prompts.route_component_messages`) answering
   strict JSON, validated against the allowed types and the inventory,
   retried once with the rejection reason, then a 502.

The route handler owns the HTTP side; this module raises `RoutingError`
with a status code and detail so that mapping stays in one place.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from depictio.api.v1.endpoints.ai_endpoints import llm_client, prompts
from depictio.api.v1.endpoints.ai_endpoints.context import InventoryEntry, ProjectInventory
from depictio.api.v1.endpoints.ai_endpoints.schemas import (
    ComponentType,
    RoutedCollection,
    RoutingInfo,
)

logger = logging.getLogger(__name__)

ALL_COMPONENT_TYPES: tuple[ComponentType, ...] = get_args(ComponentType)
MAX_ROUTE_ATTEMPTS = 2
MAX_ALTERNATIVES = 3


class RoutingError(Exception):
    """A routing failure the handler turns into an HTTP error."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class RouteDecision:
    """What generation should run with."""

    component_type: ComponentType
    entry: InventoryEntry | None
    routing: RoutingInfo


class _RouteAnswer(BaseModel):
    """The router's JSON, coerced leniently before semantic validation."""

    model_config = ConfigDict(extra="ignore")

    component_type: str
    data_collection_tag: str | None = None
    reason: str = ""
    alternatives: list[str] = Field(default_factory=list)


def routed(entry: InventoryEntry) -> RoutedCollection:
    return RoutedCollection(
        data_collection_id=entry.data_collection_id,
        data_collection_tag=entry.data_collection_tag,
        workflow_id=entry.workflow_id,
        workflow_tag=entry.workflow_tag,
    )


def single_candidate(
    inventory: ProjectInventory, component_type: ComponentType
) -> InventoryEntry | None:
    """The one collection a pinned type can use, when there is no choice to make.

    Dashboard collections first: exactly one fitting collection already on
    the dashboard wins even if the project has others. Failing that,
    exactly one fitting collection in the whole project.
    """
    candidates = inventory.candidates_for(component_type)
    on_dashboard = [e for e in candidates if e.on_dashboard]
    if len(on_dashboard) == 1:
        return on_dashboard[0]
    if not on_dashboard and len(candidates) == 1:
        return candidates[0]
    return None


def _parse_json_lenient(raw: str) -> dict:
    """`llm_client.parse_json`, then the outermost {...} of a chatty reply."""
    try:
        parsed = llm_client.parse_json(raw)
    except Exception:  # noqa: BLE001
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise
        parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("the answer is not a JSON object")
    return parsed


def validate_answer(
    raw: str,
    inventory: ProjectInventory,
    allowed_types: list[ComponentType],
    *,
    pinned_type: ComponentType | None,
    pinned_entry: InventoryEntry | None,
) -> RouteDecision:
    """Turn the router's reply into a decision, or raise ValueError.

    A pinned half is enforced from the request, not from the reply: the
    model is told it is fixed, and echoing it back wrong is not worth a
    retry. Unknown tags in `alternatives` are dropped, not rejected.
    """
    try:
        answer = _RouteAnswer.model_validate(_parse_json_lenient(raw))
    except (ValidationError, ValueError, json.JSONDecodeError) as e:
        raise ValueError(f"the answer is not the expected JSON object ({e})") from e

    component_type = pinned_type or answer.component_type.strip().lower()
    if component_type not in allowed_types:
        raise ValueError(
            f"component_type {answer.component_type!r} is not one of the allowed types "
            f"({', '.join(allowed_types)})"
        )

    entry: InventoryEntry | None
    if component_type == "text":
        entry = None
    elif pinned_entry is not None:
        entry = pinned_entry
    else:
        entry = inventory.entry_for_tag(answer.data_collection_tag)
        if entry is None:
            raise ValueError(
                f"data_collection_tag {answer.data_collection_tag!r} is not in the inventory "
                f"({', '.join(inventory.tags()) or 'empty'})"
            )
        if entry not in inventory.candidates_for(component_type):
            raise ValueError(
                f"data collection {entry.data_collection_tag!r} (type {entry.dc_type}) "
                f"cannot back a {component_type} component"
            )

    alternatives: list[InventoryEntry] = []
    for tag in answer.alternatives:
        if len(alternatives) >= MAX_ALTERNATIVES:
            break
        alt = inventory.entry_for_tag(tag)
        if alt is None:
            logger.info("router named an unknown alternative %r; dropped", tag)
        elif alt is not entry and alt not in alternatives:
            alternatives.append(alt)

    return RouteDecision(
        component_type=component_type,  # type: ignore[arg-type]
        entry=entry,
        routing=RoutingInfo(
            source="auto",
            reason=" ".join(answer.reason.split()) or None,
            alternatives=[routed(e) for e in alternatives],
        ),
    )


def allowed_types_for(
    inventory: ProjectInventory,
    *,
    pinned_type: ComponentType | None,
    pinned_entry: InventoryEntry | None,
) -> list[ComponentType]:
    """Types the router may answer with, given the pins and the inventory.

    A pinned type is the only answer. A pinned collection narrows the list
    to the types it can back (text stays allowed: a prose request with a
    collection selected is still a prose request). With nothing pinned,
    every type that has at least one fitting collection, plus text.
    """
    if pinned_type is not None:
        return [pinned_type]

    def allowed(component_type: ComponentType) -> bool:
        if component_type == "text":
            return True
        candidates = inventory.candidates_for(component_type)
        if pinned_entry is not None:
            return pinned_entry in candidates
        return bool(candidates)

    return [t for t in ALL_COMPONENT_TYPES if allowed(t)]


async def route_component(
    prompt: str,
    inventory: ProjectInventory,
    *,
    pinned_type: ComponentType | None,
    pinned_dc_id: str | None,
    complete: Callable[[list[dict]], str],
) -> RouteDecision:
    """Settle the (type, collection) pair for one request.

    `complete` is the blocking completion call (already bound to the
    user's key); it runs in a worker thread. Raises `RoutingError`.
    """
    pinned_entry: InventoryEntry | None = None
    if pinned_dc_id is not None:
        pinned_entry = inventory.entry_for_id(pinned_dc_id)
        if pinned_entry is None:
            raise RoutingError(
                404, "data_collection_id does not belong to the dashboard's project."
            )

    if pinned_type is not None and (pinned_entry is not None or pinned_type == "text"):
        # Fully pinned: nothing to route. The handler normally skips this
        # module in that case; answering here keeps the contract total.
        return RouteDecision(
            component_type=pinned_type,
            entry=None if pinned_type == "text" else pinned_entry,
            routing=RoutingInfo(source="user"),
        )

    allowed_types = allowed_types_for(inventory, pinned_type=pinned_type, pinned_entry=pinned_entry)

    # Shortcuts: a pinned type with a single fitting collection needs no model.
    if pinned_type is not None:
        if not inventory.candidates_for(pinned_type):
            raise RoutingError(
                422,
                f"No data collection in this project fits a {pinned_type} component "
                "(none of the expected collection types was found).",
            )
        single = single_candidate(inventory, pinned_type)
        if single is not None:
            scope = "on the dashboard" if single.on_dashboard else "in the project"
            return RouteDecision(
                component_type=pinned_type,
                entry=single,
                routing=RoutingInfo(
                    source="single",
                    reason=(
                        f"{single.data_collection_tag!r} is the only collection {scope} "
                        f"that fits a {pinned_type} component."
                    ),
                ),
            )
    elif pinned_entry is not None and len(allowed_types) == 1:
        # Only text can be built on it: nothing to ask.
        raise RoutingError(
            422,
            f"No component type can be built on data collection "
            f"{pinned_entry.data_collection_tag!r} (type {pinned_entry.dc_type}).",
        )

    messages = prompts.route_component_messages(
        prompt,
        inventory,
        allowed_types,
        pinned_type=pinned_type,
        pinned_dc_tag=pinned_entry.data_collection_tag if pinned_entry else None,
    )
    last_error = ""
    for attempt in range(MAX_ROUTE_ATTEMPTS):
        try:
            raw = await asyncio.to_thread(complete, messages)
        except Exception as e:  # noqa: BLE001
            raise RoutingError(502, f"LLM error: {e}") from e
        try:
            return validate_answer(
                raw,
                inventory,
                allowed_types,
                pinned_type=pinned_type,
                pinned_entry=pinned_entry,
            )
        except ValueError as e:
            last_error = str(e)
            logger.warning("component routing attempt %d rejected: %s", attempt + 1, last_error)
            messages = [
                *messages,
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        f"Your answer was rejected: {last_error}.\n"
                        "Reply with the JSON object only, using exactly one of the allowed "
                        "component types and one data_collection_tag copied from INVENTORY "
                        "(null for text)."
                    ),
                },
            ]

    raise RoutingError(
        502,
        "The assistant could not choose a component type and data collection for this "
        f"prompt: {last_error}. Pick them yourself and try again.",
    )
