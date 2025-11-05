"""
Embed Vizro layout into your own Dash app - Layout extraction only

This shows how to:
1. Create YOUR OWN Dash app
2. Build Vizro and extract its layout
3. Use Vizro's layout in YOUR app
4. Run YOUR Dash app (not Vizro's)
"""

import pandas as pd
import vizro.models as vm
import vizro.plotly.express as px
from dash import Dash, html
from vizro import Vizro
from vizro.managers import data_manager

# Load data into Vizro's data manager
data_manager["iris_data"] = pd.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/iris-id.csv"
)

# Create Vizro dashboard model
vizro_model = vm.Dashboard(
    pages=[
        vm.Page(
            components=[
                vm.Graph(
                    id="scatter_sepal",
                    figure=px.scatter(
                        data_frame="iris_data",
                        x="sepal_length",
                        y="sepal_width",
                        color="species",
                    ),
                    title="Sepal Dimensions",
                ),
                vm.Graph(
                    id="scatter_petal",
                    figure=px.scatter(
                        data_frame="iris_data",
                        x="petal_length",
                        y="petal_width",
                        color="species",
                    ),
                    title="Petal Dimensions",
                ),
            ],
            title="Iris Analysis",
            controls=[
                vm.Filter(
                    id="species_filter",
                    column="species",
                    targets=["scatter_sepal", "scatter_petal"],
                    selector=vm.Dropdown(multi=True),
                )
            ],
        )
    ],
    theme="vizro_dark",
    title="Iris Dashboard",
)

print("=" * 60)
print("Creating YOUR Dash app (not Vizro's)")
print("=" * 60)

# 1. Create YOUR OWN Dash app
my_dash_app = Dash(__name__, suppress_callback_exceptions=True)

print(f"✓ Your Dash app created (id: {id(my_dash_app)})")
print(f"  Callbacks before Vizro: {len(my_dash_app.callback_map)}")

# 2. Monkey-patch Vizro to use YOUR app
import vizro._vizro

original_dash = vizro._vizro.dash.Dash
vizro._vizro.dash.Dash = lambda *a, **k: my_dash_app

# 3. Build Vizro - this registers callbacks on YOUR app
vizro_built = Vizro().build(vizro_model)

print(f"✓ Vizro built (callbacks registered on YOUR app)")
print(f"  Callbacks after build: {len(my_dash_app.callback_map)}")

# 4. CRITICAL: Activate callbacks
my_dash_app._setup_server()

print(f"✓ Callbacks activated: {len(my_dash_app.callback_map)}")

# 5. Restore Dash class
vizro._vizro.dash.Dash = original_dash

# 6. Extract Vizro's layout
vizro_layout = vizro_built.dash.layout

print(f"✓ Extracted Vizro layout: {type(vizro_layout).__name__}")

# 7. Set pathname on dcc.Location to "/"
from dash import dcc


def set_pathname(component):
    if isinstance(component, dcc.Location):
        component.pathname = "/"
        print(f"✓ Set pathname='/' on {component.id}")
        return True
    if hasattr(component, "children") and component.children:
        children = component.children if isinstance(component.children, list) else [component.children]
        for child in children:
            if not isinstance(child, str) and set_pathname(child):
                return True
    return False


set_pathname(vizro_layout)

# 8. Add a header to YOUR app and include Vizro content
my_dash_app.layout = html.Div(
    [
        html.Div(
            [
                html.H1("My Dash App", style={"color": "#2c3e50", "margin": "0"}),
                html.P("Vizro dashboard embedded below", style={"color": "#7f8c8d", "margin": "10px 0"}),
                html.Hr(style={"margin": "20px 0"}),
            ],
            style={"padding": "20px", "backgroundColor": "#ecf0f1"},
        ),
        html.Div(vizro_layout, style={"padding": "20px"}),
    ]
)

print("✓ Layout set on YOUR Dash app (with custom header)")
print("=" * 60)
print("Running YOUR Dash app on http://localhost:8051")
print("=" * 60)

if __name__ == "__main__":
    # Run YOUR Dash app (not vizro_app)
    my_dash_app.run(port=8051, debug=True)
