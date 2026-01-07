"""
Extract Vizro app into standard Dash app - Minimal Integration
"""

import pandas as pd
import vizro.models as vm
import vizro.plotly.express as px
from dash import Dash
from vizro import Vizro
from vizro.managers import data_manager

# Load data into Vizro's data manager
data_manager["iris_data"] = pd.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/iris-id.csv"
)

# Create Vizro dashboard model
model = vm.Dashboard(
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

# Create standard Dash app
dash_app = Dash(__name__, suppress_callback_exceptions=True)

# Build Vizro with the dashboard model
vizro_app = Vizro().build(model)

# Extract the layout from the built Vizro app
dash_app.layout = vizro_app.dash.layout

# Extract callbacks (they're registered on vizro_app.dash)
# Since Vizro creates its own Dash instance, we need to use it directly
# The simplest approach is to just use vizro_app.dash as our server

if __name__ == "__main__":
    # Run the Vizro app's dash instance (which has layout + callbacks)
    vizro_app.dash.run(port=8051, debug=True)
