############ Imports ##############
import vizro.plotly.express as px
import vizro.models as vm
from vizro import Vizro
import pandas as pd
from vizro.managers import data_manager


####### Data Manager Settings #####
data_manager["iris_data"] = pd.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/iris-id.csv"
)

########### Model code ############
model = vm.Dashboard(
    pages=[
        vm.Page(
            components=[
                vm.Graph(
                    id="scatter_sepal",
                    type="graph",
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
                    type="graph",
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
                    type="filter",
                    column="species",
                    targets=["scatter_sepal", "scatter_petal"],
                    selector=vm.Dropdown(type="dropdown", multi=True),
                )
            ],
        )
    ],
    theme="vizro_dark",
    title="Iris Dashboard",
)

if __name__ == "__main__":
    Vizro().build(model).run(port=8051, debug=True)
