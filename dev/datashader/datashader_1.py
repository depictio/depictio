import holoviews as hv
import numpy as np
import pandas as pd
from dash import Dash, html
from holoviews.operation.datashader import datashade
from holoviews.plotting.plotly.dash import to_dash
from plotly.data import iris

# Load iris dataset and replicate with noise to create large dataset
df_original = iris()[["sepal_length", "sepal_width", "petal_length", "petal_width"]]
df = pd.concat([
df_original + np.random.randn(*df_original.shape) * 0.1
for i in range(10000)
])
dataset = hv.Dataset(df)

scatter = datashade(
hv.Scatter(dataset, kdims=["sepal_length"], vdims=["sepal_width"])
).opts(title="Datashader with %d points" % len(dataset))

app = Dash()
components = to_dash(
app, [scatter], reset_button=True
)

app.layout = html.Div(components.children)

if __name__ == "__main__":
    app.run(debug=True)