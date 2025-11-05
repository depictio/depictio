"""
Vizro Integration Prototype

This is a minimal working example showing how to integrate Vizro dashboards
into an existing Dash application. This prototype demonstrates the key concepts
learned from the Depictio integration effort.

Key Learnings:
1. Vizro must be initialized with the host app instance via monkey-patching
2. Callbacks are registered globally and need _setup_server() to activate
3. Vizro's routing system conflicts with host app routing
4. Full Vizro app layout (with dcc.Location) must be returned for callbacks to work
5. The dcc.Location pathname must be controlled to trigger Vizro's page routing

Run this file standalone to see the working integration:
    python dev/vizro_integration_prototype.py
"""

import pandas as pd
import vizro.models as vm  # type: ignore[import-untyped]
import vizro.plotly.express as px  # type: ignore[import-untyped]
from dash import Dash, dcc, html
from vizro import Vizro  # type: ignore[import-untyped]
from vizro.managers import data_manager  # type: ignore[import-untyped]


def create_vizro_dashboard():
    """Create a minimal Vizro dashboard with 2 components and 1 filter."""
    # Load iris dataset
    iris_df = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/iris.csv")
    data_manager["iris_data"] = iris_df

    print(f"📊 Loaded iris dataset: {len(iris_df)} rows")

    # Create minimal dashboard: 1 card + 2 graphs + 1 filter
    dashboard = vm.Dashboard(
        pages=[
            vm.Page(
                title="Iris Analysis",
                path="/",  # Default page
                components=[
                    vm.Card(
                        text="## Iris Dataset\n\nInteractive analysis with 2 scatter plots and species filter.",
                    ),
                    vm.Graph(
                        id="scatter_sepal",
                        figure=px.scatter(
                            data_frame="iris_data",
                            x="SepalLength",
                            y="SepalWidth",
                            color="Name",
                            title="Sepal Dimensions",
                        ),
                    ),
                    vm.Graph(
                        id="scatter_petal",
                        figure=px.scatter(
                            data_frame="iris_data",
                            x="PetalLength",
                            y="PetalWidth",
                            color="Name",
                            size="SepalLength",
                            title="Petal Dimensions",
                        ),
                    ),
                ],
                controls=[
                    vm.Filter(
                        column="Name",
                        selector=vm.Dropdown(multi=True),
                    )
                ],
            )
        ],
        title="Vizro Iris Dashboard",
    )

    return dashboard


def initialize_vizro(host_app: Dash):
    """
    Initialize Vizro framework to use the host Dash app.

    This is the critical step that makes Vizro work within an existing Dash app.
    Uses monkey-patching to ensure Vizro's callbacks register on the host app.

    Args:
        host_app: The host Dash application instance

    Returns:
        Vizro: The initialized Vizro app instance
    """
    print("🔧 Initializing Vizro with monkey-patching...")

    # Create Vizro dashboard
    dashboard = create_vizro_dashboard()

    # Monkey-patch Vizro to use host app instead of creating its own
    import vizro._vizro

    original_dash_class = vizro._vizro.dash.Dash

    def dash_factory(*args, **kwargs):
        print(f"🔧 Vizro requesting Dash app - returning host app (id: {id(host_app)})")
        return host_app

    # Apply monkey-patch BEFORE creating Vizro instance
    vizro._vizro.dash.Dash = dash_factory

    try:
        # Save original layout
        original_layout = getattr(host_app, "layout", None)

        print(f"🔧 Callbacks BEFORE Vizro.build(): {len(host_app.callback_map)}")

        # Create and build Vizro - will use host app via monkey-patch
        vizro = Vizro()
        vizro_app = vizro.build(dashboard)

        print(f"🔧 Callbacks AFTER Vizro.build(): {len(host_app.callback_map)}")

        # CRITICAL: Call _setup_server() to register global callbacks
        print("🔧 Calling _setup_server() to register Vizro's global callbacks...")
        host_app._setup_server()

        callback_count = len(host_app.callback_map)
        print(f"✅ Callbacks registered after _setup_server(): {callback_count}")

        # Restore host app's original layout
        if original_layout is not None:
            host_app.layout = original_layout
            print("✅ Restored host app's layout")
        else:
            host_app.layout = html.Div("Loading...")
            print("✅ Set placeholder layout (host uses dynamic layout)")

        print(f"✅ Vizro.dash IS host_app: {vizro_app.dash is host_app}")

        return vizro_app

    finally:
        # Restore original Dash class
        import vizro._vizro

        vizro._vizro.dash.Dash = original_dash_class
        print("✅ Restored original Dash class")


def get_vizro_layout(vizro_app):
    """
    Get the Vizro complete app layout directly from the Vizro app instance.

    This is the key insight: we need the FULL Vizro app layout (including dcc.Location,
    stores, etc.) for callbacks to work, but we access it directly from the Vizro app
    object instead of through the host app's layout property (which would cause recursion).

    Args:
        vizro_app: The Vizro app instance (returned by Vizro().build())

    Returns:
        Dash component: The complete Vizro app layout
    """
    print("📦 Getting Vizro complete app layout...")

    # CRITICAL: Access Vizro's layout directly from the Vizro app instance
    # This gives us the full app infrastructure (Location, stores, etc.)
    # without causing recursion because we're not accessing host_app.layout

    # Vizro stores its layout in the dash instance it created
    # Since we monkey-patched it, vizro_app.dash IS the host app
    # But we can access Vizro's original layout via Vizro's _layout attribute

    # Get the Vizro app's layout function/component
    if hasattr(vizro_app, '_layout'):
        vizro_layout = vizro_app._layout
        print("📦 Found Vizro._layout attribute")
    else:
        # Fallback: Get from the dashboard build
        print("📦 No _layout attribute, using dashboard build")
        vizro_layout = vizro_app._dashboard.build()

    # If it's a callable, invoke it
    if callable(vizro_layout):
        print("📦 Vizro layout is callable, invoking it...")
        vizro_layout = vizro_layout()

    print(f"📦 Vizro layout type: {type(vizro_layout).__name__}")

    # Modify the dcc.Location pathname to "/" so Vizro routes to default page
    def set_location_pathname(component):
        """Find dcc.Location and set its pathname to /."""
        if isinstance(component, dcc.Location):
            component.pathname = "/"
            print(f"✅ Set dcc.Location pathname to '/' (id: {component.id})")
            return True

        if hasattr(component, "children"):
            children = component.children
            if children is not None:
                if isinstance(children, list):
                    for child in children:
                        if set_location_pathname(child):
                            return True
                elif not isinstance(children, str):
                    return set_location_pathname(children)
        return False

    set_location_pathname(vizro_layout)

    return vizro_layout


def create_host_app_with_vizro():
    """
    Create a minimal host Dash app with integrated Vizro dashboard.

    This demonstrates the complete integration pattern:
    1. Create host Dash app
    2. Initialize Vizro with monkey-patching
    3. Create layout that includes Vizro content
    4. Return app ready to run

    Returns:
        Dash: The host app with Vizro integrated
    """
    print("🚀 Creating host Dash app...")

    # Create host Dash app
    host_app = Dash(
        __name__,
        suppress_callback_exceptions=True,
        title="Vizro Integration Prototype",
    )

    # Initialize Vizro with host app
    vizro_app = initialize_vizro(host_app)

    # Create simple routing layout
    def serve_layout():
        """Dynamic layout that shows Vizro content."""
        print("📄 Serving layout...")

        # Get Vizro's complete app layout (including Location, stores, etc.)
        # Pass the vizro_app instance, not the dashboard
        vizro_content = get_vizro_layout(vizro_app)

        # Wrap in a simple container
        layout = html.Div(
            [
                html.Div(
                    [
                        html.H1("Vizro Integration Prototype", style={"color": "#2c3e50"}),
                        html.P(
                            "This demonstrates Vizro running inside a host Dash app",
                            style={"color": "#7f8c8d"},
                        ),
                        html.Hr(),
                    ],
                    style={"padding": "20px", "backgroundColor": "#ecf0f1"},
                ),
                html.Div(
                    vizro_content,
                    style={"padding": "20px"},
                ),
            ]
        )

        return layout

    # Set the layout - Dash 3.x requires calling the function once
    # or using app.layout as a property
    print("🔧 Setting up layout...")

    # Option 1: Call it once to get the initial layout
    # host_app.layout = serve_layout()

    # Option 2: Use function for dynamic layouts (Dash will call it on each page load)
    # But we need to make sure it's being called
    initial_layout = serve_layout()
    host_app.layout = initial_layout

    print("✅ Host app created with Vizro integrated")

    return host_app


if __name__ == "__main__":
    print("=" * 60)
    print("VIZRO INTEGRATION PROTOTYPE")
    print("=" * 60)

    # Create the integrated app
    app = create_host_app_with_vizro()

    print("\n" + "=" * 60)
    print("🌐 Starting server on http://localhost:8051")
    print("=" * 60 + "\n")

    # Run the app
    app.run(debug=True, port=8051)
