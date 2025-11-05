"""
Minimalistic Vizro Integration - Bare Bones

Just the absolute essentials to get Vizro working within a host Dash app.
"""

import pandas as pd
import vizro.models as vm  # type: ignore[import-untyped]
import vizro.plotly.express as px  # type: ignore[import-untyped]
from dash import Dash
from vizro import Vizro  # type: ignore[import-untyped]
from vizro.managers import data_manager  # type: ignore[import-untyped]


# 1. Create host Dash app
print("Creating host Dash app...")
host_app = Dash(__name__, suppress_callback_exceptions=True)

# 2. Load data into Vizro's data manager
iris_df = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/iris.csv")
data_manager["iris_data"] = iris_df
print(f"Loaded {len(iris_df)} rows")

# 3. Create Vizro dashboard (minimal: 2 graphs + 1 filter)
dashboard = vm.Dashboard(
    pages=[
        vm.Page(
            title="Iris",
            path="/",
            components=[
                vm.Graph(
                    id="scatter1",
                    figure=px.scatter(
                        data_frame="iris_data",
                        x="SepalLength",
                        y="SepalWidth",
                        color="Name",
                    ),
                ),
                vm.Graph(
                    id="scatter2",
                    figure=px.scatter(
                        data_frame="iris_data",
                        x="PetalLength",
                        y="PetalWidth",
                        color="Name",
                    ),
                ),
            ],
            controls=[vm.Filter(column="Name", selector=vm.Dropdown(multi=True))],
        )
    ],
)

# 4. Monkey-patch Vizro to use host app
import vizro._vizro

original_dash = vizro._vizro.dash.Dash
vizro._vizro.dash.Dash = lambda *a, **k: host_app

# 5. Build Vizro (this registers callbacks on host_app)
print(f"Callbacks before: {len(host_app.callback_map)}")
vizro_app = Vizro().build(dashboard)
print(f"Callbacks after build: {len(host_app.callback_map)}")

# 6. CRITICAL: Activate global callbacks
host_app._setup_server()
print(f"Callbacks after _setup_server: {len(host_app.callback_map)}")

# 7. Restore Dash class
vizro._vizro.dash.Dash = original_dash

# 8. Get Vizro's full layout (already set on host_app by build())
# The key insight: vizro_app.dash.layout IS the complete Vizro layout
vizro_layout = vizro_app.dash.layout
print(f"Vizro layout type: {type(vizro_layout).__name__}")

# 9. CRITICAL: Set pathname on dcc.Location to "/"
from dash import dcc


def set_pathname(component):
    """Find dcc.Location and set pathname to /."""
    if isinstance(component, dcc.Location):
        component.pathname = "/"
        print(f"Set pathname to / on {component.id}")
        return True
    if hasattr(component, "children") and component.children:
        children = component.children if isinstance(component.children, list) else [component.children]
        for child in children:
            if not isinstance(child, str) and set_pathname(child):
                return True
    return False


set_pathname(vizro_layout)

# 10. Set this as the host app's layout
host_app.layout = vizro_layout

print("\n✅ Vizro integrated successfully")
print("🌐 Starting on http://localhost:8051\n")

# 11. Run
if __name__ == "__main__":
    host_app.run(debug=True, port=8051)
