"""Taxonomy Browser prototype — main entry point.

Run with:
    cd dev/taxonomy-browser
    uv sync
    uv run python app.py

Then open http://localhost:8064 in your browser.
"""

import dash_mantine_components as dmc
from callbacks import register_callbacks
from dash import Dash
from data import generate_abundance_data
from layout import create_layout


def main() -> None:
    """Initialize and run the Dash app."""
    app = Dash(
        __name__,
        external_stylesheets=dmc.styles.ALL,
    )

    abundance_df, taxonomy_df, metadata_df = generate_abundance_data()

    app.layout = create_layout()
    register_callbacks(app, abundance_df, taxonomy_df, metadata_df)

    app.run(debug=True, port=8064)


if __name__ == "__main__":
    main()
