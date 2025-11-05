"""
Pure Standalone Vizro App - No Dash Integration

Just Vizro on its own, the way it's meant to be used.
"""

import pandas as pd
import vizro.models as vm  # type: ignore[import-untyped]
import vizro.plotly.express as px  # type: ignore[import-untyped]
from vizro import Vizro  # type: ignore[import-untyped]
from vizro.managers import data_manager  # type: ignore[import-untyped]

# Load data
iris_df = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/iris.csv")
data_manager["iris_data"] = iris_df

print(f"📊 Loaded {len(iris_df)} rows")

# Create Vizro dashboard
dashboard = vm.Dashboard(
    pages=[
        vm.Page(
            title="Iris Analysis",
            path="/",
            components=[
                vm.Card(
                    text="""
                    # Iris Dataset Analysis

                    Explore the classic Iris dataset with interactive visualizations.
                    Use the species filter to focus on specific flower types.
                    """
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
                        title="Petal Dimensions",
                    ),
                ),
            ],
            controls=[vm.Filter(column="Name", selector=vm.Dropdown(multi=True))],
        )
    ],
    title="Vizro Iris Dashboard",
)

# Build and run
app = Vizro().build(dashboard)

if __name__ == "__main__":
    app.run(port=8051, debug=True)
