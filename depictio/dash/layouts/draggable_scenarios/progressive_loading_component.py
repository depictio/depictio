"""
Component loading callback for progressive loading.

PERFORMANCE OPTIMIZATION (Phase 5B):
Generic callback to load components incrementally.
"""

from dash import ALL, Input, Output, State, callback_context, no_update

from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import get_build_functions
from depictio.dash.layouts.edit import enable_box_edit_mode


def register_component_loading_callback(app, component_type: str):
    """
    Register callback to load a specific component type incrementally.

    PERFORMANCE OPTIMIZATION (Phase 5B):
    This callback loads components progressively via dcc.Interval triggers,
    reducing the initial 378-mutation React render into smaller chunks.

    Each placeholder has a dcc.Interval that fires once with a staggered delay.
    This callback builds the actual component when triggered.

    Args:
        app: Dash application instance
        component_type: Type of component to load ("figure", "card", "interactive")
    """
    logger.info(f"⚡ PHASE 5B: Registering incremental loading callback for {component_type}")

    # Get build function for this component type
    build_functions = get_build_functions()
    build_function = build_functions.get(component_type)

    if not build_function:
        logger.warning(
            f"⚠️  PHASE 5B: Build function for {component_type} not found, "
            f"skipping callback registration"
        )
        return

    # CRITICAL FIX: Use "index" instead of "uuid" for pattern-matching consistency
    # This ensures progressive-loaded components can be found by pattern-matching callbacks
    @app.callback(
        Output({"type": f"{component_type}-container", "index": ALL}, "children"),
        Input({"type": f"{component_type}-load-trigger", "index": ALL}, "n_intervals"),
        State({"type": f"{component_type}-metadata-store", "index": ALL}, "data"),
        State({"type": f"{component_type}-container", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def load_component(n_intervals_list, metadata_list, container_ids):
        """
        Load component when interval fires.

        Args:
            n_intervals_list: List of n_intervals for each trigger
            metadata_list: List of component metadata for each component
            container_ids: List of container IDs

        Returns:
            List of components (or no_update for non-triggered components)
        """
        ctx = callback_context
        if not ctx.triggered:
            return [no_update] * len(container_ids)

        # Find which interval triggered
        trigger_id = ctx.triggered_id
        expected_trigger_type = f"{component_type}-load-trigger"
        if not trigger_id or trigger_id.get("type") != expected_trigger_type:
            return [no_update] * len(container_ids)

        # CRITICAL FIX: Use "index" key consistently (changed from "uuid")
        triggered_index = trigger_id.get("index")

        logger.info(f"⚡ PROGRESSIVE LOADING: Loading {component_type} component {triggered_index}")

        # Build output list
        # CRITICAL FIX: We must preserve the dcc.Store component when replacing container children
        # Container structure: [placeholder, dcc.Interval, dcc.Store]
        # We replace: [loaded_component, dcc.Store] (Interval is one-time, can be discarded)
        from dash import dcc

        outputs = []
        for i, (n_intervals, metadata, container_id) in enumerate(
            zip(n_intervals_list, metadata_list, container_ids)
        ):
            # CRITICAL FIX: Use "index" key consistently (changed from "uuid")
            container_index = container_id.get("index")

            # Only build the component that was triggered
            if container_index == triggered_index and n_intervals and n_intervals > 0:
                logger.info(f"⚡ PROGRESSIVE LOADING: Building {component_type} {container_index}")

                try:
                    # Build the actual component
                    component = build_function(**metadata)

                    # Wrap with enable_box_edit_mode like in render_dashboard
                    wrapped_component = enable_box_edit_mode(
                        component,
                        switch_state=metadata.get("edit_components_button", False),
                        dashboard_id=metadata.get("dashboard_id"),
                        component_data=metadata,
                        TOKEN=metadata.get("access_token"),
                    )

                    # CRITICAL FIX: Preserve the Store component to prevent component disappearance
                    # The Store contains metadata needed for subsequent interactions
                    # Use "index" key for consistency with pattern-matching callbacks
                    preserved_store = dcc.Store(
                        id={
                            "type": f"{component_type}-metadata-store",
                            "index": container_index,  # Changed from "uuid" to "index"
                        },
                        data=metadata,
                    )

                    # TIMING GUARD: Ensure React has time to commit the component tree
                    # before the component's own render callbacks fire (prevent_initial_call=False)
                    # This prevents race condition where card-trigger Store fires before DOM is ready
                    # The preserved Store will still exist, but the component needs to be mounted first

                    # Return both the loaded component AND the preserved Store
                    # This prevents the Store from being wiped out when we replace container children
                    outputs.append([wrapped_component, preserved_store])
                    logger.info(
                        f"✅ PROGRESSIVE LOADING: {component_type.capitalize()} "
                        f"{container_index} loaded successfully (Store preserved, React will commit)"
                    )

                except Exception as e:
                    logger.error(
                        f"❌ PROGRESSIVE LOADING: Error loading {component_type} "
                        f"{container_index}: {e}"
                    )
                    # Return placeholder on error
                    outputs.append(no_update)
            else:
                # Keep placeholder for non-triggered components
                outputs.append(no_update)

        return outputs

    logger.info(f"⚡ PHASE 5B: Incremental loading callback for {component_type} registered")
