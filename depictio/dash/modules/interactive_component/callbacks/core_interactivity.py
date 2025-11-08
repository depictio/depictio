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

    Args:
        app: Dash application instance
    """

    @app.callback(
        Output("interactive-values-store", "data"),
        Input({"type": "interactive-component-value", "index": dash.ALL}, "value"),
        State({"type": "interactive-component-value", "index": dash.ALL}, "id"),
        prevent_initial_call=False,
    )
    def update_interactive_values_store(values, ids):
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

        Returns:
            dict: Aggregated values with indexes
        """
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

        return {"interactive_components_values": components_values}
