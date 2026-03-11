"""
Hi-C Contact Map Viewer — Dash application with DMC 2.0+ controls.

A standalone prototype for visualizing Hi-C contact maps using Plotly.
Supports loading .cool/.mcool files from nf-core/hic pipeline results
or generating synthetic demo data.

Run:
    python app.py
    python app.py --file /path/to/matrix.cool
    python app.py --file /path/to/matrix.mcool
"""

from __future__ import annotations

import argparse
import os

import dash_mantine_components as dmc
from dash import Dash, Input, Output, State, callback, dcc
from hic_data import (
    HiCData,
    generate_synthetic_hic,
    list_cool_chroms,
    list_mcool_resolutions,
    load_cool_matrix,
)
from hic_figure import DEFAULT_COLORSCALE, HIC_COLORSCALES, create_contact_map_figure

# ---------------------------------------------------------------------------
# App initialization
# ---------------------------------------------------------------------------

app = Dash(
    __name__,
    external_stylesheets=[dmc.styles.ALL],
    suppress_callback_exceptions=True,
)
app.title = "Hi-C Contact Map Viewer"


# ---------------------------------------------------------------------------
# Global state for file path (set via CLI args)
# ---------------------------------------------------------------------------

COOL_FILE_PATH: str | None = None


def get_initial_data() -> HiCData:
    """Load initial data from file or generate synthetic."""
    if COOL_FILE_PATH and os.path.exists(COOL_FILE_PATH):
        chroms = list_cool_chroms(COOL_FILE_PATH)
        # Pick first autosome
        chrom = next((c for c in chroms if c.startswith("chr") and c[3:].isdigit()), chroms[0])
        resolution = None
        if COOL_FILE_PATH.endswith(".mcool"):
            resolutions = list_mcool_resolutions(COOL_FILE_PATH)
            resolution = resolutions[len(resolutions) // 2]  # Mid resolution
        return load_cool_matrix(COOL_FILE_PATH, chrom, resolution)
    return generate_synthetic_hic()


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def build_controls() -> dmc.Paper:
    """Build the left sidebar with all controls."""
    return dmc.Paper(
        shadow="sm",
        p="md",
        radius="md",
        children=dmc.Stack(
            gap="md",
            children=[
                dmc.Title("Hi-C Contact Map", order=3),
                dmc.Text(
                    "Interactive viewer for chromosome conformation data", size="sm", c="dimmed"
                ),
                # Data source
                dmc.Divider(label="Data Source", labelPosition="center"),
                dmc.Select(
                    id="data-source-select",
                    label="Source",
                    data=[
                        {"value": "synthetic", "label": "Synthetic demo data"},
                        {"value": "file", "label": "Cool/mcool file"},
                    ],
                    value="file" if COOL_FILE_PATH else "synthetic",
                ),
                dmc.TextInput(
                    id="file-path-input",
                    label="File path",
                    placeholder="/path/to/matrix.cool or .mcool",
                    value=COOL_FILE_PATH or "",
                    style={"display": "block" if COOL_FILE_PATH else "none"},
                ),
                # Chromosome
                dmc.Divider(label="Region", labelPosition="center"),
                dmc.Select(
                    id="chrom-select",
                    label="Chromosome",
                    data=[],
                    searchable=True,
                ),
                # Resolution
                dmc.Select(
                    id="resolution-select",
                    label="Resolution",
                    data=[],
                ),
                # Region range
                dmc.Text("Genomic region (Mb)", size="sm", fw=500),
                dmc.Group(
                    gap="xs",
                    children=[
                        dmc.NumberInput(
                            id="region-start-input",
                            label="Start",
                            value=0,
                            min=0,
                            step=1,
                            suffix=" Mb",
                            w=120,
                        ),
                        dmc.NumberInput(
                            id="region-end-input",
                            label="End",
                            value=0,
                            min=0,
                            step=1,
                            suffix=" Mb",
                            w=120,
                        ),
                    ],
                ),
                # Visualization
                dmc.Divider(label="Visualization", labelPosition="center"),
                dmc.Select(
                    id="colorscale-select",
                    label="Color scale",
                    data=[{"value": k, "label": k} for k in HIC_COLORSCALES],
                    value=DEFAULT_COLORSCALE,
                ),
                dmc.Switch(
                    id="log-scale-switch",
                    label="Log scale",
                    checked=True,
                ),
                dmc.Text("Value cap percentile", size="sm", fw=500),
                dmc.Slider(
                    id="cap-percentile-slider",
                    value=99.5,
                    min=90,
                    max=100,
                    step=0.5,
                    marks=[
                        {"value": 90, "label": "90"},
                        {"value": 95, "label": "95"},
                        {"value": 100, "label": "100"},
                    ],
                ),
                # Synthetic data params
                dmc.Divider(
                    label="Synthetic Params", labelPosition="center", id="synthetic-divider"
                ),
                dmc.NumberInput(
                    id="n-bins-input",
                    label="Matrix size (bins)",
                    value=500,
                    min=50,
                    max=2000,
                    step=50,
                ),
                dmc.NumberInput(
                    id="n-tads-input",
                    label="Number of TADs",
                    value=8,
                    min=1,
                    max=30,
                    step=1,
                ),
                dmc.NumberInput(
                    id="n-loops-input",
                    label="Number of loops",
                    value=5,
                    min=0,
                    max=20,
                    step=1,
                ),
                # Load button
                dmc.Button(
                    "Render Contact Map",
                    id="render-button",
                    fullWidth=True,
                    variant="filled",
                    size="md",
                    mt="md",
                ),
            ],
        ),
    )


def build_layout() -> dmc.MantineProvider:
    """Build the full application layout."""
    return dmc.MantineProvider(
        forceColorScheme="light",
        children=[
            dcc.Store(id="hic-data-store", data=None),
            dmc.Container(
                fluid=True,
                p="md",
                children=[
                    dmc.Grid(
                        gutter="md",
                        children=[
                            # Left controls
                            dmc.GridCol(
                                span=3,
                                children=build_controls(),
                            ),
                            # Right: contact map
                            dmc.GridCol(
                                span=9,
                                children=dmc.Paper(
                                    shadow="sm",
                                    p="md",
                                    radius="md",
                                    children=[
                                        dcc.Loading(
                                            children=dcc.Graph(
                                                id="contact-map-graph",
                                                config={
                                                    "displayModeBar": True,
                                                    "modeBarButtonsToAdd": [
                                                        "drawrect",
                                                        "eraseshape",
                                                    ],
                                                    "scrollZoom": True,
                                                    "displaylogo": False,
                                                },
                                                style={"height": "80vh"},
                                            ),
                                            type="circle",
                                        ),
                                        # Info bar
                                        dmc.Group(
                                            mt="xs",
                                            gap="lg",
                                            children=[
                                                dmc.Text(id="info-text", size="sm", c="dimmed"),
                                            ],
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


app.layout = build_layout()


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


@callback(
    Output("file-path-input", "style"),
    Output("synthetic-divider", "style"),
    Output("n-bins-input", "style"),
    Output("n-tads-input", "style"),
    Output("n-loops-input", "style"),
    Input("data-source-select", "value"),
)
def toggle_source_controls(source):
    """Show/hide controls based on data source selection."""
    is_file = source == "file"
    file_style = {"display": "block"} if is_file else {"display": "none"}
    synth_style = {"display": "none"} if is_file else {"display": "block"}
    return file_style, synth_style, synth_style, synth_style, synth_style


@callback(
    Output("chrom-select", "data"),
    Output("chrom-select", "value"),
    Output("resolution-select", "data"),
    Output("resolution-select", "value"),
    Input("data-source-select", "value"),
    Input("file-path-input", "value"),
)
def update_metadata(source, file_path):
    """Update chromosome and resolution dropdowns based on data source."""
    if source == "file" and file_path and os.path.exists(file_path):
        chroms = list_cool_chroms(file_path)
        chrom_data = [{"value": c, "label": c} for c in chroms]
        default_chrom = next(
            (c for c in chroms if c.startswith("chr") and c[3:].isdigit()), chroms[0]
        )

        res_data = []
        default_res = None
        if file_path.endswith(".mcool"):
            resolutions = list_mcool_resolutions(file_path)
            res_data = [{"value": str(r), "label": _format_res(r)} for r in resolutions]
            default_res = str(resolutions[len(resolutions) // 2])

        return chrom_data, default_chrom, res_data, default_res

    # Synthetic: provide standard chromosome list
    chroms = [f"chr{i}" for i in range(1, 23)] + ["chrX"]
    chrom_data = [{"value": c, "label": c} for c in chroms]
    res_data = [
        {"value": str(r), "label": _format_res(r)}
        for r in [10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]
    ]
    return chrom_data, "chr1", res_data, "50000"


@callback(
    Output("contact-map-graph", "figure"),
    Output("info-text", "children"),
    Input("render-button", "n_clicks"),
    State("data-source-select", "value"),
    State("file-path-input", "value"),
    State("chrom-select", "value"),
    State("resolution-select", "value"),
    State("region-start-input", "value"),
    State("region-end-input", "value"),
    State("colorscale-select", "value"),
    State("log-scale-switch", "checked"),
    State("cap-percentile-slider", "value"),
    State("n-bins-input", "value"),
    State("n-tads-input", "value"),
    State("n-loops-input", "value"),
    prevent_initial_call=False,
)
def render_contact_map(
    n_clicks,
    source,
    file_path,
    chrom,
    resolution,
    region_start,
    region_end,
    colorscale,
    log_scale,
    cap_percentile,
    n_bins,
    n_tads,
    n_loops,
):
    """Main callback: load data and render the contact map figure."""
    try:
        if source == "file" and file_path and os.path.exists(file_path):
            res = int(resolution) if resolution else None
            data = load_cool_matrix(file_path, chrom or "chr1", res)
        else:
            data = generate_synthetic_hic(
                n_bins=int(n_bins or 500),
                resolution=int(resolution or 50_000),
                chrom=chrom or "chr1",
                n_tads=int(n_tads or 8),
                n_loops=int(n_loops or 5),
            )

        # Region in base pairs (input is in Mb)
        rs = int(region_start * 1_000_000) if region_start else None
        re = int(region_end * 1_000_000) if region_end else None
        if rs == 0 and re == 0:
            rs, re = None, None

        fig = create_contact_map_figure(
            data,
            colorscale=colorscale or DEFAULT_COLORSCALE,
            log_scale=bool(log_scale),
            value_cap_percentile=float(cap_percentile or 99.5),
            region_start=rs,
            region_end=re,
        )

        n = data.matrix.shape[0]
        res_label = _format_res(data.resolution)
        info = (
            f"Matrix: {n}×{n} bins | Resolution: {res_label} | {data.chrom}:{data.start}-{data.end}"
        )

        return fig, info

    except Exception as e:
        import traceback

        traceback.print_exc()
        import plotly.graph_objects as go

        fig = go.Figure()
        fig.add_annotation(
            text=f"Error: {e}",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=16, color="red"),
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
        )
        return fig, f"Error: {e}"


def _format_res(res: int) -> str:
    """Format resolution for display."""
    if res >= 1_000_000:
        return f"{res // 1_000_000} Mb"
    if res >= 1_000:
        return f"{res // 1_000} kb"
    return f"{res} bp"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """CLI entry point."""
    global COOL_FILE_PATH
    parser = argparse.ArgumentParser(description="Hi-C Contact Map Viewer")
    parser.add_argument("--file", "-f", help="Path to .cool or .mcool file")
    parser.add_argument("--port", "-p", type=int, default=8050, help="Port (default: 8050)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    if args.file:
        COOL_FILE_PATH = args.file

    app.run(debug=args.debug, port=args.port)


if __name__ == "__main__":
    main()
