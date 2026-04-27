"""Progressive Filter prototype — main entry point.

Run with:
    cd dev/progressive-filter
    uv sync
    uv run python app.py

Then open http://localhost:8060 in your browser.
"""

import dash_mantine_components as dmc
from callbacks import register_callbacks
from dash import Dash
from data import generate_de_data
from layout import create_layout


def main() -> None:
    """Initialize and run the Dash app."""
    app = Dash(
        __name__,
        external_stylesheets=dmc.styles.ALL,
    )

    df = generate_de_data(n_genes=2000)
    app.layout = create_layout()
    register_callbacks(app, df)

    app.run(debug=True, port=8060)


if __name__ == "__main__":
    main()
