import dash
from dash import html, dcc, Input, Output
import plotly.express as px
import pandas as pd
from sklearn.datasets import load_iris
import umap

# Load Iris dataset
iris = load_iris()
df = pd.DataFrame(iris.data, columns=iris.feature_names)
labels = iris.target

# Initialize the Dash app
app = dash.Dash(__name__)

# App layout
app.layout = html.Div(
    [
        html.H1("UMAP Visualization of Iris Dataset"),
        html.Label("Number of Neighbors:"),
        dcc.Slider(
            id="umap-neighbors",
            min=5,
            max=50,
            step=1,
            value=15,
            marks={i: str(i) for i in range(5, 51, 5)},
        ),
        html.Label("Min Distance:"),
        dcc.Slider(
            id="umap-min-dist",
            min=0.0,
            max=0.99,
            step=0.1,
            value=0.1,
            marks={i / 10: str(i / 10) for i in range(0, 10, 1)},
        ),
        dcc.Graph(id="umap-graph"),
    ]
)


# Callback to update the UMAP graph
@app.callback(
    Output("umap-graph", "figure"),
    [Input("umap-neighbors", "value"), Input("umap-min-dist", "value")],
)
def update_graph(n_neighbors, min_dist):
    reducer = umap.UMAP(n_neighbors=n_neighbors, min_dist=min_dist)
    embedding = reducer.fit_transform(df)
    fig = px.scatter(
        x=embedding[:, 0],
        y=embedding[:, 1],
        color=labels,
        title="UMAP Projection of the Iris Dataset",
        labels={"x": "Component 1", "y": "Component 2"},
        color_continuous_scale=px.colors.qualitative.Vivid,
    )
    return fig


# Run the app
if __name__ == "__main__":
    app.run_server(debug=True)
