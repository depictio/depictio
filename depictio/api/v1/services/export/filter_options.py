"""Filter options for an embedded component's controls.

An external page that wants its *own* dropdown or slider — rather than an
embedded Depictio control — needs to know what to put in it. The values live
behind ``/deltatables/unique_values`` and ``/deltatables/specs``, both gated by
``get_user_or_anonymous``, which raises 401 in a normal multi-user deployment
*before* any project check runs. That is exactly the case embeds exist for, so
those routes cannot serve an embedding page.

This module reads the same data through the same helpers, and the export router
puts it behind ``get_embed_user`` + ``check_project_permission(..., "viewer")``
— the identical gate every other export route applies. The effective widening is
public projects only, same as the rest of the router.

Two shapes, because two kinds of control need different things:

* **categorical** — the sorted distinct values, for a select or a set of tabs.
* **numeric / temporal** — min and max, for a slider or a date range.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from depictio.api.v1.configs.logging_init import logger

#: Cap on distinct values returned. A select with more entries than this is not
#: a usable control anyway, and the cap keeps a high-cardinality column (sample
#: ids, feature ids) from returning a multi-megabyte manifest.
MAX_OPTIONS = 500

#: Component types whose control is driven by distinct values rather than a range.
_CATEGORICAL_TYPES = frozenset({"Select", "MultiSelect", "SegmentedControl", "TextInput"})
_RANGE_TYPES = frozenset({"Slider", "RangeSlider", "DateRangePicker", "Timeline"})


def _column_specs(specs: Any, column: str) -> dict[str, Any]:
    """Pull one column's spec block out of either shape the API returns."""
    if isinstance(specs, list):
        entry = next((e for e in specs if e.get("name") == column), None) or {}
        return entry.get("specs") or {}
    if isinstance(specs, dict):
        entry = specs.get(column) or {}
        return entry.get("specs") or entry
    return {}


async def filter_options(component: dict, current_user: Any) -> dict[str, Any] | None:
    """Describe the value universe for one interactive component.

    Returns ``None`` for a component that is not a filter, or when the lookup
    fails — a manifest that 500s because one column could not be read would be
    worse than a manifest that omits its options.
    """
    control = component.get("interactive_component_type")
    column = component.get("column_name")
    dc_id = component.get("dc_id")
    if not control or not column or not dc_id:
        return None

    if control in _CATEGORICAL_TYPES:
        return await _categorical_options(str(dc_id), str(column), control, current_user)
    if control in _RANGE_TYPES:
        return await _range_options(str(dc_id), str(column), control, current_user)
    return None


async def _categorical_options(
    dc_id: str, column: str, control: str, current_user: Any
) -> dict[str, Any] | None:
    # Delegates to the same handler the viewer's MultiSelect uses rather than
    # re-reading the Delta table. That handler already carries the cases this
    # would otherwise have to duplicate — MultiQC collections have no Delta
    # table and source their sample list from ingested metadata — and a second
    # implementation would drift from it.
    from depictio.api.v1.endpoints.deltatables_endpoints.routes import (
        get_unique_values,
    )
    from depictio.models.models.base import PyObjectId

    try:
        # PyObjectId, not str. FastAPI coerces the path parameter on the real
        # route; calling the handler directly skips that, and the Mongo query
        # `{"data_collection_id": <str>}` matches nothing — which surfaces as a
        # misleading "No DeltaTable found" rather than a type error.
        result = await get_unique_values(
            data_collection_id=PyObjectId(dc_id),
            column=column,
            limit=MAX_OPTIONS + 1,
            current_user=current_user,
        )
        values = (result or {}).get("values") or []
    except HTTPException as exc:
        # A DC with no materialised Delta table (or one this user cannot read)
        # must degrade to "no options", not fail the whole manifest. The
        # HTTPException would otherwise propagate straight out of the route.
        logger.info("export: no options for dc=%s column=%s: %s", dc_id, column, exc.detail)
        return None
    except Exception as exc:
        logger.warning("export: options lookup failed for dc=%s column=%s: %s", dc_id, column, exc)
        return None

    # Already stringified by that handler, which matches `add_filter` casting
    # the column to Utf8 before `is_in`. Returning ints would let a caller send
    # ints that silently match nothing.
    cleaned = [str(v) for v in values if v is not None]
    return {
        "kind": "categorical",
        "control": control,
        "values": cleaned[:MAX_OPTIONS],
        "truncated": len(cleaned) > MAX_OPTIONS,
        "total": len(cleaned),
    }


async def _range_options(
    dc_id: str, column: str, control: str, current_user: Any
) -> dict[str, Any] | None:
    from depictio.api.v1.endpoints.deltatables_endpoints.routes import specs as fetch_specs
    from depictio.models.models.base import PyObjectId

    try:
        specs = await fetch_specs(
            data_collection_id=PyObjectId(dc_id),
            current_user=current_user,  # type: ignore[arg-type]
        )
    except HTTPException as exc:
        logger.info("export: no range for dc=%s column=%s: %s", dc_id, column, exc.detail)
        return None
    except Exception as exc:
        logger.warning("export: specs lookup failed for dc=%s: %s", dc_id, exc)
        return None

    block = _column_specs(specs, column)
    minimum, maximum = block.get("min"), block.get("max")
    if minimum is None or maximum is None:
        return None
    return {"kind": "range", "control": control, "min": minimum, "max": maximum}
