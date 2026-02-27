"""
Interactive Component - Interactivity System

This module handles the core interactivity system:
- Store definition for interactive component values
- Callback to aggregate values from all interactive components
- Lightweight store (values + indexes only, no metadata)
- Global filter promote/demote (cross-tab filtering)

The store is consumed by passive components (cards, figures, tables) to apply filters.
"""

from typing import Any

import dash
import httpx
from dash import Input, Output, State, dcc


def get_interactive_stores():
    """
    Return interactive filtering stores.

    Returns:
        list: List of dcc.Store components for interactive filtering system
    """
    return [
        dcc.Store(
            id="interactive-values-store",
            storage_type="session",
            data={},
        ),
    ]


def register_store_update_callback(app):
    """
    Register callback to aggregate interactive component values.

    This is a server-side callback because:
    - Clientside dash.ALL doesn't work with async-rendered components
    - Server-side re-evaluates dash.ALL on every execution
    - Performance is acceptable (~10-50ms for lightweight aggregation)

    The store contains ONLY values and indexes (no metadata) to keep it minimal.

    OPTIMIZATION: Intelligent idempotency tracking prevents redundant updates when:
    - All values are None (initial page load - components not yet rendered)
    - Values are identical to previous state (no user interaction occurred)

    RESET DETECTION: Detects reset actions by state transition - if previous values
    were non-default and current values are all default, that's a reset (not init).

    Args:
        app: Dash application instance
    """

    @app.callback(
        Output("interactive-values-store", "data"),
        Input({"type": "interactive-component-value", "index": dash.ALL}, "value"),
        State({"type": "interactive-component-value", "index": dash.ALL}, "id"),
        State("interactive-values-store", "data"),
        State({"type": "interactive-stored-metadata", "index": dash.ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": dash.ALL}, "id"),
        prevent_initial_call=False,
    )
    def update_interactive_values_store(
        values,
        ids,
        previous_store_data,
        metadata_list,
        metadata_ids,
    ):
        """
        Aggregate interactive component values into lightweight session store.

        Store structure (minimal):
        {
            "interactive_components_values": [
                {"index": "component-uuid", "value": [4.3, 7.9]},
                {"index": "component-uuid-2", "value": "setosa"},
                ...
            ]
        }

        Args:
            values: List of component values
            ids: List of component IDs
            previous_store_data: Previous store state for idempotency check

        Returns:
            dict: Aggregated values with indexes
        """
        # ⭐ OPTIMIZATION DISABLED: "All at defaults" check removed
        # REASON: This optimization blocked legitimate reset actions - when users clicked "Reset",
        # filters returned to defaults but cards didn't refresh because this check prevented
        # the store update. The "values unchanged" check below is sufficient for optimization.
        # REMOVED: Lines that checked if all values are at defaults and blocked store updates
        # SEE: Git history for original implementation if needed

        # # ⭐ RESET DETECTION: Check if callback was triggered by reset button
        # # If so, bypass optimization checks to ensure cards refresh
        # triggered_by_reset = False
        # if dash.callback_context.triggered:
        #     trigger_id = dash.callback_context.triggered[0]["prop_id"]
        #     if (
        #         "reset-selection-graph-button" in trigger_id
        #         or "reset-all-filters-button" in trigger_id
        #     ):
        #         triggered_by_reset = True
        #             f"🔄 RESET TRIGGER: Store update triggered by reset button: {trigger_id}"
        #         )
        #
        # # ⭐ OPTIMIZATION: Check if all values are at defaults (prevents spurious card re-renders)
        # # Trigger when:
        # # 1. We have all interactive component values (metadata count == value count)
        # # 2. Previous store exists (not the very first render ever)
        # # 3. NOT triggered by reset button (reset should always update cards)
        # # This prevents store updates when components render with default values,
        # # which in turn prevents patch_card_with_filters from firing unnecessarily
        # optimization_check_triggered = (
        #     not triggered_by_reset
        #     and len(values) > 0
        #     and metadata_list
        #     and len(metadata_list) == len(values)
        #     and previous_store_data is not None
        #     and "interactive_components_values" in previous_store_data
        # )
        # if optimization_check_triggered:
        #     # Create metadata lookup by index
        #     metadata_by_index = {}
        #     try:
        #         for i, meta_id in enumerate(metadata_ids):
        #             if i < len(metadata_list) and metadata_list[i]:
        #                 metadata_by_index[meta_id["index"]] = metadata_list[i]
        #     except Exception as e:
        #         # Continue with normal processing if metadata lookup fails
        #
        #     if metadata_by_index:
        #         # Check if all values are at their defaults
        #         all_at_defaults = True
        #         for i, value in enumerate(values):
        #             if i >= len(ids):
        #                 continue
        #
        #             component_index = ids[i]["index"]
        #             metadata = metadata_by_index.get(component_index)
        #
        #             if not metadata or "default_state" not in metadata:
        #                 all_at_defaults = False
        #                 break
        #
        #             default_state = metadata.get("default_state", {})
        #             is_at_default = False
        #
        #             # Check based on component type
        #             comp_type = default_state.get("type")
        #             if comp_type == "range":
        #                 default_range = default_state.get("default_range")
        #                 is_at_default = value == default_range
        #             elif comp_type == "select":
        #                 default_value = default_state.get("default_value")
        #                 is_at_default = value == default_value or (
        #                     value == [] and default_value is None
        #                 )
        #             elif comp_type == "date_range":
        #                 default_range = default_state.get("default_range")
        #                 is_at_default = value == default_range
        #             else:
        #                 is_at_default = False
        #
        #             if not is_at_default:
        #                 all_at_defaults = False
        #                 break
        #
        #         if all_at_defaults:
        #             # ⭐ CRITICAL: Only prevent update if we're NOT adding new components
        #             # Check if current update has MORE components than previous store
        #             prev_component_count = len(
        #                 previous_store_data.get("interactive_components_values", [])
        #             )
        #             current_component_count = len(values)
        #
        #             if current_component_count > prev_component_count:
        #                 # We're adding NEW components - ALLOW update to populate store fully
        #                     f"   ℹ️ Adding new components ({prev_component_count} → {current_component_count}) - allowing update despite defaults"
        #                 )
        #             else:
        #                 # Same or fewer components, all at defaults - PREVENT redundant update
        #                 elapsed_ms = (time.perf_counter() - start_time) * 1000
        #                     "🚫 OPTIMIZATION: All values at defaults (preventing spurious re-render)"
        #                 )
        #                     f"   Detected {len(values)} interactive components with default values"
        #                 )
        #                     "   Preventing unnecessary store update and card loading overlay"
        #                 )
        #                 raise dash.exceptions.PreventUpdate

        components_values = []

        for i in range(len(values)):
            value = values[i]

            if value is not None:
                components_values.append(
                    {
                        "index": ids[i]["index"],
                        "value": value,
                    }
                )

        # ⭐ OPTIMIZATION: Compare with previous state to prevent redundant updates
        # This prevents the spurious second render when interactive components finish rendering

        # Determine if this is the first load (initial population with default values)
        is_first_load = previous_store_data is None or not previous_store_data.get(
            "interactive_components_values"
        )

        new_store_data = {
            "interactive_components_values": components_values,
            "first_load": is_first_load,  # Flag to distinguish initial load from user interactions
        }

        if previous_store_data is not None and previous_store_data.get(
            "interactive_components_values"
        ):
            # Create comparable structure (sort by index for consistent comparison)
            prev_components = sorted(
                previous_store_data.get("interactive_components_values", []),
                key=lambda x: x.get("index", ""),
            )
            new_components = sorted(components_values, key=lambda x: x.get("index", ""))

            # Deep comparison of values
            if prev_components == new_components:
                raise dash.exceptions.PreventUpdate
            else:
                # User changed filter values
                from depictio.api.v1.configs.logging_init import logger

                active_count = len([c for c in components_values if c.get("value")])
                logger.info(f"🔍 Filters updated: {active_count} active filter(s)")
        elif previous_store_data is None or not previous_store_data.get(
            "interactive_components_values"
        ):
            # ⭐ OPTIMIZATION: Progressive store updates - don't block on component count
            # Allow store updates as soon as any component has a value for better responsiveness
            # Cards will handle partial data gracefully via idempotency checks
            if not components_values:
                raise dash.exceptions.PreventUpdate

        return new_store_data


def register_global_filter_callbacks(app: dash.Dash) -> None:
    """Register callbacks for global filter promote/demote and globe toggle color sync.

    Args:
        app: Dash application instance.
    """
    from depictio.api.v1.configs.logging_init import logger

    @app.callback(
        Output("global-filters-store", "data", allow_duplicate=True),
        Input({"type": "global-filter-toggle", "index": dash.ALL}, "n_clicks"),
        State("interactive-values-store", "data"),
        State("global-filters-store", "data"),
        State({"type": "interactive-stored-metadata", "index": dash.ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": dash.ALL}, "id"),
        State("local-store", "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def toggle_global_filter(
        n_clicks_list: list[int | None],
        local_filters: dict[str, Any] | None,
        global_filters: dict[str, Any] | None,
        metadata_list: list[dict[str, Any] | None],
        metadata_ids: list[dict[str, str]],
        local_data: dict[str, Any] | None,
        pathname: str | None,
    ) -> dict[str, Any]:
        """Promote or demote a filter to/from global scope.

        When the globe icon is clicked:
        1. Identifies the clicked component via callback_context
        2. Looks up dc_id + column_name from stored metadata
        3. Toggles: if already global → remove; if not → add current value
        4. Persists to MongoDB via API (for editors/owners)

        Args:
            n_clicks_list: Click counts for all globe toggle buttons.
            local_filters: Current interactive-values-store data.
            global_filters: Current global-filters-store data.
            metadata_list: Stored metadata for all interactive components.
            metadata_ids: IDs for the stored metadata components.
            local_data: User auth data with access_token.
            pathname: Current URL pathname.

        Returns:
            Updated global-filters-store data.

        Raises:
            PreventUpdate: If no valid click detected or missing metadata.
        """
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate

        # Find which button was clicked
        triggered_id = ctx.triggered_id
        if not isinstance(triggered_id, dict) or triggered_id.get("type") != "global-filter-toggle":
            raise dash.exceptions.PreventUpdate

        clicked_index = triggered_id.get("index")
        if not clicked_index:
            raise dash.exceptions.PreventUpdate

        # Build metadata lookup
        metadata_by_index: dict[str, dict[str, Any]] = {}
        for i, meta_id in enumerate(metadata_ids):
            if i < len(metadata_list) and metadata_list[i]:
                idx = meta_id.get("index") if isinstance(meta_id, dict) else str(meta_id)
                metadata_by_index[idx] = metadata_list[i]

        component_metadata = metadata_by_index.get(clicked_index)
        if not component_metadata:
            logger.warning(f"No metadata found for component {clicked_index[:8]}...")
            raise dash.exceptions.PreventUpdate

        dc_id = str(component_metadata.get("dc_id", ""))
        column_name = component_metadata.get("column_name", "")
        filter_type = component_metadata.get("interactive_component_type", "Select")

        if not dc_id or not column_name:
            logger.warning(f"Missing dc_id or column_name for component {clicked_index[:8]}...")
            raise dash.exceptions.PreventUpdate

        filter_key = f"{dc_id}:{column_name}"
        global_filters = dict(global_filters) if global_filters else {}

        # Extract current tab ID from pathname
        source_tab_id = ""
        if pathname:
            parts = pathname.strip("/").split("/")
            if len(parts) >= 2:
                source_tab_id = parts[-1].replace("/edit", "")

        if filter_key in global_filters:
            # Demote: remove from global filters
            del global_filters[filter_key]
            logger.info(f"Global filter demoted: {column_name} (dc={dc_id[:8]}...)")
        else:
            # Promote: find current value from interactive-values-store
            current_value = None
            if local_filters and local_filters.get("interactive_components_values"):
                for comp in local_filters["interactive_components_values"]:
                    if comp.get("index") == clicked_index:
                        current_value = comp.get("value")
                        break

            global_filters[filter_key] = {
                "values": current_value,
                "filter_type": filter_type,
                "source_tab_id": source_tab_id,
                "column_name": column_name,
                "dc_id": dc_id,
            }
            logger.info(f"Global filter promoted: {column_name} (dc={dc_id[:8]}...)")

        # Persist to MongoDB (fire-and-forget for editors/owners)
        access_token = local_data.get("access_token") if local_data else None
        if access_token and source_tab_id:
            try:
                from depictio.dash.api_calls import API_BASE_URL

                httpx.put(
                    f"{API_BASE_URL}/depictio/api/v1/dashboards/global-filters/{source_tab_id}",
                    json=global_filters,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=5.0,
                )
            except Exception as e:
                # Non-blocking: session store is already updated
                logger.debug(f"Could not persist global filters to DB: {e}")

        return global_filters

    @app.callback(
        Output({"type": "global-filter-toggle", "index": dash.ALL}, "color"),
        Input("global-filters-store", "data"),
        State({"type": "interactive-stored-metadata", "index": dash.ALL}, "data"),
        State({"type": "interactive-stored-metadata", "index": dash.ALL}, "id"),
        prevent_initial_call=False,
    )
    def update_globe_toggle_colors(
        global_filters: dict[str, Any] | None,
        metadata_list: list[dict[str, Any] | None],
        metadata_ids: list[dict[str, str]],
    ) -> list[str]:
        """Set globe toggle icon color based on global filter state.

        Returns 'blue' for components whose dc_id:column_name is in global filters,
        'gray' otherwise.

        Args:
            global_filters: Current global-filters-store data.
            metadata_list: Stored metadata for all interactive components.
            metadata_ids: IDs for the stored metadata components.

        Returns:
            List of color strings for each globe toggle button.
        """
        if not metadata_ids:
            raise dash.exceptions.PreventUpdate

        global_filters = global_filters or {}

        # Build set of active global filter keys
        global_keys: set[str] = set(global_filters.keys())

        colors: list[str] = []
        for i, meta_id in enumerate(metadata_ids):
            metadata = metadata_list[i] if i < len(metadata_list) and metadata_list[i] else {}

            dc_id = str(metadata.get("dc_id", ""))
            column_name = metadata.get("column_name", "")
            filter_key = f"{dc_id}:{column_name}"

            colors.append("blue" if filter_key in global_keys else "gray")

        return colors
