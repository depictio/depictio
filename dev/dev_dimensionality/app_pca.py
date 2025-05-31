import dash
from dash import html, dcc, Input, Output
import plotly.express as px
import pandas as pd
from sklearn.datasets import load_iris
from sklearn.decomposition import PCA

# Load Iris dataset
iris = load_iris()
df = pd.DataFrame(iris.data, columns=iris.feature_names)
labels = iris.target

# Initialize the Dash app
app = dash.Dash(__name__)

# App layout
app.layout = html.Div(
    [
        html.H1("PCA Visualization of Iris Dataset"),
        html.Label("Number of Components:"),
        dcc.Slider(
            id="pca-components",
            min=2,
            max=len(df.columns),
            step=1,
            value=2,
            marks={i: str(i) for i in range(2, len(df.columns) + 1)},
        ),
        dcc.Graph(id="pca-graph"),
    ]
)


# Callback to update the PCA graph
@app.callback(Output("pca-graph", "figure"), [Input("pca-components", "value")])
def update_graph(n_components):
    pca = PCA(n_components=n_components)
    components = pca.fit_transform(df)
    explained_variance = pca.explained_variance_ratio_

    # For a 2D plot, we'll take the first two principal components
    if n_components >= 2:
        fig = px.scatter(
            x=components[:, 0],
            y=components[:, 1],
            color=labels,
            title=f"PCA Projection of the Iris Dataset (Explained Variance: {explained_variance[0]:.2f}, {explained_variance[1]:.2f})",
            labels={"x": "PC 1", "y": "PC 2"},
            color_continuous_scale=px.colors.qualitative.Vivid,
        )
    else:  # Fallback for 1D plot
        fig = px.scatter(
            x=components[:, 0],
            y=[0] * len(components),
            color=labels,
            title=f"PCA Projection of the Iris Dataset (Explained Variance: {explained_variance[0]:.2f})",
            labels={"x": "PC 1", "y": ""},
            color_continuous_scale=px.colors.qualitative.Vivid,
        )

    return fig


# Run the app
if __name__ == "__main__":
    app.run_server(debug=True)
