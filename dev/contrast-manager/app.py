"""DE contrast manager prototype — main entry point.

Run with:
    cd dev/contrast-manager
    uv sync
    uv run python app.py

Then open http://localhost:8059 in your browser.
"""

import dash_mantine_components as dmc
from callbacks import register_callbacks
from dash import Dash
from data import generate_data
from layout import create_layout


def main() -> None:
    """Initialize and run the Dash app."""
    app = Dash(
        __name__,
        external_stylesheets=dmc.styles.ALL,
    )

    expression_df, metadata_df, de_results = generate_data(
        n_samples=60, n_genes=500
    )
    app.layout = create_layout()
    register_callbacks(app, expression_df, metadata_df, de_results)

    app.run(debug=True, port=8059)


if __name__ == "__main__":
    main()
