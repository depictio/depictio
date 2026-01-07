"""
Quick script to inspect Vizro app structure.
"""
import pandas as pd
import vizro.models as vm
import vizro.plotly.express as px
from dash import Dash
from vizro import Vizro
from vizro.managers import data_manager


# Create minimal dashboard
iris_df = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/iris.csv")
data_manager["iris_data"] = iris_df

dashboard = vm.Dashboard(
    pages=[
        vm.Page(
            title="Test",
            path="/",
            components=[
                vm.Graph(
                    id="scatter",
                    figure=px.scatter(
                        data_frame="iris_data",
                        x="SepalLength",
                        y="SepalWidth",
                        color="Name",
                    ),
                )
            ],
        )
    ],
)

# Create host app
host_app = Dash(__name__, suppress_callback_exceptions=True)

# Monkey-patch
import vizro._vizro
original_dash_class = vizro._vizro.dash.Dash

def dash_factory(*args, **kwargs):
    return host_app

vizro._vizro.dash.Dash = dash_factory

try:
    # Build Vizro
    vizro = Vizro()
    vizro_app = vizro.build(dashboard)

    print("=" * 60)
    print("VIZRO APP ATTRIBUTES")
    print("=" * 60)

    # Inspect vizro_app
    print(f"\nvizro_app type: {type(vizro_app)}")
    print(f"\nvizro_app attributes:")
    for attr in dir(vizro_app):
        if not attr.startswith('__'):
            print(f"  - {attr}")

    # Check for layout-related attributes
    print("\n" + "=" * 60)
    print("LAYOUT-RELATED ATTRIBUTES")
    print("=" * 60)

    if hasattr(vizro_app, '_layout'):
        print(f"\nvizro_app._layout: {type(vizro_app._layout)}")
    else:
        print("\nvizro_app._layout: NOT FOUND")

    if hasattr(vizro_app, 'layout'):
        print(f"vizro_app.layout: {type(vizro_app.layout)}")
    else:
        print("vizro_app.layout: NOT FOUND")

    if hasattr(vizro_app, '_dashboard'):
        print(f"vizro_app._dashboard: {type(vizro_app._dashboard)}")
    else:
        print("vizro_app._dashboard: NOT FOUND")

    if hasattr(vizro_app, 'dash'):
        print(f"vizro_app.dash: {type(vizro_app.dash)}")
        print(f"vizro_app.dash is host_app: {vizro_app.dash is host_app}")

        # Check what layout is on the dash app
        print(f"\nvizro_app.dash.layout type: {type(vizro_app.dash.layout)}")
        if callable(vizro_app.dash.layout):
            print("  → Layout is callable")
        else:
            print("  → Layout is a component")

    print("\n" + "=" * 60)
    print("TRYING TO GET FULL LAYOUT")
    print("=" * 60)

    # Try to get the full layout that Vizro created
    if callable(vizro_app.dash.layout):
        layout = vizro_app.dash.layout()
        print(f"\nCalling vizro_app.dash.layout():")
        print(f"  Result type: {type(layout)}")
        print(f"  Has children: {hasattr(layout, 'children')}")

        # Try to find dcc.Location
        from dash import dcc
        def find_location(component, depth=0):
            if depth > 3:
                return None
            if isinstance(component, dcc.Location):
                return component
            if hasattr(component, 'children'):
                children = component.children
                if isinstance(children, list):
                    for child in children:
                        result = find_location(child, depth+1)
                        if result:
                            return result
                elif children and not isinstance(children, str):
                    return find_location(children, depth+1)
            return None

        location = find_location(layout)
        if location:
            print(f"\n  Found dcc.Location:")
            print(f"    id: {location.id}")
            print(f"    pathname: {location.pathname}")

finally:
    vizro._vizro.dash.Dash = original_dash_class

print("\n" + "=" * 60)
