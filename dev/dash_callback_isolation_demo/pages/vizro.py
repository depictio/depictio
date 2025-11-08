import vizro.models as vm
import vizro.plotly.express as px
from vizro import Vizro
from vizro._vizro import model_manager

# Clear Vizro's global model registry to allow recreation on module reload
# This is necessary in dev mode when Flask's hot reload re-executes the module
model_manager._clear()
logger.info("Cleared Vizro model_manager for fresh initialization")

df = px.data.iris()

page = vm.Page(
    title="My first dashboard",
    components=[
        vm.Graph(figure=px.scatter(df, x="sepal_length", y="petal_width", color="species")),
        vm.Graph(figure=px.histogram(df, x="sepal_width", color="species")),
    ],
    controls=[
        vm.Filter(column="species"),
    ],
)

dashboard = vm.Dashboard(pages=[page])
app = Vizro(url_base_pathname="/vizro/", server=server).build(dashboard)
# Enable dev tools
app.enable_dev_tools(
    dev_tools_ui=True, dev_tools_serve_dev_bundles=True, dev_tools_hot_reload=dev_mode
)
