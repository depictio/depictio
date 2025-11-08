"""
Vizro module following Flask multi-app pattern with monkey-patching.

Follows the same structure as dashboard_dynamic.py and dashboard_edit.py:
- Exports a `layout` variable
- Provides a `register_callbacks(app)` function

Uses monkey-patching so Vizro registers callbacks directly on the Flask app
instead of creating its own Dash instance.
"""

import pandas as pd
import vizro.models as vm
import vizro.plotly.express as px
from vizro import Vizro
from vizro.managers import data_manager

# Store the Flask app reference for callback registration
_flask_app = None
_vizro_app = None

# Load iris dataset into Vizro's data manager
iris_df = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/iris.csv")
data_manager["iris_data"] = iris_df

# Create Vizro dashboard model
dashboard = vm.Dashboard(
    pages=[
        vm.Page(
            title="Iris Analysis",
            path="/",
            components=[
                vm.Graph(
                    id="scatter_sepal",
                    figure=px.scatter(
                        data_frame="iris_data",
                        x="SepalLength",
                        y="SepalWidth",
                        color="Name",
                    ),
                ),
                vm.Graph(
                    id="scatter_petal",
                    figure=px.scatter(
                        data_frame="iris_data",
                        x="PetalLength",
                        y="PetalWidth",
                        color="Name",
                    ),
                ),
            ],
            controls=[
                vm.Filter(column="Name", selector=vm.Dropdown(title="Species")),
            ],
        ),
        vm.Page(
            title="Distribution",
            path="/distribution",
            components=[
                vm.Graph(
                    id="histogram_sepal",
                    figure=px.histogram(
                        data_frame="iris_data",
                        x="SepalLength",
                        color="Name",
                    ),
                ),
                vm.Graph(
                    id="histogram_petal",
                    figure=px.histogram(
                        data_frame="iris_data",
                        x="PetalLength",
                        color="Name",
                    ),
                ),
            ],
        ),
    ],
)

# Build Vizro dashboard model (don't build Vizro app yet - needs Flask app)
_dashboard = dashboard

# Placeholder layout - will be set when register_callbacks is called
layout = None


def register_callbacks(app):
    """
    Register Vizro callbacks on the Flask-managed Dash app using monkey-patching.

    This makes Vizro use the Flask app directly instead of creating its own,
    so callbacks are registered on the correct app instance.

    Args:
        app: Flask-managed Dash app instance
    """
    global _flask_app, _vizro_app, layout

    print("DEBUG [vizro_flask]: Registering VIZRO app callbacks (isolated registry)")
    print(f"DEBUG [vizro_flask]: Flask app has {len(app.callback_map)} callbacks before Vizro")

    _flask_app = app

    # Monkey-patch Vizro to use the Flask app
    import vizro._vizro
    original_dash_class = vizro._vizro.dash.Dash

    def dash_factory(*args, **kwargs):
        print(f"DEBUG [vizro_flask]: Vizro requesting Dash app - returning Flask app (id: {id(app)})")
        return app

    # Apply monkey-patch
    vizro._vizro.dash.Dash = dash_factory

    try:
        # Build Vizro with monkey-patched Dash class
        print("DEBUG [vizro_flask]: Building Vizro with Flask app...")
        vizro_instance = Vizro()
        _vizro_app = vizro_instance.build(_dashboard)

        print(f"DEBUG [vizro_flask]: Callbacks BEFORE _setup_server(): {len(app.callback_map)}")

        # Call _setup_server() to activate callbacks
        print("DEBUG [vizro_flask]: Calling _setup_server() to activate callbacks...")
        app._setup_server()

        print(f"DEBUG [vizro_flask]: Callbacks AFTER _setup_server(): {len(app.callback_map)}")
        print(f"DEBUG [vizro_flask]: Sample callbacks: {list(app.callback_map.keys())[:2]}")

        # CRITICAL: Get layout from Vizro using the same approach as the working example
        # Try _layout attribute first, fallback to building from _dashboard
        try:
            layout = _vizro_app._layout
            print("DEBUG [vizro_flask]: Found Vizro._layout attribute")
        except AttributeError:
            print("DEBUG [vizro_flask]: No _layout attribute, using _dashboard.build()")
            layout = _vizro_app._dashboard.build()

        # If layout is callable, invoke it
        if callable(layout):
            print("DEBUG [vizro_flask]: Layout is callable, invoking it...")
            layout = layout()

        print(f"DEBUG [vizro_flask]: Vizro layout type: {type(layout).__name__}")

    finally:
        # Restore original Dash class
        import vizro._vizro
        vizro._vizro.dash.Dash = original_dash_class
        print("DEBUG [vizro_flask]: Restored original Dash class")
