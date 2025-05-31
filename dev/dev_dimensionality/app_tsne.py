import dash
from dash import html, dcc, Input, Output
import plotly.express as px
import pandas as pd
from sklearn.datasets import load_iris
from sklearn.manifold import TSNE

# Load Iris dataset
iris = load_iris()
df = pd.DataFrame(iris.data, columns=iris.feature_names)
print(df)
labels = iris.target

# Initialize the Dash app
app = dash.Dash(__name__)

# App layout
app.layout = html.Div(
    [
        html.H1("t-SNE Visualization of Iris Dataset"),
        html.Label("Perplexity:"),
        dcc.Slider(
            id="tsne-perplexity",
            min=5,
            max=50,
            step=1,
            value=30,
            marks={i: str(i) for i in range(5, 51, 5)},
        ),
        html.Label("Learning Rate:"),
        dcc.Slider(
            id="tsne-learning-rate",
            min=10,
            max=200,
            step=10,
            value=100,
            marks={i: str(i) for i in range(10, 201, 10)},
        ),
        dcc.Graph(id="tsne-graph"),
    ]
)


# Callback to update the t-SNE graph
@app.callback(
    Output("tsne-graph", "figure"),
    [Input("tsne-perplexity", "value"), Input("tsne-learning-rate", "value")],
)
def update_graph(perplexity, learning_rate):
    tsne = TSNE(n_components=2, perplexity=perplexity, learning_rate=learning_rate, random_state=42)
    tsne_results = tsne.fit_transform(df)
    fig = px.scatter(
        x=tsne_results[:, 0],
        y=tsne_results[:, 1],
        color=labels,
        title="t-SNE Projection of the Iris Dataset",
        labels={"x": "Component 1", "y": "Component 2"},
        color_continuous_scale=px.colors.qualitative.Vivid,
    )
    return fig


# Run the app
if __name__ == "__main__":
    app.run_server(debug=True)
