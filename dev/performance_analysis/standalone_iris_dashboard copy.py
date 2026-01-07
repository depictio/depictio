#!/usr/bin/env python3
"""
Standalone Optimized Iris Dashboard for Performance Benchmarking

This is a minimal, optimized version of the Depictio dashboard system designed to:
1. Replicate the lite_dashboard.json configuration (11 components)
2. Use existing build_* helper functions for component consistency
3. Provide baseline performance metrics for comparison
4. Support incremental addition of filtering functionality

Components:
- 3 Interactive components (2 RangeSliders, 1 MultiSelect)
- 6 Metric cards (various aggregations)
- 2 Figures (box plot, histogram)

Usage:
    python standalone_iris_dashboard.py
    # Navigate to: http://localhost:5081/dashboard/iris-benchmark
"""

import os

# ============================================================================
# CRITICAL: Configure service connections BEFORE any depictio imports
# This ensures Settings() picks up the correct hostnames (localhost not Docker names)
# Docker exposes services on localhost (see docker-compose.dev.yaml)
# ============================================================================

# Redis cache configuration (localhost:6379)
os.environ["DEPICTIO_CACHE_REDIS_HOST"] = "localhost"
os.environ["DEPICTIO_CACHE_REDIS_PORT"] = "6379"
os.environ["DEPICTIO_CACHE_ENABLE_REDIS_CACHE"] = "true"

# FastAPI backend configuration (localhost:8058)
os.environ["DEPICTIO_FASTAPI_SERVICE_NAME"] = "localhost"
os.environ["DEPICTIO_FASTAPI_SERVICE_PORT"] = "8058"

# Now safe to import depictio modules (Settings will use above env vars)
import json
import sys
from pathlib import Path
from typing import Any

import dash_mantine_components as dmc
import polars as pl
from dash import ALL, MATCH, Dash, Input, Output, State, callback, dcc, html
from dash_iconify import DashIconify

# Add depictio to path for imports
DEPICTIO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(DEPICTIO_ROOT))

# Import and initialize Redis cache BEFORE building components
from depictio.api.cache import get_cache

# Import for monkey-patching DataFrame loader
from depictio.api.v1 import deltatables_utils

# Import callback registration functions
from depictio.dash.modules.card_component.frontend import register_callbacks_card_component

# Import component builders
from depictio.dash.modules.card_component.utils import build_card
from depictio.dash.modules.figure_component.frontend import register_callbacks_figure_component
from depictio.dash.modules.figure_component.utils import build_figure
from depictio.dash.modules.interactive_component.utils import build_interactive

# File paths
LITE_DASHBOARD_JSON = DEPICTIO_ROOT / "depictio/api/v1/configs/iris_dataset/lite_dashboard.json"
IRIS_CSV = DEPICTIO_ROOT / "depictio/api/v1/configs/iris_dataset/iris.csv"


# ============================================================================
# Data Loading and Preparation
# ============================================================================

def load_iris_data() -> pl.DataFrame:
    """Load the Iris dataset from CSV."""
    df = pl.read_csv(str(IRIS_CSV))
    print(f"✓ Loaded Iris dataset: {df.shape[0]} rows, {df.shape[1]} columns")
    return df


def initialize_cache() -> None:
    """
    Initialize Redis cache connection early.
    This establishes the connection before component building starts.
    """
    cache = get_cache()
    redis_status = "✅ Redis available" if cache._redis_available else "❌ Redis unavailable (memory fallback)"
    print(f"{redis_status}")

    if cache._redis_available:
        print(f"   Connected to: {cache.cache_config.redis_host}:{cache.cache_config.redis_port}")

    return None


def load_component_metadata() -> dict[str, list[dict[str, Any]]]:
    """Load and categorize component metadata from lite_dashboard.json."""
    with open(LITE_DASHBOARD_JSON, "r") as f:
        dashboard_data = json.load(f)

    stored_metadata = dashboard_data["stored_metadata"]

    # Categorize components by type
    components = {
        "interactive": [],
        "card": [],
        "figure": []
    }

    for meta in stored_metadata:
        comp_type = meta["component_type"]
        if comp_type in components:
            components[comp_type].append(meta)

    print(f"✓ Loaded metadata: {len(components['interactive'])} interactive, "
          f"{len(components['card'])} cards, {len(components['figure'])} figures")

    return components


def compute_cols_json(df: pl.DataFrame) -> dict[str, dict[str, Any]]:
    """
    Compute statistical specifications for all columns.
    This replicates the cols_json structure expected by component builders.
    """
    cols_json = {}

    for col in df.columns:
        dtype = str(df[col].dtype)

        if dtype in ["Float64", "Int64", "Float32", "Int32"]:
            # Numeric column
            col_data = df[col].drop_nulls()
            cols_json[col] = {
                "type": "float64" if "Float" in dtype else "int64",
                "description": f"{col} column",
                "specs": {
                    "count": col_data.len(),
                    "unique": col_data.n_unique(),
                    "sum": float(col_data.sum()),
                    "average": float(col_data.mean()),
                    "median": float(col_data.median()),
                    "min": float(col_data.min()),
                    "max": float(col_data.max()),
                    "range": float(col_data.max() - col_data.min()),
                    "variance": float(col_data.var()) if col_data.var() is not None else 0.0,
                    "std_dev": float(col_data.std()) if col_data.std() is not None else 0.0,
                    "percentile": float(col_data.median()),
                    "skewness": 0.0,  # Simplified
                    "kurtosis": 0.0,  # Simplified
                }
            }
        else:
            # String/categorical column
            col_data = df[col].drop_nulls()
            cols_json[col] = {
                "type": "object",
                "description": f"{col} column",
                "specs": {
                    "count": col_data.len(),
                    "mode": str(col_data.mode()[0]) if col_data.len() > 0 else None,
                    "nunique": col_data.n_unique(),
                }
            }

    print(f"✓ Computed statistical specs for {len(cols_json)} columns")
    return cols_json


# ============================================================================
# Component Building
# ============================================================================

def build_all_components(
    df: pl.DataFrame,
    cols_json: dict[str, dict[str, Any]],
    metadata: dict[str, list[dict[str, Any]]]
) -> dict[str, list[Any]]:
    """
    Build all dashboard components using existing helper functions.

    Returns dict with keys: interactive, card, figure
    Each containing list of rendered components.
    """
    components_built = {
        "interactive": [],
        "card": [],
        "figure": []
    }

    # Prepare common dc_config (minimal version)
    dc_config = {
        "type": "table",
        "metatype": "Metadata",
        "_id": {"$oid": "68ee1ce0766d13e034d230f7"},
    }

    # Build interactive components
    print(f"\nBuilding {len(metadata['interactive'])} interactive components...")
    for meta in metadata["interactive"]:
        try:
            # For standalone mode, pass access_token=None to force using pre-loaded df
            # This prevents build_interactive from trying to fetch data from API
            component = build_interactive(
                index=meta["index"],
                wf_id=str(meta["wf_id"]["$oid"]),
                dc_id=str(meta["dc_id"]["$oid"]),
                dc_config=dc_config,
                column_name=meta["column_name"],
                column_type=meta["column_type"],
                interactive_component_type=meta["interactive_component_type"],
                cols_json=cols_json,
                df=df,
                value=meta.get("value"),
                title=meta.get("title"),
                scale=meta.get("scale", "linear"),
                custom_color=meta.get("custom_color"),
                icon_name=meta.get("icon_name"),
                marks_number=meta.get("marks_number", 2),
                title_size=meta.get("title_size", "md"),
                build_frame=False,  # No loading wrappers for performance
                stepper=False,
                access_token=None,  # Force use of pre-loaded df, don't fetch from API
            )
            components_built["interactive"].append(component)
            print(f"  ✓ Built {meta['interactive_component_type']}: {meta['column_name']}")
        except Exception as e:
            print(f"  ✗ Failed to build interactive {meta['index']}: {e}")

    # Build metric cards
    print(f"\nBuilding {len(metadata['card'])} metric cards...")
    for meta in metadata["card"]:
        try:
            component = build_card(
                index=meta["index"],
                wf_id=str(meta["wf_id"]["$oid"]),
                dc_id=str(meta["dc_id"]["$oid"]),
                dc_config=dc_config,
                column_name=meta["column_name"],
                column_type=meta["column_type"],
                aggregation=meta["aggregation"],
                cols_json=cols_json,
                df=df,
                title=meta.get("title", ""),
                title_color=meta.get("title_color"),
                icon_name=meta.get("icon_name"),
                icon_color=meta.get("icon_color"),
                title_font_size=meta.get("title_font_size", "xl"),
                value_font_size=meta.get("value_font_size", "xl"),
                build_frame=False,  # No loading wrappers for performance
                stepper=False,
            )
            components_built["card"].append(component)
            print(f"  ✓ Built card: {meta['aggregation']}({meta['column_name']})")
        except Exception as e:
            print(f"  ✗ Failed to build card {meta['index']}: {e}")

    # Build figures
    print(f"\nBuilding {len(metadata['figure'])} figures...")
    for meta in metadata["figure"]:
        try:
            component = build_figure(
                index=meta["index"],
                dict_kwargs=meta["dict_kwargs"],
                visu_type=meta["visu_type"],
                wf_id=str(meta["wf_id"]["$oid"]),
                dc_id=str(meta["dc_id"]["$oid"]),
                dc_config=dc_config,
                df=df,
                build_frame=False,  # No loading wrappers for performance
                stepper=False,
                theme="light",
                mode=meta.get("mode", "ui"),
            )
            components_built["figure"].append(component)
            print(f"  ✓ Built figure: {meta['visu_type']}")
        except Exception as e:
            print(f"  ✗ Failed to build figure {meta['index']}: {e}")

    total_built = sum(len(v) for v in components_built.values())
    print(f"\n✓ Successfully built {total_built}/11 components")

    return components_built


# ============================================================================
# Callback System with DataFrame Filtering
# ============================================================================

# Global variable to store the pre-loaded DataFrame for callbacks
_STANDALONE_DATAFRAME = None
_STANDALONE_WF_ID = None
_STANDALONE_DC_ID = None


def apply_filters_to_df(df: pl.DataFrame, metadata: list[dict[str, Any]] | None) -> pl.DataFrame:
    """
    Apply interactive component filters to DataFrame.

    Args:
        df: Polars DataFrame to filter
        metadata: List of filter specifications from interactive components

    Returns:
        Filtered Polars DataFrame
    """
    if not metadata:
        return df

    filtered_df = df

    for filter_item in metadata:
        try:
            column = filter_item.get("column_name")
            values = filter_item.get("value")  # CRITICAL: Must match "value" from store callback!
            component_type = filter_item.get("interactive_component_type")

            if not column or values is None:
                continue

            if component_type in ["RangeSlider", "Slider"]:
                # Range filter for numeric columns
                min_val, max_val = values
                filtered_df = filtered_df.filter(
                    (pl.col(column) >= min_val) & (pl.col(column) <= max_val)
                )

            elif component_type in ["Select", "MultiSelect", "SegmentedControl"]:
                # Categorical filter
                if isinstance(values, list):
                    filtered_df = filtered_df.filter(pl.col(column).is_in(values))
                else:
                    filtered_df = filtered_df.filter(pl.col(column) == values)

        except Exception as e:
            print(f"Warning: Failed to apply filter for {column}: {e}")
            continue

    return filtered_df


def setup_dataframe_wrapper(df: pl.DataFrame, wf_id: str, dc_id: str) -> None:
    """
    Set up monkey-patch wrapper for load_deltatable_lite to use pre-loaded DataFrame.

    This allows the registered callbacks to work without making API calls,
    while still supporting filtering via metadata.

    Args:
        df: Pre-loaded Polars DataFrame
        wf_id: Workflow ID
        dc_id: Data collection ID
    """
    global _STANDALONE_DATAFRAME, _STANDALONE_WF_ID, _STANDALONE_DC_ID

    # Store DataFrame and IDs globally
    _STANDALONE_DATAFRAME = df
    _STANDALONE_WF_ID = wf_id
    _STANDALONE_DC_ID = dc_id

    # Save original function
    _original_load_deltatable_lite = deltatables_utils.load_deltatable_lite

    def _standalone_load_deltatable_lite(workflow_id, data_collection_id, metadata=None, **kwargs):
        """Wrapper that returns pre-loaded DataFrame with optional filtering"""
        import sys

        print(f"[DataFrame Wrapper] CALLED: wf_id={workflow_id}, dc_id={data_collection_id}", flush=True)
        print(f"[DataFrame Wrapper] metadata: {metadata}", flush=True)
        sys.stdout.flush()

        # Check if this is our standalone workflow/dc
        wf_match = str(workflow_id) == _STANDALONE_WF_ID
        dc_match = str(data_collection_id) == _STANDALONE_DC_ID

        print(f"[DataFrame Wrapper] Match check: wf={wf_match}, dc={dc_match}", flush=True)
        sys.stdout.flush()

        if wf_match and dc_match and _STANDALONE_DATAFRAME is not None:
            # Start with full DataFrame
            result_df = _STANDALONE_DATAFRAME.clone()
            print(f"[DataFrame Wrapper] Using pre-loaded DataFrame: {result_df.shape}", flush=True)

            # Apply filters if metadata provided
            if metadata:
                result_df = apply_filters_to_df(result_df, metadata)
                print(f"[DataFrame Wrapper] Applied filters: {len(metadata)} filters, {len(result_df)} rows remaining", flush=True)
            else:
                print("[DataFrame Wrapper] No filters applied", flush=True)

            sys.stdout.flush()
            return result_df

        # Fallback to original for other cases
        print("[DataFrame Wrapper] Falling back to original loader", flush=True)
        sys.stdout.flush()
        return _original_load_deltatable_lite(workflow_id, data_collection_id, metadata=metadata, **kwargs)

    # Replace function globally
    deltatables_utils.load_deltatable_lite = _standalone_load_deltatable_lite
    print("✓ DataFrame wrapper installed for callbacks")


# ============================================================================
# Layout Construction
# ============================================================================

def create_header_content(components_count: dict[str, int]) -> html.Div:
    """Create the application header content."""
    return html.Div(
        dmc.Group(
            justify="space-between",
            style={"height": "100%", "padding": "0 20px"},
            children=[
                dmc.Group(
                    gap="sm",
                    children=[
                        DashIconify(
                            icon="mdi:iris",
                            width=32,
                            color="#7C4DFF"
                        ),
                        dmc.Title(
                            "Iris Dashboard - Performance Benchmark",
                            order=3,
                            style={"color": "var(--app-text-color, #000)"}
                        ),
                    ]
                ),
                dmc.Group(
                    gap="md",
                    children=[
                        dmc.Badge(
                            f"{sum(components_count.values())} components",
                            color="blue",
                            variant="filled",
                            size="lg"
                        ),
                        dmc.Badge(
                            "Standalone Optimized",
                            color="green",
                            variant="filled",
                            size="lg"
                        ),
                    ]
                )
            ]
        ),
        style={
            "backgroundColor": "var(--app-surface-color, #fff)",
            "borderBottom": "1px solid var(--app-border-color, #dee2e6)",
            "height": "100%",
            "display": "flex",
            "alignItems": "center",
        }
    )


def create_navbar_content(components_count: dict[str, int]) -> html.Div:
    """Create the application navbar content."""
    return html.Div(
        dmc.Stack(
            gap="md",
            style={"padding": "20px"},
            children=[
                dmc.Title("Components", order=5),
                dmc.Divider(),
                dmc.Group(
                    gap="xs",
                    children=[
                        DashIconify(icon="mdi:filter", width=20),
                        dmc.Text(f"{components_count['interactive']} Interactive"),
                    ]
                ),
                dmc.Group(
                    gap="xs",
                    children=[
                        DashIconify(icon="mdi:card", width=20),
                        dmc.Text(f"{components_count['card']} Metric Cards"),
                    ]
                ),
                dmc.Group(
                    gap="xs",
                    children=[
                        DashIconify(icon="mdi:chart-bar", width=20),
                        dmc.Text(f"{components_count['figure']} Figures"),
                    ]
                ),
                dmc.Divider(),
                dmc.Text(
                    f"Total: {sum(components_count.values())} components",
                    size="sm",
                    fw=600,
                    c="dimmed"
                ),
            ]
        ),
        style={
            "backgroundColor": "var(--app-surface-color, #fff)",
            "height": "100%",
        }
    )


def create_dashboard_grid(components_built: dict[str, list[Any]]) -> html.Div:
    """
    Create a responsive grid layout for all dashboard components.
    Uses CSS Grid for optimal performance.
    """
    # Flatten all components in display order:
    # Row 1: Interactive components
    # Row 2: Metric cards
    # Row 3+: Figures

    all_items = []

    # Interactive components section
    if components_built["interactive"]:
        all_items.append(
            dmc.Title("Filters", order=4, style={"gridColumn": "1 / -1", "margin": "10px 0"})
        )
        for comp in components_built["interactive"]:
            all_items.append(
                dmc.Paper(
                    children=comp,
                    shadow="xs",
                    p="md",
                    radius="md",
                    style={
                        "backgroundColor": "var(--app-surface-color, #fff)",
                        "border": "1px solid var(--app-border-color, #dee2e6)",
                    }
                )
            )

    # Metric cards section
    if components_built["card"]:
        all_items.append(
            dmc.Title("Metrics", order=4, style={"gridColumn": "1 / -1", "margin": "20px 0 10px 0"})
        )
        for comp in components_built["card"]:
            all_items.append(
                dmc.Paper(
                    children=comp,
                    shadow="xs",
                    p="md",
                    radius="md",
                    style={
                        "backgroundColor": "var(--app-surface-color, #fff)",
                        "border": "1px solid var(--app-border-color, #dee2e6)",
                    }
                )
            )

    # Figures section
    if components_built["figure"]:
        all_items.append(
            dmc.Title("Visualizations", order=4, style={"gridColumn": "1 / -1", "margin": "20px 0 10px 0"})
        )
        for comp in components_built["figure"]:
            all_items.append(
                dmc.Paper(
                    children=comp,
                    shadow="xs",
                    p="md",
                    radius="md",
                    style={
                        "backgroundColor": "var(--app-surface-color, #fff)",
                        "border": "1px solid var(--app-border-color, #dee2e6)",
                        "gridColumn": "span 2",  # Figures take 2 columns
                    }
                )
            )

    return html.Div(
        children=all_items,
        style={
            "display": "grid",
            "gridTemplateColumns": "repeat(auto-fit, minmax(300px, 1fr))",
            "gap": "20px",
            "padding": "20px",
            "width": "100%",
        }
    )


# ============================================================================
# Application Setup
# ============================================================================

def create_app() -> Dash:
    """Create and configure the Dash application."""
    print("\n" + "="*80)
    print("STANDALONE IRIS DASHBOARD - PERFORMANCE BENCHMARK")
    print("="*80 + "\n")

    # Register Mantine figure templates for Plotly (required for theme support)
    dmc.add_figure_templates()

    # Initialize Redis cache connection
    initialize_cache()

    # Load data
    df = load_iris_data()
    cols_json = compute_cols_json(df)
    metadata = load_component_metadata()

    # Build components
    components_built = build_all_components(df, cols_json, metadata)

    # Extract workflow and data collection IDs from metadata
    wf_id = str(metadata["card"][0]["wf_id"]["$oid"])
    dc_id = str(metadata["card"][0]["dc_id"]["$oid"])

    # Set up DataFrame wrapper for callbacks (allows filtering without API calls)
    setup_dataframe_wrapper(df, wf_id, dc_id)

    # Create Dash app
    app = Dash(
        __name__,
        suppress_callback_exceptions=True,
        title="Iris Dashboard - Benchmark"
    )

    # Register pattern-matching callbacks for cards and figures
    print("Registering callbacks...")
    register_callbacks_card_component(app)
    register_callbacks_figure_component(app)
    print("✓ Callbacks registered")

    # Register callback to aggregate interactive component values into the store
    @app.callback(
        Output("interactive-values-store", "data"),
        Input({"type": "interactive-component-value", "index": ALL}, "value"),
        State({"type": "interactive-component-value", "index": ALL}, "id"),
        State({"type": "stored-metadata-component", "index": ALL}, "id"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        prevent_initial_call=False,  # MUST fire on initial page load!
    )
    def update_interactive_values_store(values, component_ids, metadata_ids, metadata_list):
        """
        Aggregate all interactive component values into a single store.
        This triggers card and figure callbacks to update with filtered data.
        """
        import sys

        print("=" * 80, flush=True)
        print(f"[Interactive Store] CALLBACK FIRED", flush=True)
        print(f"[Interactive Store] values: {values}", flush=True)
        print(f"[Interactive Store] component_ids: {component_ids}", flush=True)
        print(f"[Interactive Store] metadata count: {len(metadata_list) if metadata_list else 0}", flush=True)
        sys.stdout.flush()

        if not values or not component_ids:
            print("[Interactive Store] No values or ids, returning empty list", flush=True)
            return []

        # Build index -> metadata mapping
        metadata_map = {}
        for meta_id, meta_data in zip(metadata_ids, metadata_list):
            if meta_data and meta_id:
                idx = meta_id.get("index")
                if idx:
                    metadata_map[idx] = meta_data

        print(f"[Interactive Store] Built metadata_map with {len(metadata_map)} entries", flush=True)
        sys.stdout.flush()

        aggregated_data = []
        for value, component_id in zip(values, component_ids):
            if value is None:
                continue

            index = component_id["index"]
            metadata = metadata_map.get(index)

            if not metadata:
                print(f"[Interactive Store] No metadata for index {index}", flush=True)
                continue

            # Use correct field names from interactive component Store
            column_name = metadata.get("column_name")  # NOT interactive_component_col!
            component_type = metadata.get("interactive_component_type")

            if not column_name or not component_type:
                print(f"[Interactive Store] Missing col/type for {index}: col={column_name}, type={component_type}", flush=True)
                continue

            # Format expected by card/figure callbacks
            filter_component = {
                "index": index,
                "column_name": column_name,
                "value": value,  # CRITICAL: Must be "value" not "values"!
                "interactive_component_type": component_type,
                # Include metadata with dc_id for multi-DC filtering support
                "metadata": {
                    "dc_id": metadata.get("dc_id"),
                    "wf_id": metadata.get("wf_id"),
                    "column_name": column_name,
                    "column_type": metadata.get("column_type"),
                }
            }
            aggregated_data.append(filter_component)
            print(f"[Interactive Store] Added filter: {column_name} = {value} (type: {component_type})", flush=True)

        print(f"[Interactive Store] FINAL: Updated with {len(aggregated_data)} filters", flush=True)
        print(f"[Interactive Store] Data: {aggregated_data}", flush=True)
        print("=" * 80, flush=True)
        sys.stdout.flush()

        # Return in the format expected by card/figure callbacks:
        # {"interactive_components_values": [list of filters]}
        return {"interactive_components_values": aggregated_data}

    print("✓ Interactive store callback registered")

    # Build layout
    components_count = {k: len(v) for k, v in components_built.items()}

    app.layout = dmc.MantineProvider(
        children=[
            dmc.AppShell(
                children=[
                    dmc.AppShellHeader(
                        create_header_content(components_count)
                    ),
                    dmc.AppShellNavbar(
                        create_navbar_content(components_count)
                    ),
                    dmc.AppShellMain(
                        children=[
                            # Store for aggregated interactive component values (required for callbacks)
                            dcc.Store(id="interactive-values-store", storage_type="session", data={}),

                            # Local store (required for figure callback State dependency)
                            dcc.Store(
                                id="local-store",
                                storage_type="local",
                                data={"logged_in": False, "access_token": None},
                            ),

                            # Dashboard init data store (required for card callback compatibility)
                            # Cards use two-stage rendering with this Input, even if data=None
                            dcc.Store(
                                id="dashboard-init-data",
                                storage_type="memory",
                                data=None,  # No optimization in standalone, cards use Stage 1 (API calls)
                            ),

                            # Main dashboard container
                            html.Div(
                                id="dashboard-container",
                                children=create_dashboard_grid(components_built),
                                style={
                                    "backgroundColor": "var(--app-bg-color, #f8f9fa)",
                                    "minHeight": "100vh",
                                }
                            ),
                            # Performance tracking script
                            html.Script("""
                                window.depictioPerformance = {
                                    startTime: performance.now(),
                                    callbacks: {},
                                    renders: [],
                                    getData: function() {
                                        return {
                                            callbacks: this.callbacks,
                                            renders: this.renders,
                                            totalTime: performance.now() - this.startTime
                                        };
                                    }
                                };
                                console.log('Depictio performance tracking initialized');
                            """)
                        ]
                    ),
                ],
                header={"height": 60},
                navbar={"width": 250, "breakpoint": "sm"},
                padding="md",
            )
        ],
        theme={"colorScheme": "light"}
    )

    print("\n" + "="*80)
    print("✓ Application ready!")
    print("="*80 + "\n")

    return app


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    app = create_app()

    print("Starting standalone dashboard server...")
    print("Navigate to: http://localhost:5081/dashboard/iris-benchmark")
    print("\nPress Ctrl+C to stop the server\n")

    app.run(
        host="0.0.0.0",
        port=5081,
        debug=True,  # Disable debug for performance testing
        # dev_tools_hot_reload=False,
        # dev_tools_ui=False,
    )
