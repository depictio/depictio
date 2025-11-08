"""
Vizro integration module for callback isolation demo.

Creates an isolated Vizro dashboard app mounted at /vizro/.
Demonstrates how Vizro can coexist with other Dash apps using Flask multi-app pattern.
"""

import pandas as pd
import vizro.models as vm
import vizro.plotly.express as px
from dash import Dash
from vizro import Vizro
from vizro.managers import data_manager


def create_vizro_app(server):
    """
    Create standalone Vizro app with proper isolation.

    Args:
        server: Flask server instance to mount the app on

    Returns:
        Dash app instance configured with Vizro
    """
    # Load Iris dataset into Vizro's data manager
    # Using Vizro's data manager allows data referencing by string name in charts
    iris_df = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/iris.csv")
    print(f"DEBUG: Loaded iris data with shape: {iris_df.shape}")
    print(f"DEBUG: Columns: {list(iris_df.columns)}")

    # Store in data manager for Vizro
    from vizro.managers import data_manager
    data_manager["iris_data"] = iris_df

    # Create Vizro dashboard model - use data_frame string reference for interactivity
    dashboard = vm.Dashboard(
        pages=[
            vm.Page(
                title="Iris Analysis",
                components=[
                    vm.Graph(
                        id="scatter_sepal",
                        figure=px.scatter(
                            data_frame="iris_data",  # Use string reference for callbacks
                            x="SepalLength",
                            y="SepalWidth",
                            color="Name",
                            title="Sepal Dimensions",
                        ),
                    ),
                    vm.Graph(
                        id="scatter_petal",
                        figure=px.scatter(
                            data_frame="iris_data",  # Use string reference for callbacks
                            x="PetalLength",
                            y="PetalWidth",
                            color="Name",
                            title="Petal Dimensions",
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
                        id="histogram_sepal_length",
                        figure=px.histogram(
                            data_frame="iris_data",  # Use string reference for callbacks
                            x="SepalLength",
                            color="Name",
                            title="Sepal Length Distribution",
                        ),
                    ),
                    vm.Graph(
                        id="histogram_petal_length",
                        figure=px.histogram(
                            data_frame="iris_data",  # Use string reference for callbacks
                            x="PetalLength",
                            color="Name",
                            title="Petal Length Distribution",
                        ),
                    ),
                ],
            ),
        ],
    )

    # Build Vizro with url_base_pathname and server passed through kwargs
    # Vizro will create a Dash app internally with these settings
    print(f"DEBUG: Building Vizro with url_base_pathname='/vizro/' and server={server}")
    vizro_app = Vizro(
        url_base_pathname='/vizro/',
        server=server,
    ).build(dashboard)

    print(f"DEBUG: Vizro built successfully")
    print(f"DEBUG: vizro_app.dash: {vizro_app.dash}")
    print(f"DEBUG: Callbacks registered: {len(vizro_app.dash.callback_map)}")

    print("✅ Vizro app created and mounted at /vizro/")
    return vizro_app.dash


def _set_location_pathname(component, pathname="/"):
    """
    Recursively find dcc.Location component and set its pathname.

    This ensures Vizro routes to the correct initial page.

    Args:
        component: Dash component to search
        pathname: Pathname to set (default "/")

    Returns:
        bool: True if Location was found and set, False otherwise
    """
    from dash import dcc

    # Check if this component is a dcc.Location
    if isinstance(component, dcc.Location):
        component.pathname = pathname
        return True

    # Recursively search children
    if hasattr(component, "children") and component.children:
        children = component.children if isinstance(component.children, list) else [component.children]
        for child in children:
            # Skip string children
            if not isinstance(child, str):
                if _set_location_pathname(child, pathname):
                    return True

    return False
