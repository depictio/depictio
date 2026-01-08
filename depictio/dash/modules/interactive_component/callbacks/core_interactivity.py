"""
Interactive Component - Interactivity System

This module handles the core interactivity system:
- Store definition for interactive component values
- Callback to aggregate values from all interactive components
- Lightweight store (values + indexes only, no metadata)

The store is consumed by passive components (cards, figures, tables) to apply filters.
"""

import dash
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
    import time

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
        from depictio.api.v1.configs.logging_init import logger

        start_time = time.perf_counter()

        # ⭐ DEBUG: Detailed logging for reset troubleshooting
        logger.debug("=" * 80)
        logger.debug("🔄 STORE UPDATE CALLBACK FIRED")
        logger.debug(f"   Components count: {len(values)}")
        logger.debug(f"   Metadata count: {len(metadata_list) if metadata_list else 0}")
        logger.debug(f"   Values: {values}")
        logger.debug(f"   IDs: {[id_dict.get('index', 'unknown')[:8] for id_dict in ids]}")

        # Show what triggered this callback
        if dash.callback_context.triggered:
            trigger_info = dash.callback_context.triggered[0]
            logger.debug(f"   Triggered by: {trigger_info['prop_id']}")
            logger.debug(f"   Trigger value: {trigger_info['value']}")

        # Show previous store state
        if previous_store_data:
            prev_values = previous_store_data.get("interactive_components_values", [])
            logger.debug(f"   Previous store had {len(prev_values)} components")
            if prev_values:
                logger.debug(f"   Previous values sample: {prev_values[:2]}")
        else:
            logger.debug("   Previous store: EMPTY (first load)")

        logger.debug(
            f"🔄 Store update: {len(values)} components, metadata: {len(metadata_list) if metadata_list else 0}"
        )

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
        #         logger.info(
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
        #     logger.debug("   ⚙️ ENTERING default value optimization check...")
        #     # Create metadata lookup by index
        #     metadata_by_index = {}
        #     try:
        #         for i, meta_id in enumerate(metadata_ids):
        #             if i < len(metadata_list) and metadata_list[i]:
        #                 metadata_by_index[meta_id["index"]] = metadata_list[i]
        #     except Exception as e:
        #         logger.warning(f"⚠️ Error creating metadata lookup: {e}")
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
        #                 logger.debug(
        #                     f"   ℹ️ Adding new components ({prev_component_count} → {current_component_count}) - allowing update despite defaults"
        #                 )
        #             else:
        #                 # Same or fewer components, all at defaults - PREVENT redundant update
        #                 elapsed_ms = (time.perf_counter() - start_time) * 1000
        #                 logger.info(
        #                     "🚫 OPTIMIZATION: All values at defaults (preventing spurious re-render)"
        #                 )
        #                 logger.debug(
        #                     f"   Detected {len(values)} interactive components with default values"
        #                 )
        #                 logger.debug(
        #                     "   Preventing unnecessary store update and card loading overlay"
        #                 )
        #                 logger.debug(f"   ⏱️ Optimization check time: {elapsed_ms:.1f}ms")
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
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                logger.info("🚫 OPTIMIZATION BLOCKED: Store values unchanged")
                logger.debug(
                    f"   Previous: {len(prev_components)} components, New: {len(new_components)} components"
                )
                logger.debug(f"   Prev values: {prev_components}")
                logger.debug(f"   New values: {new_components}")
                logger.debug(
                    f"   Values are identical - preventing redundant update (checked in {elapsed_ms:.1f}ms)"
                )
                logger.debug("=" * 80)
                raise dash.exceptions.PreventUpdate
            else:
                logger.info("✅ OPTIMIZATION BYPASSED: Values changed")
                logger.debug(f"   Previous: {prev_components}")
                logger.debug(f"   New: {new_components}")
        elif previous_store_data is None or not previous_store_data.get(
            "interactive_components_values"
        ):
            # ⭐ OPTIMIZATION: Progressive store updates - don't block on component count
            # Allow store updates as soon as any component has a value for better responsiveness
            # Cards will handle partial data gracefully via idempotency checks
            if not components_values:
                logger.debug("⏳ No components ready yet, preventing update")
                raise dash.exceptions.PreventUpdate

            expected_count = len(metadata_list) if metadata_list else 0
            logger.debug(
                f"   ℹ️ Progressive store update - allowing partial data ({len(components_values)}/{expected_count} components ready)"
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"✅ STORE UPDATE ALLOWED: {len(components_values)}/{len(values)} components ({elapsed_ms:.1f}ms)"
        )
        logger.debug(f"   Returning data: {new_store_data}")
        logger.debug("=" * 80)

        return new_store_data
