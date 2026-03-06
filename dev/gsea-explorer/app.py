"""GSEA Explorer prototype — main entry point.

Run with:
    cd dev/gsea-explorer
    uv sync
    uv run python app.py

Then open http://localhost:8058 in your browser.
"""

import dash_mantine_components as dmc
from callbacks import register_callbacks
from dash import Dash
from data import generate_gsea_data
from layout import create_layout


def main() -> None:
    """Initialize and run the Dash app."""
    app = Dash(
        __name__,
        external_stylesheets=dmc.styles.ALL,
    )

    gsea_data = generate_gsea_data()
    app.layout = create_layout()
    register_callbacks(
        app,
        enrichment_df=gsea_data["enrichment_df"],
        ranked_genes=gsea_data["ranked_genes"],
        expression_df=gsea_data["expression_df"],
        sample_meta_df=gsea_data["sample_meta_df"],
    )

    app.run(debug=True, port=8058)


if __name__ == "__main__":
    main()
