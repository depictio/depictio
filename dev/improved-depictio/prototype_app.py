"""
Minimal Prototype: Draggable Modular System
Focus: Component-level rendering with MATCH indexing and draggable wrappers
"""

import time
from typing import Dict

import dash
import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
import diskcache
import numpy as np
import pandas as pd
import plotly.express as px
import polars as pl
from dash import ALL, MATCH, DiskcacheManager, Input, Output, Patch, State, dcc, html

# High-performance plotting with Datashader
try:
    import datashader as ds
    import datashader.transfer_functions as tf
    import holoviews as hv
    import panel as pn
    from holoviews import opts
    from holoviews.operation.datashader import datashade
    from holoviews.plotting.plotly.dash import to_dash
    DATASHADER_AVAILABLE = True
    print("📈 Datashader available for high-performance plotting")
    
    # Configure HoloViews for Plotly backend
    hv.extension('plotly')
    
except ImportError:
    DATASHADER_AVAILABLE = False
    print("⚠️ Datashader not available, falling back to regular Plotly")

cache = diskcache.Cache("./cache")
background_callback_manager = DiskcacheManager(cache)

# ============================================================================
# SAMPLE DATA - No DB connection
# ============================================================================

# Generate heavy shared dataframe for all components
print("📊 Generating shared heavy dataset...")
n_points = 10000000  # 100K points for heavy performance testing
np.random.seed(42)  # Consistent data

SHARED_DATAFRAME = pl.DataFrame(
    {
        "x": np.random.randn(n_points),
        "y": np.random.randn(n_points),
        "size": np.random.randint(0, 100, n_points),  # Size values 0-100 for filtering
        "category": np.random.choice(["A", "B", "C", "D"], n_points),
        "value": np.random.uniform(1000, 50000, n_points),
        "revenue": np.random.uniform(10000, 200000, n_points),  # For card component
    }
)

print(
    f"📈 Shared dataset created: {SHARED_DATAFRAME.shape} - Memory: ~{SHARED_DATAFRAME.estimated_size('mb'):.1f}MB"
)

DEFAULT_METADATA = [
    {
        "index": "card-001",
        "component_type": "card",
        "title": "Sample Card 1",
        "column_name": "revenue",
        "aggregation": "sum",
        "value": 125000,
        "color": "#3498db",
        "x": 0,
        "y": 0,
        "w": 4,
        "h": 4,
    },
    {
        "index": "figure-001",
        "component_type": "figure",
        "title": "Sample Scatter Plot",
        "x": 6,
        "y": 0,
        "w": 8,
        "h": 5,
    },
    {
        "index": "interactive-001",
        "component_type": "interactive",
        "title": "Range Slider",
        "min": 0,
        "max": 100,
        "value": [0, 100],
        "x": 0,
        "y": 5,
        "w": 4,
        "h": 4,
    },
]

# ============================================================================
# LOADING STATES - Proper loading indicators
# ============================================================================

def create_loading_card() -> dmc.Card:
    """Create a loading state for card components."""
    return dmc.Card(
        [
            dmc.Center(
                [
                    dmc.Loader(color="blue", size="md"),
                    dmc.Text("Loading card data...", size="sm", style={"marginTop": "10px"}),
                ],
                style={"height": "100%", "flexDirection": "column"},
            )
        ],
        shadow="sm",
        padding="lg",
        style={
            "height": "100%",
            "border": "2px solid #e0e0e0",
            "backgroundColor": "#f9f9f9",
        },
    )


def create_loading_figure() -> html.Div:
    """Create a loading state for figure components."""
    return html.Div(
        [
            dmc.Center(
                [
                    dmc.Loader(color="green", size="lg", variant="dots"),
                    dmc.Text("Loading chart data...", size="sm", style={"marginTop": "10px"}),
                    dmc.Text("Processing 1M+ data points", size="xs", c="gray", style={"marginTop": "5px"}),
                ],
                style={"height": "250px", "flexDirection": "column"},
            )
        ],
        style={"height": "100%", "backgroundColor": "#f5f5f5", "border": "2px solid #d0d0d0"},
    )


def create_loading_interactive() -> dmc.Card:
    """Create a loading state for interactive components."""
    return dmc.Card(
        [
            dmc.Center(
                [
                    dmc.Loader(color="purple", size="sm", variant="bars"),
                    dmc.Text("Loading controls...", size="sm", style={"marginTop": "10px"}),
                ],
                style={"height": "100%", "flexDirection": "column"},
            )
        ],
        shadow="sm",
        padding="lg",
        style={
            "height": "100%",
            "border": "2px solid #e0e0e0",
            "backgroundColor": "#fafafa",
        },
    )


def get_loading_component(component_type: str) -> html.Div:
    """Get the appropriate loading component based on type."""
    loading_map = {
        "card": create_loading_card(),
        "figure": create_loading_figure(),
        "interactive": create_loading_interactive(),
    }
    
    return loading_map.get(
        component_type, 
        html.Div(
            dmc.Center([
                dmc.Loader(color="gray", size="md"),
                dmc.Text(f"Loading {component_type}...", size="sm", style={"marginTop": "10px"}),
            ], style={"height": "100%", "flexDirection": "column"})
        )
    )

# ============================================================================
# COMPONENT BUILDING - Simplified
# ============================================================================


def build_simple_card(metadata: Dict) -> html.Div:
    """Build a simple card component from metadata."""
    return dmc.Card(
        [
            dmc.Title(metadata.get("title", "Card"), order=4),
            dmc.Text(f"Column: {metadata.get('column_name', 'N/A')}", size="sm"),
            dmc.Text(f"Aggregation: {metadata.get('aggregation', 'N/A')}", size="sm"),
            dmc.Title(
                str(metadata.get("value", 0)),
                order=2,
                style={"color": metadata.get("color", "#000")},
            ),
        ],
        shadow="sm",
        padding="lg",
        style={
            "height": "100%",
            "border": f"2px solid {metadata.get('color', '#ddd')}",
        },
    )


def build_simple_figure(metadata: Dict) -> html.Div:
    """Build a simple scatter plot from metadata. NOTE: This should not be used for initial loading."""
    # This function is kept for reference but should not show placeholder data
    # Instead, figures should start with loading state and be populated via the figure callback
    
    return html.Div(
        [
            dcc.Graph(
                id={"type": "graph", "index": metadata["index"]},  # Separate targetable Graph
                figure={"data": [], "layout": {"title": "Loading..."}},  # Empty figure during loading
                style={"height": "100%", "width": "100%"},
            )
        ]
    )

def build_datashader_component(df: pl.DataFrame, title: str = "Scatter Plot", filter_range: list = None):
    """Create a Dash component with Datashader integration."""
    if not DATASHADER_AVAILABLE:
        print("⚠️ Datashader not available, falling back to regular scatter")
        return build_regular_scatter(df, title, filter_range)
    
    print(f"🔥 Building Datashader component with {df.height:,} points")
    
    try:
        # Convert Polars to Pandas for Datashader
        df_pd = df.to_pandas()
        
        # Create HoloViews Dataset and Scatter
        dataset = hv.Dataset(df_pd)
        scatter = hv.Scatter(dataset, kdims=["x"], vdims=["y"])
        
        # Apply datashading
        datashaded_scatter = datashade(scatter, 
                                      cmap=['lightblue', 'darkblue'], 
                                      width=800, height=400)
        
        # Add title
        plot_title = title if not filter_range else f"{title} (Filtered: {filter_range})"
        datashaded_scatter = datashaded_scatter.opts(
            title=f"{plot_title} with {len(dataset):,} points",
            width=800, 
            height=400
        )
        
        # Convert to Dash components - this creates a temporary app to get the components
        from dash import Dash
        temp_app = Dash(__name__)
        components = to_dash(temp_app, [datashaded_scatter], reset_button=False)
        
        print("✅ Datashader component created successfully")
        return components.children[0] if components.children else html.Div("Error creating datashader plot")
        
    except Exception as e:
        print(f"❌ Error creating datashader component: {e}")
        return build_regular_scatter(df, title, filter_range)


def build_filtered_card(metadata: Dict, filter_range: list) -> html.Div:
    """Build a card component that shows filter information using shared dataframe."""
    # Use shared dataframe for realistic filtering
    df_filtered = SHARED_DATAFRAME.filter(
        (pl.col("size") >= filter_range[0]) & (pl.col("size") <= filter_range[1])
    )

    # Calculate real aggregated values from filtered data
    original_value = int(SHARED_DATAFRAME["revenue"].sum())
    filtered_value = int(df_filtered["revenue"].sum())
    count_filtered = df_filtered.height
    count_original = SHARED_DATAFRAME.height
    
    # Determine if this is initial state (full range) or filtered
    is_initial_state = filter_range == [0, 100] and count_filtered == count_original
    
    # Determine card styling and title based on state
    if is_initial_state:
        card_title = metadata.get("title", "Card")
        background_color = "#ffffff"  # White background for initial state
        border_color = metadata.get("color", "#3498db")
    else:
        card_title = f"{metadata.get('title', 'Card')} (Filtered)"
        background_color = "#f0f8ff"  # Light blue background for filtered state
        border_color = "#2980b9"  # Darker blue for filtered state

    return dmc.Card(
        [
            dmc.Title(card_title, order=4),
            dmc.Text(f"Column: {metadata.get('column_name', 'revenue')}", size="sm"),
            dmc.Text(f"Aggregation: {metadata.get('aggregation', 'sum')}", size="sm"),
            dmc.Text(f"Range: {filter_range[0]}-{filter_range[1]}", size="sm", 
                    c="blue" if not is_initial_state else "gray"),
            dmc.Text(f"Records: {count_filtered:,} / {count_original:,}", size="sm", c="orange"),
            dmc.Title(
                f"${filtered_value:,}",
                order=2,
                style={"color": metadata.get("color", "#000")},
            ),
            dmc.Text(f"Total Dataset: ${original_value:,}", size="xs", c="gray") if not is_initial_state else None,
        ],
        shadow="sm",
        padding="lg",
        style={
            "height": "100%",
            "border": f"2px solid {border_color}",
            "backgroundColor": background_color,
        },
    )


def build_simple_interactive(metadata: Dict) -> html.Div:
    """Build a simple range slider from metadata."""
    return dmc.Card(
        [
            dmc.Title(metadata.get("title", "Interactive"), order=4),
            html.Br(),
            dcc.RangeSlider(
                id={"type": "range-slider", "index": metadata["index"]},
                min=metadata.get("min", 0),
                max=metadata.get("max", 100),
                value=metadata.get("value", [20, 80]),
                marks={
                    metadata.get("min", 0): str(metadata.get("min", 0)),
                    metadata.get("max", 100): str(metadata.get("max", 100)),
                },
                tooltip={"placement": "bottom", "always_visible": True},
            ),
            html.Br(),
            html.Div(
                id={"type": "slider-output", "index": metadata["index"]},
                children=f"Range: {metadata.get('value', [0, 100])}",
                style={"textAlign": "center", "marginTop": "10px"},
            ),
        ],
        shadow="sm",
        padding="lg",
        style={
            "height": "100%",
            "border": "2px solid #9c88ff",
        },
    )


def build_datashader_figure(df: pl.DataFrame, title: str = "Resampled Scatter", filter_range: list = None):
    """Create a high-performance scatter plot using plotly-resampler with ScatterGL."""
    from plotly_resampler import FigureResampler
    
    print(f"🚀 Building resampled scattergl with {df.height:,} points")
    
    try:
        # Apply filtering BEFORE creating plot
        if filter_range:
            print(f"🔍 Applying filter: size between {filter_range[0]} and {filter_range[1]}")
            df_filtered = df.filter(
                (pl.col("size") >= filter_range[0]) & (pl.col("size") <= filter_range[1])
            )
            print(f"📊 Filtered from {df.height:,} to {df_filtered.height:,} points")
        else:
            df_filtered = df
        
        # Sort by x-axis for plotly-resampler (required for time series aggregation)
        df_sorted = df_filtered.sort("x")
        
        # Create FigureResampler with ScatterGL
        fig = FigureResampler(default_n_shown_samples=10000)
        
        # Add scatter trace using plotly-resampler with sorted data
        fig.add_scattergl(
            x=df_sorted["x"],
            y=df_sorted["y"],
            mode='markers',
            marker=dict(
                size=4,
                color=df_sorted["size"],
                colorscale='viridis',
                showscale=True
            ),
            name='Data Points'
        )
        
        fig.update_layout(
            title=f"{title} - {df_filtered.height:,} points",
            height=400,
            xaxis_title="X",
            yaxis_title="Y",
            showlegend=False
        )
        
        print("✅ Plotly-resampler scattergl created successfully")
        return dcc.Graph(figure=fig, style={"height": "100%", "width": "100%"})
        
    except Exception as e:
        print(f"❌ Plotly-resampler error: {e}")
        return html.Div(f"Error creating resampled plot: {e}")


def build_regular_scatter(df: pl.DataFrame, title: str = "Scatter Plot", filter_range: list = None) -> dict:
    """Fallback regular scatter plot with smart sampling."""
    print(f"📊 Building regular scatter with {df.height:,} points")
    
    # Smart sampling for performance
    if df.height > 100000:
        print(f"📊 Sampling {df.height:,} points down to 100K for performance")
        df_sampled = df.sample(100000, seed=42)
    else:
        df_sampled = df
    
    # Use ScatterGL for better performance with medium-large datasets
    fig = px.scatter(
        df_sampled,
        x="x", y="y", 
        color="category" if "category" in df_sampled.columns else None,
        title=title if not filter_range else f"{title} (Filtered: {filter_range})",
        render_mode='webgl'  # Force WebGL rendering
    )
    
    fig.update_layout(
        height=400,
        margin=dict(l=20, r=20, t=40, b=20)
    )
    
    print("✅ Regular scatter figure created")
    return fig


def update_figure_with_patch(component_id: str, new_data: dict):
    """Example of how to use Patch() for efficient updates."""
    patch = Patch()
    # Add new trace
    patch["data"].append(
        {"x": new_data["x"], "y": new_data["y"], "type": "scatter", "mode": "markers"}
    )
    # Update title
    patch["layout"]["title"]["text"] = new_data.get("title", "Updated Figure")
    return patch


# ============================================================================
# APP LAYOUT
# ============================================================================


def create_app():
    """Create the minimal prototype app."""

    app = dash.Dash(__name__, background_callback_manager=background_callback_manager)

    print("🚀 Creating app with callbacks...")

    # Create component-specific stores upfront
    component_stores = []
    for metadata in DEFAULT_METADATA:
        # Trigger store
        component_stores.append(
            dcc.Store(
                id={"type": "component-render-trigger", "index": metadata["index"]},
                data={},
            )
        )
        # Metadata store
        component_stores.append(
            dcc.Store(
                id={"type": "component-metadata", "index": metadata["index"]},
                data=metadata,
            )
        )

    app.layout = dmc.MantineProvider(
        [
            dcc.Location(id="url", refresh=False),
            # Component metadata store (replaces DB)
            dcc.Store(
                id="component-metadata-store",
                data=DEFAULT_METADATA,
            ),
            # Component-specific stores
            html.Div(component_stores, style={"display": "none"}),
            # Header
            dmc.Title("Draggable Prototype", order=1, style={"padding": "20px"}),
            # Main draggable grid
            dgl.DashGridLayout(
                id="draggable-grid",
                items=[],  # Will be populated by callback
                currentLayout=[],  # Will be populated by callback
                cols={"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
                rowHeight=80,
                style={
                    "width": "100%",
                    "height": "calc(100vh - 100px)",
                    "padding": "20px",
                },
            ),
            # Debug info
            html.Div(id="debug-output", style={"padding": "20px"}),
        ]
    )

    # ============================================================================
    # CALLBACKS - Registered with app instance
    # ============================================================================

    @app.callback(
        Output({"type": "component-render-trigger", "index": ALL}, "data"),
        [
            Input("draggable-grid", "items"),  # Wait for containers to be created
        ],
        prevent_initial_call=True,  # Don't run until containers exist
    )
    def trigger_component_updates(grid_items):
        """Central trigger - distributes updates to all component-specific triggers."""
        print(f"🔥 TRIGGER: grid_items={len(grid_items) if grid_items else 0}")
        print("💡 This will replace Loading states with actual components")

        if not grid_items:
            return []

        trigger_data = {
            "timestamp": time.time(),
            "needs_update": True,
            "initial_load": True,  # Flag to indicate this is initial component loading
        }

        # Send same trigger data to all component-specific triggers
        return [trigger_data] * len(grid_items)

    @app.callback(
        Output("draggable-grid", "itemLayout"),
        Input({"type": "component-render-trigger", "index": ALL}, "data"),
        Input("url", "pathname"),
        State({"type": "component-metadata", "index": ALL}, "data"),
        prevent_initial_call=False,
    )
    def update_item_layout(trigger, pathname, metadata):
        """Updates the layout of draggable items based on the grid layout."""
        print(f"🔄 ITEM LAYOUT: {trigger}, PATHNAME: {pathname}")
        print(f"Metadata: {metadata}")
        updated_layout = []
        for item in metadata:
            print(f" - {item.get('title')} (ID: {item.get('id')})")
            layout = {
                "i": f"box-{item.get('index')}",
                "x": item.get("x"),
                "y": item.get("y"),
                "w": item.get("w"),
                "h": item.get("h"),
            }
            print(f" - Layout for {item.get('title')}: {layout}")
            updated_layout.append(layout)
        return updated_layout

    @app.callback(
        Output({"type": "component", "index": MATCH}, "children"),
        Input({"type": "component-render-trigger", "index": MATCH}, "data"),
        State({"type": "component-metadata", "index": MATCH}, "data"),
        prevent_initial_call=False,
        background=True
    )
    def update_component_content(trigger, metadata):
        """MATCH-based callback - renders NON-FIGURE components only."""
        print(f"🎯 [BACKGROUND] COMPONENT CALLBACK START: trigger={trigger}, metadata={metadata}")

        if not trigger or not metadata:
            print("❌ [BACKGROUND] Missing trigger or metadata")
            return dash.no_update

        component_type = metadata.get("component_type")
        component_index = metadata.get("index")

        print(f"✅ [BACKGROUND] Building {component_type} for {component_index}")
        
        # Simulate processing time for demonstration
        if component_type == "card":
            print(f"🔄 [BACKGROUND] Processing card data for {component_index} - STARTING SLEEP...")
            # time.sleep(1)  # 1 second delay for cards
            print(f"✅ [BACKGROUND] Card data processing COMPLETED for {component_index}")
        elif component_type == "interactive":
            print(f"🔄 [BACKGROUND] Initializing interactive component {component_index} - STARTING SLEEP...")
            # time.sleep(0.5)  # 0.5 second delay for interactive components
            print(f"✅ [BACKGROUND] Interactive component initialization COMPLETED for {component_index}")

        # Build the appropriate component
        if component_type == "card":
            # Check if filter data is available and modify card accordingly
            filter_range = None
            if trigger and isinstance(trigger, dict):
                filter_range = trigger.get("filter_range")

            if filter_range:
                # Create modified metadata with filter info
                card_metadata = metadata.copy()
                card_metadata["title"] = f"{metadata.get('title', 'Card')} (Filtered)"
                card_metadata["filter_info"] = f"Range: {filter_range}"
                component = build_filtered_card(card_metadata, filter_range)
            else:
                # Initial load: show card with full dataset (no filter)
                # Use build_filtered_card with full range to show realistic data
                full_range = [0, 100]  # Full range from metadata
                component = build_filtered_card(metadata, full_range)
        elif component_type == "figure":
            # Create datashader component directly
            print(f"📊 Building datashader figure for {component_index}")
            
            # Check if filter data is available
            filter_range = None
            if trigger and isinstance(trigger, dict):
                filter_range = trigger.get("filter_range")
                
            # Use datashader for high-performance visualization
            title = metadata.get("title", "Scatter Plot")
            component = build_datashader_figure(SHARED_DATAFRAME, title, filter_range)
        elif component_type == "interactive":
            component = build_simple_interactive(metadata)  # Create range slider
        else:
            print(f"❌ Unsupported component type: {component_type}")
            return html.Div(f"Unsupported: {component_type}")

        # Return the component wrapped in the proper container structure
        print(f"🎯 [BACKGROUND] COMPONENT CALLBACK COMPLETED for {component_type} {component_index}")
        return [html.Div([component], style={"width": "100%", "height": "100%", "padding": "8px"})]

    @app.callback(
        [Output("draggable-grid", "items"), Output("draggable-grid", "currentLayout")],
        Input("component-metadata-store", "data"),
        prevent_initial_call=False,
    )
    def create_draggable_containers(metadata_list):
        """Creates draggable wrapper containers for each component."""
        print(f"🏗️ CONTAINERS: Creating {len(metadata_list) if metadata_list else 0} containers")

        if not metadata_list:
            print("⚠️ No metadata - returning empty containers")
            return [], []

        containers = []
        layouts = []

        for metadata in metadata_list:
            component_uuid = metadata["index"]
            # Create draggable wrapper with direct component targeting
            # Get component type for proper loading state
            component_type = metadata.get("component_type", "unknown")
            
            wrapper = dgl.DraggableWrapper(
                id=f"box-{component_uuid}",
                children=[
                    html.Div(
                        get_loading_component(component_type),
                        style={"width": "100%", "height": "100%", "padding": "8px"},
                        id={"type": "component", "index": component_uuid},
                    )
                ],
                handleText="Drag",
            )

            containers.append(wrapper)

            # Create layout info for dash-dynamic-grid-layout
            layouts.append(
                {
                    "i": f"box-{component_uuid}",
                    "x": metadata.get("x", 0),
                    "y": metadata.get("y", 0),
                    "w": metadata.get("w", 10),
                    "h": metadata.get("h", 8),
                }
            )

        print(f"📦 Returning {len(containers)} containers and {len(layouts)} layouts")
        return containers, layouts

    # Figure callback: Updates only figure content
    @app.callback(
        Output({"type": "graph", "index": MATCH}, "figure"),
        Input({"type": "component-render-trigger", "index": MATCH}, "data"),
        State({"type": "component-metadata", "index": MATCH}, "data"),
        prevent_initial_call=False,  # Allow initial call to create figures
        background=True
    )
    def update_figure_efficiently(trigger, metadata):
        """MATCH-based callback - renders and updates FIGURE components only."""
        print(f"📊 [BACKGROUND] FIGURE CALLBACK START: trigger={trigger}, metadata={metadata}")

        if not metadata:
            print("❌ [BACKGROUND] Figure callback: Missing metadata")
            return dash.no_update

        component_type = metadata.get("component_type")
        component_index = metadata.get("index")

        # Only handle figures
        if component_type != "figure":
            print(f"⏭️ [BACKGROUND] Skipping {component_type} {component_index} - handled by component callback")
            return dash.no_update

        print(f"✅ [BACKGROUND] Building/updating figure for {component_index}")
        
        # Simulate processing time for heavy datasets
        if not trigger or not trigger.get("filter_range"):
            print("🔄 [BACKGROUND] Processing 1M+ data points for initial figure load - STARTING SLEEP...")
            # time.sleep(2)  # 2 second delay for initial figure creation
            print("✅ [BACKGROUND] Initial figure load processing COMPLETED")
        else:
            print("🔄 [BACKGROUND] Applying filter to figure data - STARTING SLEEP...")
            # time.sleep(0.8)  # 0.8 second delay for filtering
            print("✅ [BACKGROUND] Figure filtering COMPLETED")

        # Use the shared dataframe
        df = SHARED_DATAFRAME
        print(f"📊 Using shared dataframe: {df.shape}")

        # Check if this is a filter update vs initial load
        filter_range = None
        if trigger and isinstance(trigger, dict):
            filter_range = trigger.get("filter_range")

        # If this is a filter update, use Patch for efficiency
        if filter_range:
            print(f"📊 Using Patch to apply filter: {filter_range}")

        # Note: Patch could be used for efficient updates but not in this demo

        # Filter the data
        if filter_range:
            df_filtered = df.filter(
                (pl.col("size") >= filter_range[0]) & (pl.col("size") <= filter_range[1])
            )
        else:
            df_filtered = df

        # Use Datashader for high-performance rendering of large datasets
        title = metadata.get("title", "Scatter Plot")
        fig = build_datashader_figure(df_filtered, title, filter_range)

        print(f"📊 [BACKGROUND] FIGURE CALLBACK COMPLETED for {component_index}")
        return fig

    # Interactive filtering: Rangeslider changes trigger other components
    @app.callback(
        Output({"type": "component-render-trigger", "index": ALL}, "data", allow_duplicate=True),
        Input({"type": "range-slider", "index": ALL}, "value"),
        State("component-metadata-store", "data"),
        prevent_initial_call=True,
        background=True
    )
    def handle_interactive_changes(slider_values, metadata_list):
        """When interactive components change, trigger updates to filterable components."""
        print(f"🎛️ [BACKGROUND] INTERACTIVE CHANGE START: slider_values={slider_values}")

        if not slider_values or not metadata_list:
            print("❌ [BACKGROUND] Missing slider values or metadata")
            return dash.no_update

        # Simulate heavy filtering processing
        print("🔄 [BACKGROUND] Processing filter changes on large dataset - STARTING SLEEP...")
        # time.sleep(0.8)  # Simulate filtering time
        print("✅ [BACKGROUND] Filter processing COMPLETED")

        # Create trigger data with the current filter values
        trigger_data = {
            "timestamp": time.time(),
            "needs_update": True,
            "filter_range": slider_values[0] if slider_values else None,  # First slider value
        }

        # Update triggers only for components that should respond to filtering
        result = []
        for metadata in metadata_list:
            component_type = metadata.get("component_type")
            component_index = metadata.get("index")

            # Only update figure and card components, skip interactive components
            if component_type in ["figure", "card"]:
                print(f"🎯 [BACKGROUND] Triggering update for {component_type} {component_index}")
                result.append(trigger_data)
            else:
                print(f"⏭️ [BACKGROUND] Skipping {component_type} {component_index}")
                result.append(dash.no_update)

        print(f"🎛️ [BACKGROUND] INTERACTIVE CALLBACK COMPLETED - triggered {len([r for r in result if r != dash.no_update])} components")
        return result

    # Add a simple debug callback to see the state
    @app.callback(
        Output("debug-output", "children"),
        Input("draggable-grid", "items"),
        prevent_initial_call=True,
    )
    def debug_output(items):
        if items:
            return f"Debug: Grid has {len(items)} items"
        return "Debug: No items in grid"

    return app


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=8892)
