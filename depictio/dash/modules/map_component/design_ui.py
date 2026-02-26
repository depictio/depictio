"""
Map Component - Design UI for Stepper Step 3.

Provides design_map() which creates the configuration panel and live preview
for creating/editing map components in the stepper workflow.
"""

from typing import Any

import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify


def design_map(
    id: dict | str,
    df: Any = None,
    wf_id: str | None = None,
    dc_id: str | None = None,
    **kwargs: Any,
) -> html.Div:
    """Create the map component design UI for the stepper.

    Two-panel layout: left side has configuration controls,
    right side shows a live map preview.

    Args:
        id: Component identifier (dict with type/index or string).
        df: DataFrame for populating column selectors.
        wf_id: Workflow ID for the component metadata.
        dc_id: Data collection ID for the component metadata.
        **kwargs: Additional parameters.

    Returns:
        html.Div with the design UI layout.
    """
    n = id["index"] if isinstance(id, dict) else str(id)

    # Extract column names from DataFrame
    columns: list[str] = []
    numeric_columns: list[str] = []
    if df is not None:
        if hasattr(df, "columns"):
            columns = list(df.columns)
        if hasattr(df, "dtypes"):
            for col in columns:
                dtype = str(df[col].dtype) if hasattr(df[col], "dtype") else ""
                if any(t in dtype.lower() for t in ["int", "float", "numeric"]):
                    numeric_columns.append(col)

    column_options = [{"value": c, "label": c} for c in columns]
    numeric_options = [{"value": c, "label": c} for c in numeric_columns]

    # Left panel: configuration
    left_panel = dmc.Stack(
        [
            dmc.Text("Map Configuration", fw="bold", size="lg"),
            # Required: lat/lon columns
            dmc.Select(
                id={"type": "map-lat-column", "index": n},
                label="Latitude Column",
                description="Column with latitude values",
                data=numeric_options,
                searchable=True,
                required=True,
                leftSection=DashIconify(icon="mdi:latitude"),
            ),
            dmc.Select(
                id={"type": "map-lon-column", "index": n},
                label="Longitude Column",
                description="Column with longitude values",
                data=numeric_options,
                searchable=True,
                required=True,
                leftSection=DashIconify(icon="mdi:longitude"),
            ),
            # Optional: color and size
            dmc.Select(
                id={"type": "map-color-column", "index": n},
                label="Color Column",
                description="Column for marker color encoding",
                data=column_options,
                searchable=True,
                clearable=True,
                leftSection=DashIconify(icon="mdi:palette"),
            ),
            dmc.Select(
                id={"type": "map-size-column", "index": n},
                label="Size Column",
                description="Column for marker size encoding",
                data=numeric_options,
                searchable=True,
                clearable=True,
                leftSection=DashIconify(icon="mdi:resize"),
            ),
            # Hover columns
            dmc.MultiSelect(
                id={"type": "map-hover-columns", "index": n},
                label="Hover Columns",
                description="Columns to show on hover tooltip",
                data=column_options,
                searchable=True,
                clearable=True,
            ),
            # Map style
            dmc.SegmentedControl(
                id={"type": "map-style-selector", "index": n},
                data=[
                    {"value": "open-street-map", "label": "Street Map"},
                    {"value": "carto-positron", "label": "Light"},
                    {"value": "carto-darkmatter", "label": "Dark"},
                ],
                value="carto-positron",
                fullWidth=True,
            ),
            # Opacity slider
            dmc.Text("Opacity", size="sm", fw=500),
            dmc.Slider(
                id={"type": "map-opacity", "index": n},
                min=0.1,
                max=1.0,
                step=0.1,
                value=0.8,
                marks=[
                    {"value": 0.2, "label": "0.2"},
                    {"value": 0.5, "label": "0.5"},
                    {"value": 0.8, "label": "0.8"},
                    {"value": 1.0, "label": "1.0"},
                ],
            ),
            # Selection toggle
            dmc.Switch(
                id={"type": "map-selection-enabled", "index": n},
                label="Enable cross-filtering selection",
                checked=False,
            ),
            dmc.Select(
                id={"type": "map-selection-column", "index": n},
                label="Selection Column",
                description="Column to extract from selected points",
                data=column_options,
                searchable=True,
                clearable=True,
                disabled=True,
            ),
        ],
        gap="md",
    )

    # Right panel: live preview
    right_panel = dmc.Stack(
        [
            dmc.Text("Preview", fw="bold", size="lg"),
            dcc.Graph(
                id={"type": "map-preview-graph", "index": n},
                config={"scrollZoom": True, "displayModeBar": "hover"},
                style={"height": "500px", "width": "100%"},
            ),
        ],
        gap="md",
    )

    # Store for design state
    design_store = dcc.Store(
        id={"type": "map-design-store", "index": n},
        data={},
    )

    # Component metadata store — the stepper save reads this to persist the component
    metadata_store = dcc.Store(
        id={"type": "stored-metadata-component", "index": n},
        data={
            "index": n,
            "component_type": "map",
            "map_type": "scatter_map",
            "wf_id": wf_id,
            "dc_id": dc_id,
        },
        storage_type="memory",
    )

    # Store the DataFrame so the preview callback can access it.
    # Handles both Polars (to_dicts) and Pandas (to_dict(orient="records")).
    df_records = None
    if df is not None:
        try:
            if hasattr(df, "to_dicts"):
                # Polars DataFrame
                df_records = df.to_dicts()
            elif hasattr(df, "to_dict"):
                # Pandas DataFrame
                df_records = df.to_dict(orient="records")
        except Exception:
            pass
    df_store = dcc.Store(
        id={"type": "map-df-store", "index": n},
        data=df_records,
    )

    return html.Div(
        [
            design_store,
            df_store,
            metadata_store,
            dmc.Paper(
                [
                    dmc.Paper(
                        left_panel,
                        w="40%",
                        p="xl",
                        style={"borderRight": "1px solid var(--mantine-color-gray-4)"},
                    ),
                    dmc.Paper(right_panel, w="60%", p="xl"),
                ],
                w="100%",
                mih=300,
                withBorder=True,
                radius="md",
                p="xs",
                style={"display": "flex", "flexDirection": "row", "gap": "10px"},
            ),
        ]
    )
