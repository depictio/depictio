"""PCA / UMAP / t-SNE explorer prototype — main entry point.

Run with:
    cd dev/dimred-explorer
    uv sync
    uv run python app.py

Then open http://localhost:8056 in your browser.
"""

import dash_mantine_components as dmc
from callbacks import register_callbacks
from dash import Dash
from data import generate_expression_data
from layout import create_layout


def main() -> None:
    """Initialize and run the Dash app."""
    app = Dash(
        __name__,
        external_stylesheets=dmc.styles.ALL,
    )

    expression_df, metadata_df = generate_expression_data(
        n_samples=60, n_genes=500, n_variable_genes=100
    )
    app.layout = create_layout()
    register_callbacks(app, expression_df, metadata_df)

    app.run(debug=True, port=8056)


if __name__ == "__main__":
    main()
