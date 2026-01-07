"""
Interactive Component - Core Callbacks

This module contains the core callbacks for interactive components.
This callback is always loaded at app startup.

Callbacks:
- Filter reset callback (clientside): Resets interactive component values to defaults
- Async rendering callback (serverside): Builds interactive components with data loaded asynchronously
"""

from dash import MATCH, Input, Output, State


def register_core_callbacks(app):
    """Register core clientside callback for interactive component."""

    app.clientside_callback(
        """
        function(individual_reset_clicks, reset_all_clicks, component_metadata, store_data) {
            console.log('🔄 CLIENTSIDE FILTER RESET: Triggered');

            // Get the triggered component info from dash_clientside
            var ctx = dash_clientside.callback_context;
            if (!ctx || !ctx.triggered || ctx.triggered.length === 0) {
                console.log('❌ No trigger detected, skipping reset');
                return window.dash_clientside.no_update;
            }

            var triggered_id = ctx.triggered[0].prop_id.split('.')[0];
            console.log('📍 Triggered by:', triggered_id);

            if (!component_metadata) {
                console.warn('⚠️  No component metadata available');
                return window.dash_clientside.no_update;
            }

            var component_index = component_metadata.index;
            var component_type = component_metadata.interactive_component_type;

            // Check if this is actually a reset button click
            var is_reset_trigger = triggered_id.includes('reset-selection-graph-button') ||
                                  triggered_id.includes('reset-all-filters-button');

            if (!is_reset_trigger) {
                // Not a reset button - preserve existing value from store
                console.log('📥 Non-reset trigger for ' + component_index + ', preserving store value');
                if (store_data && store_data.interactive_components_values) {
                    var components = store_data.interactive_components_values;
                    for (var i = 0; i < components.length; i++) {
                        if (components[i].index === component_index) {
                            var existing_value = components[i].value;
                            console.log('✅ Preserving existing value for ' + component_index + ':', existing_value);
                            return existing_value;
                        }
                    }
                }
                console.log('No store value found for ' + component_index + ', no update');
                return window.dash_clientside.no_update;
            }

            // RESET TRIGGERED - return default value
            console.log('🔄 Reset triggered for component ' + component_index + ' (' + component_type + ')');

            // Get default state from metadata
            var default_state = component_metadata.default_state || {};

            // Generic default value logic (extendable for future components)
            if (default_state.default_range !== undefined) {
                var default_value = default_state.default_range;
                console.log('✅ Resetting ' + component_index + ' to default_range:', default_value);
                return default_value;
            } else if (default_state.default_value !== undefined) {
                var default_value = default_state.default_value;
                console.log('✅ Resetting ' + component_index + ' to default_value:', default_value);
                return default_value;
            } else {
                // Fallback based on component type
                var fallback_value = (component_type === 'MultiSelect') ? [] : null;
                console.log('✅ Resetting ' + component_index + ' (' + component_type + ') to fallback:', fallback_value);
                return fallback_value;
            }
        }
        """,
        Output({"type": "interactive-component-value", "index": MATCH}, "value"),
        Input({"type": "reset-selection-graph-button", "index": MATCH}, "n_clicks"),
        Input("reset-all-filters-button", "n_clicks"),
        State({"type": "interactive-stored-metadata", "index": MATCH}, "data"),
        State("interactive-values-store", "data"),
        prevent_initial_call=True,
    )
