"""Peak Explorer analysis module — main entry point.

Run with:
    cd dev/peak-explorer
    uv sync
    uv run python app.py

Then open http://localhost:8063 in your browser.
"""

import dash_mantine_components as dmc
from callbacks import register_callbacks
from dash import Dash
from data import generate_peak_data
from layout import create_layout


def main() -> None:
    """Initialize and run the Dash app."""
    app = Dash(
        __name__,
        external_stylesheets=dmc.styles.ALL,
    )

    peak_df = generate_peak_data(n_peaks=3000)

    app.layout = create_layout()
    register_callbacks(app, peak_df)

    app.run(debug=True, port=8063)


if __name__ == "__main__":
    main()
