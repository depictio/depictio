"""What changed between two dashboard versions.

``content_hash`` can say two versions differ; it cannot say *how*. This answers
that: which components were added, removed, moved, resized or reconfigured, and
which tabs appeared or vanished.

Pure and synchronous, like ``schema_integrity`` next door. It takes two
already-loaded snapshot payloads and touches no collection — the route resolves
and authorises them, this decides what they mean.

**The whole feature lives or dies on noise.** A diff that reports every component
as changed after a routine re-save is worse than no diff, because a reader learns
to ignore it. Two mechanisms keep that from happening, and both matter:
``_VOLATILE_COMPONENT_KEYS`` drops fields that churn without anyone editing
anything, and an emptiness-collapsing leaf comparison treats ``None``, ``""``,
``[]``, ``{}`` and *absent* as one value.
"""

from __future__ import annotations

from typing import Any

#: Component fields that change without anyone having edited the component.
#:
#: - ``last_updated`` — stamped unconditionally on every rebuild, in four places
#:   (``builder/buildMetadata.ts``, ``models/dashboards.py``, and both YAML
#:   serialisers). ``_jsonify`` normalises its *type* at capture but does not
#:   drop it, so a diff must.
#: - ``dc_config`` — a cached copy of the data collection's config, which moves
#:   whenever the collection is re-scanned (size, column specs). That is *data*
#:   drift, and ``build_compatibility_report`` already owns that dimension
#:   entirely; letting it in here marks every component on a re-ingested
#:   collection as reconfigured.
#: - ``value`` — cards persist a computed value that ``bulk_compute_cards``
#:   recalculates. A stale number is not an edit.
#:
#: ``wf_id`` and ``dc_id`` are deliberately absent: repointing a component at a
#: different collection is the single most consequential change there is.
_VOLATILE_COMPONENT_KEYS: frozenset[str] = frozenset({"last_updated", "dc_config", "value"})

#: ``cols_json`` is a per-column statistics cache — churn — *except* for the
#: ``hide`` flags, which ``TableRenderer`` reads and a user sets deliberately.
#: Projected down to those rather than dropped outright.
_COLS_JSON_KEPT_KEYS: frozenset[str] = frozenset({"hide"})

#: Tab-level fields worth reporting. A reorder is exactly a ``tab_order`` delta
#: and no component-level list would ever surface it.
_TAB_SCALAR_FIELDS: tuple[str, ...] = (
    "title",
    "subtitle",
    "tab_order",
    "tab_icon",
    "tab_icon_color",
    "icon",
    "icon_color",
    "notes_content",
)

#: react-grid-layout fields carrying user intent. ``static`` and
#: ``resizeHandles`` are excluded because ``DashboardGrid.normalizeLayout``
#: overrides them at render time, so they are pure churn from older editor
#: passes.
_LAYOUT_FIELDS: tuple[str, ...] = ("x", "y", "w", "h")

#: A code-mode figure's ``code_content`` change would otherwise ship a field
#: list the length of the file.
_MAX_CHANGED_FIELDS = 12


def strip_box_prefix(item_id: str) -> str:
    """``box-abc`` → ``abc``.

    Not cosmetic. ``upsertComponent`` writes ``i: `box-${index}` `` when it
    appends a new cell, while the editor's drag/resize path writes bare indices,
    and ``DashboardGrid`` reconciles the two at render time. A diff that skipped
    this would report every component as removed-and-re-added the first time a
    dashboard crossed that boundary.
    """
    return item_id[4:] if item_id.startswith("box-") else item_id


def _component_index(component: dict[str, Any]) -> str:
    """The id a component is known by — the same one the render endpoints match
    on and ``DashboardGrid`` stamps into the DOM, so diff ids are directly usable
    as canvas selectors."""
    return str(component.get("index", ""))


def _is_empty(value: Any) -> bool:
    """``None``, ``""``, ``[]`` and ``{}`` are all "nothing was set here"."""
    return value is None or value == "" or value == [] or value == {}


def _project_cols_json(value: Any) -> Any:
    """Keep the ``hide`` flags, discard the statistics cache around them."""
    if not isinstance(value, dict):
        return value
    projected: dict[str, Any] = {}
    for column, spec in value.items():
        if isinstance(spec, dict):
            kept = {k: v for k, v in spec.items() if k in _COLS_JSON_KEPT_KEYS}
            if kept:
                projected[str(column)] = kept
    return projected


def _comparable(component: dict[str, Any]) -> dict[str, Any]:
    """A component reduced to the fields a user could have changed."""
    result: dict[str, Any] = {}
    for key, value in component.items():
        if key in _VOLATILE_COMPONENT_KEYS:
            continue
        if key == "cols_json":
            projected = _project_cols_json(value)
            if not _is_empty(projected):
                result[key] = projected
            continue
        result[key] = value
    return result


def _diff_values(before: Any, after: Any, path: str, out: list[str]) -> None:
    """Collect dotted paths where two values differ.

    The emptiness rule is applied at every leaf, not just the top level, and it
    is the second-largest false-positive source after ``last_updated``:
    ``buildMetadata`` writes ``background_color: c.background_color || ''`` and
    ``breakdown_col: (c.breakdown_col ?? null)`` where an older save simply
    omitted the keys, so a pure re-save through a newer builder would otherwise
    mark every card reconfigured.
    """
    if _is_empty(before) and _is_empty(after):
        return

    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            _diff_values(before.get(key), after.get(key), f"{path}.{key}" if path else key, out)
        return

    if isinstance(before, list) and isinstance(after, list):
        # Positionally: `columns` and `aggregations` order is user-visible, so a
        # reorder is a real change rather than noise to normalise away.
        if len(before) != len(after):
            out.append(f"{path}.length" if path else "length")
            return
        for position, (left, right) in enumerate(zip(before, after)):
            _diff_values(left, right, f"{path}[{position}]", out)
        return

    if before != after:
        out.append(path or "value")


def changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Dotted paths that differ between two components."""
    out: list[str] = []
    _diff_values(_comparable(before), _comparable(after), "", out)
    return out


def _layout_index(tab: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{component_index: {panel, x, y, w, h}}`` across both panels.

    The two panels are read separately and tagged, so a component moved between
    them reports a ``panel`` change — which the editor supports and which a
    merged index could not express.
    """
    index: dict[str, dict[str, Any]] = {}
    for panel, field in (("left", "left_panel_layout_data"), ("right", "right_panel_layout_data")):
        for item in tab.get(field) or []:
            if not isinstance(item, dict) or "i" not in item:
                continue
            entry: dict[str, Any] = {"panel": panel}
            for key in _LAYOUT_FIELDS:
                if key in item:
                    entry[key] = item[key]
            index[strip_box_prefix(str(item["i"]))] = entry
    return index


def _tabs_by_id(tabs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Keyed the same way ``restore_dashboard_version`` pairs tabs, so the two
    cannot drift on what "the same tab" means."""
    return {str(tab.get("dashboard_id", "")): tab for tab in tabs if tab.get("dashboard_id")}


def _components_by_index(tab: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _component_index(component): component
        for component in tab.get("stored_metadata") or []
        if isinstance(component, dict) and _component_index(component)
    }


def _component_entry(
    index: str,
    tab_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    layout_before: dict[str, Any] | None,
    layout_after: dict[str, Any] | None,
    *,
    via_tab: bool = False,
) -> dict[str, Any]:
    source = after or before or {}
    entry: dict[str, Any] = {
        "index": index,
        "tab_id": tab_id,
        "component_type": source.get("component_type"),
        "title": source.get("title") or source.get("component_type"),
        "via_tab": via_tab,
        "layout_before": layout_before,
        "layout_after": layout_after,
        "moved": False,
        "resized": False,
        "modified_config": False,
        "changed_fields": [],
        "changed_fields_truncated": 0,
    }

    if before is None:
        entry["change"] = "added"
        return entry
    if after is None:
        entry["change"] = "removed"
        return entry

    fields = changed_fields(before, after)
    entry["modified_config"] = bool(fields)
    entry["changed_fields"] = fields[:_MAX_CHANGED_FIELDS]
    entry["changed_fields_truncated"] = max(0, len(fields) - _MAX_CHANGED_FIELDS)

    # A component with no layout entry on either side is not layout-comparable.
    # Cards routinely have none — `DashboardGrid` auto-places them — and must not
    # read as moved.
    if layout_before and layout_after:
        entry["moved"] = any(
            layout_before.get(k) != layout_after.get(k) for k in ("x", "y", "panel")
        )
        entry["resized"] = any(layout_before.get(k) != layout_after.get(k) for k in ("w", "h"))

    entry["change"] = (
        "modified"
        if entry["modified_config"] or entry["moved"] or entry["resized"]
        else "unchanged"
    )
    return entry


def diff_tabs(
    base_tabs: list[dict[str, Any]],
    target_tabs: list[dict[str, Any]],
    *,
    include_unchanged: bool = False,
) -> dict[str, Any]:
    """Compare two snapshot tab lists. ``base`` is older, ``target`` newer.

    ``change`` on a component is a four-value enum — added / removed / modified /
    unchanged — with ``moved``, ``resized`` and ``modified_config`` as
    qualifiers. Not a six-way enum, because a component can genuinely be moved
    *and* reconfigured in one version, and the canvas has only four treatments
    to give.
    """
    base_by_id = _tabs_by_id(base_tabs)
    target_by_id = _tabs_by_id(target_tabs)

    totals = {
        "added": 0,
        "removed": 0,
        "modified": 0,
        "unchanged": 0,
        "tabs_added": 0,
        "tabs_removed": 0,
    }
    tab_reports: list[dict[str, Any]] = []

    for tab_id in list(target_by_id) + [t for t in base_by_id if t not in target_by_id]:
        base_tab = base_by_id.get(tab_id)
        target_tab = target_by_id.get(tab_id)
        source_tab = target_tab or base_tab or {}

        if base_tab is None:
            tab_change = "added"
            totals["tabs_added"] += 1
        elif target_tab is None:
            tab_change = "removed"
            totals["tabs_removed"] += 1
        else:
            tab_change = "unchanged"

        base_components = _components_by_index(base_tab) if base_tab else {}
        target_components = _components_by_index(target_tab) if target_tab else {}
        base_layout = _layout_index(base_tab) if base_tab else {}
        target_layout = _layout_index(target_tab) if target_tab else {}

        entries: list[dict[str, Any]] = []
        for index in list(target_components) + [
            i for i in base_components if i not in target_components
        ]:
            entry = _component_entry(
                index,
                tab_id,
                base_components.get(index),
                target_components.get(index),
                base_layout.get(index),
                target_layout.get(index),
                via_tab=tab_change in ("added", "removed"),
            )
            totals[entry["change"]] = totals.get(entry["change"], 0) + 1
            if entry["change"] != "unchanged" or include_unchanged:
                entries.append(entry)

        tab_fields: list[str] = []
        if base_tab and target_tab:
            tab_fields = [
                field
                for field in _TAB_SCALAR_FIELDS
                if not (_is_empty(base_tab.get(field)) and _is_empty(target_tab.get(field)))
                and base_tab.get(field) != target_tab.get(field)
            ]
            if tab_fields or entries:
                tab_change = "changed"

        tab_reports.append(
            {
                "tab_id": tab_id,
                "title": source_tab.get("title") or "",
                "change": tab_change,
                "changed_fields": tab_fields,
                "components": entries,
            }
        )

    return {"totals": totals, "tabs": tab_reports}
