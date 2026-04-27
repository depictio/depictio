"""Single-gene deep-dive explorer prototype — main entry point.

Run with:
    cd dev/gene-explorer
    uv sync
    uv run python app.py

Then open http://localhost:8057 in your browser.
"""

import dash_mantine_components as dmc
from callbacks import register_callbacks
from dash import Dash
from data import generate_all_data
from layout import create_layout


def main() -> None:
    """Initialize and run the Dash app."""
    app = Dash(
        __name__,
        external_stylesheets=dmc.styles.ALL,
    )

    data = generate_all_data(n_samples=60, n_genes=500)

    gene_options = [
        {"value": g, "label": g} for g in sorted(data["gene_names"])
    ]

    app.layout = create_layout(gene_options)
    register_callbacks(
        app,
        data["expression_df"],
        data["metadata_df"],
        data["de_results_df"],
        data["correlation_df"],
    )

    app.run(debug=True, port=8057)


if __name__ == "__main__":
    main()
