"""Variant Inspector prototype — main entry point.

Run with:
    cd dev/variant-inspector
    uv sync
    uv run python app.py

Then open http://localhost:8065 in your browser.
"""

import dash_mantine_components as dmc
from callbacks import register_callbacks
from dash import Dash
from data import generate_coverage_data, generate_lineage_data, generate_variant_data
from layout import create_layout


def main() -> None:
    """Initialize and run the Dash app."""
    app = Dash(
        __name__,
        external_stylesheets=dmc.styles.ALL,
    )

    variant_df = generate_variant_data(n_variants=200)
    coverage_df = generate_coverage_data()
    lineage_df = generate_lineage_data()

    app.layout = create_layout()
    register_callbacks(app, variant_df, coverage_df, lineage_df)

    app.run(debug=True, port=8065)


if __name__ == "__main__":
    main()
