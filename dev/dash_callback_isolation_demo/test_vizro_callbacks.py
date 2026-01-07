"""
Quick test to see if Vizro registers callbacks at all.
"""
import pandas as pd
import vizro.models as vm
import vizro.plotly.express as px
from vizro import Vizro
from vizro.managers import data_manager

# Load data
iris_df = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/iris.csv")
data_manager["iris_data"] = iris_df

# Create simple dashboard
dashboard = vm.Dashboard(
    pages=[
        vm.Page(
            title="Test",
            components=[
                vm.Graph(
                    figure=px.scatter(
                        data_frame="iris_data",
                        x="SepalLength",
                        y="SepalWidth",
                        color="Name",
                    ),
                ),
            ],
            controls=[
                vm.Filter(column="Name"),
            ],
        ),
    ],
)

# Build and check callbacks
print("Building Vizro...")
vizro_app = Vizro().build(dashboard)
print(f"Callbacks registered: {len(vizro_app.dash.callback_map)}")
print(f"Callback IDs: {list(vizro_app.dash.callback_map.keys())}")
