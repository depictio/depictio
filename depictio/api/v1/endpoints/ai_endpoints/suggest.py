"""Typed component suggestions: "what would you add to this dashboard?"

Backs ``POST /ai/suggest-components``. Two sources feed one list:

* ranked candidates, built deterministically from the data: ``table``
  from the stored column specs, and ``advanced_viz`` from the viz-kind
  ranker when the request pins that type;
* LLM candidates, one completion proposing the other types (card,
  interactive, figure, map, multiqc, image, text, and advanced_viz when
  the type is open) inside the legal spaces this module derives from the
  inventory (column types x aggregations, column types x widgets, MultiQC
  modules and plots, coordinate columns, ranked viz kinds with their
  config keys).

A ranked advanced_viz is never surfaced on its own when the type is open:
dtype matching finds a kind whose roles the columns can fill, not a kind
that makes sense for the dataset (bill depth is a fine "depth" column
for a rarefaction curve, dtype-wise). The ranker's candidates become the
model's legal space instead, so the model judges the fit and
``validate_single`` still guards the shape.

Every candidate, whatever its source, goes through
``component_yaml.validate_single`` (the CLI's offline validator); what
fails is dropped with a warning, never repaired.

The pure helpers are module-level functions so they can be tested without
a dashboard. The data loaders are imported as module attributes so tests
can substitute them: ``suggest._get_data_collection_polars_schema``,
``suggest.fetch_multiqc_builder_options_sync`` and
``suggest.suggest_viz_kinds``. The inventory / dashboard / data-context
builders are passed in by the route (it resolves them from its own module
globals, which is where the route tests patch them).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import yaml
from fastapi import HTTPException
from pydantic import ValidationError

from depictio.api.v1.endpoints.ai_endpoints import (
    component_yaml,
    llm_client,
    prompts,
    routing,
)
from depictio.api.v1.endpoints.ai_endpoints.code_gen import figure_python_code
from depictio.api.v1.endpoints.ai_endpoints.context import (
    _LAT_NAME_RE,
    _LON_NAME_RE,
    _NUMERIC_DTYPE_RE,
    TABLE_LIKE_DC_TYPES,
    DashboardContext,
    DataContext,
    InventoryEntry,
    ProjectInventory,
    column_type_for,
    dc_has_coordinates,
)
from depictio.api.v1.endpoints.ai_endpoints.dashboard_validate import schema_error
from depictio.api.v1.endpoints.ai_endpoints.schemas import (
    ComponentSuggestion,
    ComponentType,
    SuggestComponentsRequest,
    SuggestComponentsResponse,
)
from depictio.api.v1.endpoints.datacollections_endpoints.utils import (
    _get_data_collection_polars_schema,
)
from depictio.api.v1.endpoints.multiqc_endpoints.utils import (
    fetch_multiqc_builder_options_sync,
)
from depictio.models.components.advanced_viz.catalog import role_config_key
from depictio.models.components.advanced_viz.schemas import (
    KIND_METADATA,
    RECOMMENDED_SCORE,
    role_dtype_specs,
    suggest_viz_kinds,
)
from depictio.models.components.constants import (
    AGGREGATION_COMPATIBILITY,
    ALLOWED_VISUALIZATIONS,
    INTERACTIVE_COMPATIBILITY,
)

logger = logging.getLogger(__name__)

# How many collections one request describes, how many of them get sample
# rows (a delta read each), and how many ranked advanced_viz per collection.
MAX_SUGGEST_COLLECTIONS = 4
MAX_SAMPLED_COLLECTIONS = 2
MAX_RANKED_PER_DC = 2
# The deterministic table shows the first columns on a short page.
MAX_TABLE_COLUMNS = 8
TABLE_PAGE_SIZE = 10
# MultiQC module lines per collection in the prompt.
MAX_MULTIQC_LINES = 12
# Ranked viz kinds offered to the model per collection (Auto mode).
MAX_ADVANCED_VIZ_SPACE_KINDS = 4

# Types built here when pinned: no LLM call at all. With the type open,
# table stays ranked and advanced_viz is offered to the model inside the
# ranked legal space (see `advanced_viz_space_lines`).
RANKED_TYPES: frozenset[str] = frozenset({"advanced_viz", "table"})

InventoryBuilder = Callable[..., Awaitable[ProjectInventory]]
DashboardContextBuilder = Callable[[str, Any], Awaitable[tuple[DashboardContext, str | None]]]
DataContextBuilder = Callable[..., Awaitable[DataContext]]


# ---------------------------------------------------------------------------
# Column types and legal spaces
# ---------------------------------------------------------------------------


def columns_by_type(entry: InventoryEntry) -> dict[str, list[str]]:
    """column_type -> column names of the collection, inventory order; unmapped dtypes skipped."""
    grouped: dict[str, list[str]] = {}
    for name, dtype in entry.columns:
        column_type = column_type_for(dtype)
        if column_type is not None:
            grouped.setdefault(column_type, []).append(name)
    return grouped


def _typed_space(
    entry: InventoryEntry, compatibility: dict[str, list[str]]
) -> dict[str, tuple[list[str], list[str]]]:
    return {
        column_type: (columns, list(compatibility[column_type]))
        for column_type, columns in columns_by_type(entry).items()
        if compatibility.get(column_type)
    }


def card_space(entry: InventoryEntry) -> dict[str, tuple[list[str], list[str]]]:
    """column_type -> (columns of that type, aggregations a card may apply to them)."""
    return _typed_space(entry, AGGREGATION_COMPATIBILITY)


def interactive_space(entry: InventoryEntry) -> dict[str, tuple[list[str], list[str]]]:
    """column_type -> (columns, interactive_component_type values); types with no widget are left out."""
    return _typed_space(entry, INTERACTIVE_COMPATIBILITY)


def coordinate_columns_for(entry: InventoryEntry) -> tuple[str, str] | None:
    """The (lat, lon) columns a scatter_map on this collection would bind.

    Explicit hints from the collection config win; otherwise the same name
    heuristic as `context.dc_has_coordinates` picks the first match each.
    """
    if entry.coordinate_columns is not None:
        return entry.coordinate_columns

    def numeric(dtype: str) -> bool:
        return not dtype or bool(_NUMERIC_DTYPE_RE.search(dtype))

    lat = next((n for n, d in entry.columns if _LAT_NAME_RE.search(n) and numeric(d)), None)
    lon = next((n for n, d in entry.columns if _LON_NAME_RE.search(n) and numeric(d)), None)
    return (lat, lon) if lat and lon else None


def _multiqc_lines(options: dict[str, Any]) -> list[str]:
    plots: dict[str, list[str]] = options.get("plots") or {}
    modules: list[str] = list(options.get("modules") or sorted(plots))
    shown = modules if len(modules) <= MAX_MULTIQC_LINES else modules[: MAX_MULTIQC_LINES - 1]
    lines: list[str] = []
    for module in shown:
        names = list(plots.get(module) or [])
        if module == "general_stats" and not names:
            names = ["general_stats"]
        if names:
            lines.append(
                f"multiqc: selected_module {module}; selected_plot in {{{', '.join(names)}}}"
            )
        else:
            lines.append(f"multiqc: selected_module {module}")
    if len(shown) < len(modules):
        lines.append(f"multiqc: (+{len(modules) - len(shown)} more modules not listed)")
    return lines


def advanced_viz_space_lines(candidates: list[dict[str, Any]]) -> list[str]:
    """The advanced_viz legal space of one collection, from `advanced_viz_components`.

    One line per ranked kind (at most MAX_ADVANCED_VIZ_SPACE_KINDS) naming
    the exact config keys and the best column for each required role, then
    the shape rule. The model decides whether a kind is semantically apt;
    the keys keep whatever it emits inside what the config model accepts.
    """
    lines: list[str] = []
    for candidate in candidates[:MAX_ADVANCED_VIZ_SPACE_KINDS]:
        keys = ", ".join(
            f"{key}={column}" for key, column in candidate["config"].items() if key != "viz_kind"
        )
        lines.append(f'advanced_viz kind "{candidate["viz_kind"]}": config keys {keys}')
    if lines:
        lines.append(
            "advanced_viz: the component carries viz_kind and a config object with viz_kind "
            "and exactly the keys listed for that kind (extra keys are rejected)"
        )
    return lines


def space_lines(
    entry: InventoryEntry,
    llm_types: list[ComponentType],
    multiqc_options: dict[str, Any] | None = None,
    *,
    has_coords: bool = False,
    advanced_viz_candidates: list[dict[str, Any]] | None = None,
) -> list[str]:
    """The legal component spaces of one collection, one line per (type, column_type).

    `llm_types` is already narrowed to the types this collection can back.
    The lines go into the suggestion prompt so the model picks aggregations,
    widgets and columns the lite validators accept, instead of discovering
    the compatibility tables by rejection. `advanced_viz_candidates` is the
    output of `advanced_viz_components` for this collection (Auto mode).
    """
    lines: list[str] = []
    if "card" in llm_types:
        for column_type, (columns, aggregations) in card_space(entry).items():
            lines.append(
                f"card: column_type {column_type} for {', '.join(columns)}; "
                f"aggregation in {{{', '.join(aggregations)}}}"
            )
    if "interactive" in llm_types:
        for column_type, (columns, widgets) in interactive_space(entry).items():
            lines.append(
                f"interactive: column_type {column_type} for {', '.join(columns)}; "
                f"interactive_component_type in {{{', '.join(widgets)}}}"
            )
    if "figure" in llm_types and entry.columns:
        names = ", ".join(name for name, _ in entry.columns)
        lines.append(
            f"figure: visu_type in {{{', '.join(ALLOWED_VISUALIZATIONS)}}}; "
            f"dict_kwargs columns from {names}"
        )
    if "image" in llm_types:
        strings = columns_by_type(entry).get("object", [])
        if strings:
            lines.append(f"image: image_column in {{{', '.join(strings)}}}")
        else:
            lines.append("image: image_column is the collection's image-path column")
    if "map" in llm_types and has_coords:
        coords = coordinate_columns_for(entry)
        if coords:
            lines.append(
                f"map: map_type scatter_map with lat_column {coords[0]} and lon_column {coords[1]}"
            )
    if "multiqc" in llm_types and multiqc_options:
        lines.extend(_multiqc_lines(multiqc_options))
    if "advanced_viz" in llm_types and advanced_viz_candidates:
        lines.extend(advanced_viz_space_lines(advanced_viz_candidates))
    return lines


# ---------------------------------------------------------------------------
# Ranked (deterministic) candidates
# ---------------------------------------------------------------------------


def table_component(entry: InventoryEntry) -> dict[str, Any]:
    """A table over the first MAX_TABLE_COLUMNS columns of the collection (not yet validated)."""
    return {
        "component_type": "table",
        "workflow_tag": entry.workflow_tag or "",
        "data_collection_tag": entry.data_collection_tag,
        "title": f"Browse {entry.data_collection_tag}",
        "columns": [name for name, _ in entry.columns[:MAX_TABLE_COLUMNS]],
        "page_size": TABLE_PAGE_SIZE,
    }


def viz_kind_label(kind: str) -> str:
    meta = KIND_METADATA.get(kind) or {}
    return str(meta.get("label") or kind.replace("_", " "))


def advanced_viz_components(entry: InventoryEntry, schema: dict[str, str]) -> list[dict[str, Any]]:
    """Candidate advanced_viz components for a collection, best fit first (not yet validated).

    One per viz kind the ranker recommends for the polars schema (score at
    or above RECOMMENDED_SCORE and every required role satisfiable). Each
    required role is bound to the ranker's best column under the config key
    the renderer reads (`role_config_key` covers the renamed ones). Kinds
    whose roles matched on dtype alone (weak) sort after the kinds with a
    name match, so a schema that names its columns leads with the plot it
    was made for.
    """
    ranked = suggest_viz_kinds(schema, dc_type=entry.dc_type)
    picks = [s for s in ranked if s.score >= RECOMMENDED_SCORE and not s.unmet_roles]
    picks.sort(key=lambda s: bool(s.weak_roles))  # stable: keeps the ranker's order per half
    out: list[dict[str, Any]] = []
    for suggestion in picks:
        kind = suggestion.viz_kind
        config: dict[str, Any] = {"viz_kind": kind}
        bound = True
        for role, spec in role_dtype_specs(kind).items():
            if not spec["required"]:
                continue
            candidates = suggestion.role_candidates.get(role) or []
            if not candidates:
                bound = False
                break
            config[role_config_key(kind, role)] = candidates[0]
        if not bound:
            continue
        out.append(
            {
                "component_type": "advanced_viz",
                "workflow_tag": entry.workflow_tag or "",
                "data_collection_tag": entry.data_collection_tag,
                "title": f"{viz_kind_label(kind)} of {entry.data_collection_tag}",
                "viz_kind": kind,
                "config": config,
            }
        )
    return out


def _log_dropped(component: dict[str, Any], finding: str) -> None:
    """Say which candidate was dropped and why: it has no repair round to fix it."""
    logger.warning(
        "suggest-components: dropped %s candidate %r: %s",
        component.get("component_type"),
        component.get("title"),
        finding,
    )


def validate_candidate(
    component: dict[str, Any], ctx: DataContext | None = None
) -> dict[str, Any] | None:
    """Run one candidate through the CLI validator; None (logged) when it fails.

    The dict is dumped to YAML first so every candidate, LLM or ranked,
    takes exactly the path `depictio-cli dashboard import` takes.

    With a `ctx`, the candidate is also checked against the collection's real
    columns (`schema_error`), the check the generator runs and this route used
    to skip: an `average` on a String column parses perfectly and is still not
    a card anyone can render. A suggestion has no repair round, so a candidate
    that fails is dropped like one that fails the grammar; the caller keeps
    whatever survives.
    """
    try:
        text = yaml.safe_dump(component, sort_keys=False)
        parsed = component_yaml.validate_single(text)
    except (ValidationError, ValueError, yaml.YAMLError) as e:
        _log_dropped(component, component_yaml.format_validation_error_for_llm(e))
        return None
    if ctx is None:
        return parsed
    try:
        finding = schema_error(parsed, ctx)
    except (ValidationError, ValueError) as e:  # pragma: no cover, defensive
        finding = component_yaml.format_validation_error_for_llm(e)
    if finding:
        _log_dropped(component, finding)
        return None
    return parsed


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


def _suggestion(
    entry: InventoryEntry | None,
    component: dict[str, Any],
    *,
    origin: str,
    rationale: str,
    title: str | None = None,
) -> ComponentSuggestion:
    component_type = component["component_type"]
    code: str | None = None
    if component_type == "figure":
        if component.get("mode") == "code":
            code = component.get("code_content") or None
        else:
            code = figure_python_code(
                str(component.get("visu_type") or "scatter"), component.get("dict_kwargs") or {}
            )
    tag = entry.data_collection_tag if entry else None
    return ComponentSuggestion(
        component_type=component_type,
        data_collection_id=entry.data_collection_id if entry else None,
        data_collection_tag=tag,
        workflow_id=entry.workflow_id if entry else None,
        title=title or str(component.get("title") or "").strip() or f"{component_type} on {tag}",
        rationale=rationale,
        component=component,
        code=code,
        origin=origin,  # type: ignore[arg-type]
    )


def _advanced_viz_rationale(candidate: dict[str, Any], entry: InventoryEntry) -> str:
    """Why a ranked advanced_viz was proposed: the kind and the roles its columns fill."""
    kind = viz_kind_label(str(candidate["viz_kind"])).lower()
    bindings = ", ".join(
        f"{key.removesuffix('_col').removesuffix('_column').replace('_', ' ')}: {column}"
        for key, column in candidate["config"].items()
        if key != "viz_kind"
    )
    return f"The columns of {entry.data_collection_tag} fill every role of a {kind} ({bindings})."


def _fill_column_type(component: dict[str, Any], entry: InventoryEntry) -> None:
    """Give a card / interactive its column_type from the inventory when the model left it out.

    Without it the lite validator skips the compatibility check and an
    illegal aggregation only fails at render time.
    """
    if component.get("column_type"):
        return
    column = component.get("column_name")
    dtype = next((d for name, d in entry.columns if name == column), None)
    column_type = column_type_for(dtype)
    if column_type:
        component["column_type"] = column_type


def llm_suggestions(
    parsed: Any,
    inventory: ProjectInventory,
    llm_types: list[ComponentType],
    targets: list[InventoryEntry],
    contexts: dict[str, DataContext] | None = None,
) -> tuple[list[ComponentSuggestion], int]:
    """Turn the model's JSON into validated suggestions. Returns (kept, dropped).

    Per item: the type is forced from the item and must be one of
    `llm_types`; the tags are filled from the inventory entry the item
    names, which must be one of the `targets` the prompt described (an
    unknown or out-of-scope tag drops the item, except for text, which has
    no collection); the component is validated like any other candidate,
    against `contexts[<dc id>]` when the run sampled that collection.
    """
    items = parsed.get("suggestions") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return [], 0
    in_scope = {e.data_collection_id for e in targets}

    kept: list[ComponentSuggestion] = []
    dropped = 0
    for item in items:
        if not isinstance(item, dict):
            dropped += 1
            continue
        raw_component = item.get("component")
        component: dict[str, Any] = dict(raw_component) if isinstance(raw_component, dict) else {}
        raw_type = item.get("component_type") or component.get("component_type") or ""
        component_type = str(raw_type).strip().lower()
        if component_type not in llm_types or not component:
            logger.warning(
                "suggest-components: dropped item with type %r (allowed: %s)",
                component_type,
                ", ".join(llm_types),
            )
            dropped += 1
            continue
        component["component_type"] = component_type

        title = str(item.get("title") or component.get("title") or "").strip()
        if title:
            component["title"] = title

        entry: InventoryEntry | None = None
        if component_type == "text":
            component.pop("workflow_tag", None)
            component.pop("data_collection_tag", None)
        else:
            tag = item.get("data_collection_tag") or component.get("data_collection_tag")
            entry = inventory.entry_for_tag(str(tag) if tag is not None else None)
            if entry is None or entry.data_collection_id not in in_scope:
                logger.warning(
                    "suggest-components: dropped %r, tag %r is not one of the described collections",
                    title,
                    tag,
                )
                dropped += 1
                continue
            if entry not in inventory.candidates_for(component_type):
                logger.warning(
                    "suggest-components: dropped %r, %s cannot back a %s",
                    title,
                    entry.data_collection_tag,
                    component_type,
                )
                dropped += 1
                continue
            component["workflow_tag"] = entry.workflow_tag or ""
            component["data_collection_tag"] = entry.data_collection_tag
            if component_type in ("card", "interactive"):
                _fill_column_type(component, entry)
            if component_type == "advanced_viz":
                # config.viz_kind must mirror viz_kind; a model that sets
                # only the top-level one is not worth a rejection.
                config = component.get("config")
                if isinstance(config, dict) and component.get("viz_kind"):
                    component["config"] = {"viz_kind": component["viz_kind"], **config}

        # None for text, and for a collection this run never sampled: the
        # column check has nothing to read and the candidate stands on the
        # grammar alone.
        ctx = (contexts or {}).get(entry.data_collection_id) if entry is not None else None
        validated = validate_candidate(component, ctx)
        if validated is None:
            dropped += 1
            continue
        rationale = " ".join(str(item.get("rationale") or "").split())
        kept.append(
            _suggestion(entry, validated, origin="llm", rationale=rationale, title=title or None)
        )
    return kept, dropped


def merge(
    ranked: list[ComponentSuggestion],
    llm: list[ComponentSuggestion],
    n: int,
    pinned_type: ComponentType | None,
) -> list[ComponentSuggestion]:
    """Order the two candidate lists, dedupe, cap at `n`.

    Pinned to a ranked type: the ranked list is the answer. Otherwise the
    model's items come first and ranked tables fill what room is left. No
    slot is reserved for a ranked advanced_viz: with the type open, the
    model proposes one (or not) from the legal space it was shown. Items
    are deduplicated on (type, collection, title).
    """
    if pinned_type in RANKED_TYPES:
        ordered = list(ranked)
    else:
        tables = [s for s in ranked if s.component_type == "table"]
        ordered = [*llm, *tables]

    out: list[ComponentSuggestion] = []
    seen: set[tuple[str, str | None, str]] = set()
    for s in ordered:
        key = (s.component_type, s.data_collection_id, " ".join(s.title.lower().split()))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _fits(inventory: ProjectInventory, entry: InventoryEntry, component_type: str) -> bool:
    return entry in inventory.candidates_for(component_type)


def _targets(
    inventory: ProjectInventory,
    allowed: list[ComponentType],
    *,
    pinned_type: ComponentType | None,
    pinned_entry: InventoryEntry | None,
) -> list[InventoryEntry]:
    """The collections one request describes: on-dashboard first, capped.

    A pinned collection is the only target; a pinned type narrows the pool
    to the collections that back it (text needs none); with everything
    open, every collection that backs at least one allowed data type.
    """
    if pinned_type == "text":
        pool: list[InventoryEntry] = []
    elif pinned_entry is not None:
        pool = [pinned_entry]
    elif pinned_type is not None:
        pool = inventory.candidates_for(pinned_type)
    else:
        data_types = [t for t in allowed if t != "text"]
        pool = [e for e in inventory.entries if any(_fits(inventory, e, t) for t in data_types)]
    return sorted(pool, key=lambda e: not e.on_dashboard)[:MAX_SUGGEST_COLLECTIONS]


async def _advanced_viz_candidates(
    entry: InventoryEntry, user: Any, ctx: DataContext | None
) -> list[dict[str, Any]]:
    """Ranked advanced_viz candidates of a collection, [] when no schema is available.

    The schema comes from the delta metadata, falling back to the columns of
    the sampled context when that read fails or comes back empty.
    """
    schema: dict[str, str] = {}
    try:
        schema = dict(
            await _get_data_collection_polars_schema(entry.data_collection_id, user) or {}
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "suggest-components: polars schema unavailable for %s: %s", entry.data_collection_tag, e
        )
    if not schema and ctx is not None:
        schema = {c.name: c.dtype for c in ctx.columns}
    return advanced_viz_components(entry, schema) if schema else []


async def _ranked(
    inventory: ProjectInventory,
    dashboard_ctx: DashboardContext,
    targets: list[InventoryEntry],
    contexts: dict[str, DataContext],
    allowed: list[ComponentType],
    user: Any,
    *,
    pinned_type: ComponentType | None,
) -> list[ComponentSuggestion]:
    """Deterministic suggestions: tables when allowed, advanced_viz only when pinned."""
    ranked: list[ComponentSuggestion] = []
    if pinned_type == "advanced_viz":
        for entry in targets:
            if not _fits(inventory, entry, "advanced_viz"):
                continue
            candidates = await _advanced_viz_candidates(
                entry, user, contexts.get(entry.data_collection_id)
            )
            kept = 0
            for candidate in candidates:
                if kept >= MAX_RANKED_PER_DC:
                    break
                validated = await asyncio.to_thread(
                    validate_candidate, candidate, contexts.get(entry.data_collection_id)
                )
                if validated is None:
                    continue
                kept += 1
                ranked.append(
                    _suggestion(
                        entry,
                        validated,
                        origin="ranked",
                        rationale=_advanced_viz_rationale(candidate, entry),
                    )
                )
    if "table" in allowed:
        tabled = {
            c.dc_id for c in dashboard_ctx.components if (c.component_type or "").lower() == "table"
        }
        for entry in targets:
            if (
                not _fits(inventory, entry, "table")
                or entry.data_collection_id in tabled
                or not entry.columns
            ):
                continue
            validated = await asyncio.to_thread(
                validate_candidate, table_component(entry), contexts.get(entry.data_collection_id)
            )
            if validated is not None:
                ranked.append(
                    _suggestion(
                        entry,
                        validated,
                        origin="ranked",
                        rationale=(
                            f"The rows of {entry.data_collection_tag} with sorting and filtering, "
                            "so the records behind the other tiles stay reachable."
                        ),
                    )
                )
    return ranked


async def _spaces(
    inventory: ProjectInventory,
    targets: list[InventoryEntry],
    llm_types: list[ComponentType],
    contexts: dict[str, DataContext],
    user: Any,
) -> dict[str, list[str]]:
    """Legal space lines per target collection for the prompt."""
    spaces: dict[str, list[str]] = {}
    for entry in targets:
        entry_types = [t for t in llm_types if t != "text" and _fits(inventory, entry, t)]
        advanced_viz_candidates: list[dict[str, Any]] | None = None
        if "advanced_viz" in entry_types:
            advanced_viz_candidates = await _advanced_viz_candidates(
                entry, user, contexts.get(entry.data_collection_id)
            )
        multiqc_options: dict[str, Any] | None = None
        if "multiqc" in entry_types:
            try:
                multiqc_options = await asyncio.to_thread(
                    fetch_multiqc_builder_options_sync, entry.data_collection_id
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "suggest-components: MultiQC options unavailable for %s: %s",
                    entry.data_collection_tag,
                    e,
                )
        spaces[entry.data_collection_id] = space_lines(
            entry,
            entry_types,
            multiqc_options,
            has_coords=dc_has_coordinates(entry),
            advanced_viz_candidates=advanced_viz_candidates,
        )
    return spaces


def llm_types_for(
    allowed: list[ComponentType], pinned_type: ComponentType | None
) -> list[ComponentType]:
    """The types the model is asked for.

    Type open: every allowed type but table (advanced_viz included, inside
    its ranked legal space). Pinned to a ranked type: none, no LLM call.
    Pinned to anything else: that type alone.
    """
    if pinned_type is None:
        return [t for t in allowed if t != "table"]
    if pinned_type in RANKED_TYPES:
        return []
    return [pinned_type]


async def _completion_json(
    messages: list[dict], user_api_key: str | None
) -> tuple[Any, str | None]:
    """One LLM call parsed leniently: (parsed JSON, None), or (None, why it failed)."""
    try:
        raw = await asyncio.to_thread(llm_client.completion, messages, user_api_key=user_api_key)
    except Exception as e:  # noqa: BLE001
        return None, f"LLM call failed: {e}"
    try:
        return routing._parse_json_lenient(raw), None
    except Exception as e:  # noqa: BLE001
        return None, f"LLM returned invalid JSON: {e}"


async def suggest_components(
    body: SuggestComponentsRequest,
    user: Any,
    *,
    user_api_key: str | None,
    build_inventory: InventoryBuilder,
    build_dashboard_ctx: DashboardContextBuilder,
    build_data_ctx: DataContextBuilder,
) -> SuggestComponentsResponse:
    """Propose up to `body.n` components for the dashboard. Raises HTTPException.

    404 for an unknown dashboard or a pinned collection outside its project,
    403 without project permission (both from the builders), 422 when a
    pinned type has no fitting collection (or the pinned collection cannot
    back it), 502 when nothing usable came out of either source.
    """
    pinned_type = body.component_type
    inventory = await build_inventory(
        body.dashboard_id,
        user,
        prioritize=[body.data_collection_id] if body.data_collection_id else None,
    )
    dashboard_ctx, _ = await build_dashboard_ctx(body.dashboard_id, user)

    pinned_entry: InventoryEntry | None = None
    if body.data_collection_id:
        pinned_entry = inventory.entry_for_id(body.data_collection_id)
        if pinned_entry is None:
            raise HTTPException(
                status_code=404,
                detail="data_collection_id does not belong to the dashboard's project.",
            )

    fitting = routing.allowed_types_for(inventory, pinned_type=None, pinned_entry=pinned_entry)
    if pinned_type is not None:
        if pinned_type not in fitting:
            if pinned_entry is not None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"data collection {pinned_entry.data_collection_tag!r} "
                        f"(type {pinned_entry.dc_type}) cannot back a {pinned_type} component."
                    ),
                )
            raise HTTPException(
                status_code=422,
                detail=(
                    f"No data collection in this project fits a {pinned_type} component "
                    "(none of the expected collection types was found)."
                ),
            )
        allowed: list[ComponentType] = [pinned_type]
    else:
        if pinned_entry is not None and fitting == ["text"]:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"No component type can be built on data collection "
                    f"{pinned_entry.data_collection_tag!r} (type {pinned_entry.dc_type})."
                ),
            )
        allowed = fitting

    targets = _targets(inventory, allowed, pinned_type=pinned_type, pinned_entry=pinned_entry)
    llm_types = llm_types_for(allowed, pinned_type)

    # Sample rows are for the model; the ranked path reads schemas only.
    contexts: dict[str, DataContext] = {}
    if llm_types:
        for entry in targets:
            if len(contexts) >= MAX_SAMPLED_COLLECTIONS:
                break
            if (entry.dc_type or "").lower() not in TABLE_LIKE_DC_TYPES:
                continue
            try:
                contexts[entry.data_collection_id] = await build_data_ctx(
                    entry.data_collection_id, user
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "suggest-components: no data context for %s: %s", entry.data_collection_tag, e
                )

    ranked = await _ranked(
        inventory, dashboard_ctx, targets, contexts, allowed, user, pinned_type=pinned_type
    )

    llm_items: list[ComponentSuggestion] = []
    llm_error: str | None = None
    if llm_types:
        spaces_by_dc = await _spaces(inventory, targets, llm_types, contexts, user)
        messages = prompts.suggest_components_messages(
            targets, contexts, dashboard_ctx, llm_types, spaces_by_dc, body.n
        )
        parsed, llm_error = await _completion_json(messages, user_api_key)
        if llm_error is None:
            llm_items, dropped = await asyncio.to_thread(
                llm_suggestions, parsed, inventory, llm_types, targets, contexts
            )
            if dropped and not llm_items:
                llm_error = "none of the assistant's suggestions passed validation"
        if llm_error:
            logger.warning("suggest-components: %s", llm_error)

    result = merge(ranked, llm_items, body.n, pinned_type)
    if not result:
        if llm_error:
            raise HTTPException(status_code=502, detail=f"LLM error: {llm_error}")
        raise HTTPException(
            status_code=502,
            detail="No usable suggestion could be built for this dashboard.",
        )
    warnings = [f"{llm_error}; showing ranked suggestions only"] if llm_error else []
    return SuggestComponentsResponse(suggestions=result, warnings=warnings)
