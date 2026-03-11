"""
Hi-C Contact Map Browser — JBrowse-style Dash application.

A genome browser-style viewer for Hi-C contact maps with:
- Navigation bar: chromosome, position, zoom in/out, pan left/right
- Hi-C heatmap with optional upper-triangle view
- Linear genome ruler track below the heatmap
- Interactive zoom via Plotly relayout events

Run:
    python app.py
    python app.py --file /path/to/matrix.cool
    python app.py --file /path/to/matrix.mcool
"""

from __future__ import annotations

import argparse
import os

import dash_mantine_components as dmc
from dash import Dash, Input, Output, State, callback, ctx, dcc
from hic_data import (
    generate_synthetic_hic,
    list_cool_chroms,
    list_mcool_resolutions,
    load_cool_matrix,
)
from hic_figure import DEFAULT_COLORSCALE, HIC_COLORSCALES, create_browser_figure

# ---------------------------------------------------------------------------
# App initialization
# ---------------------------------------------------------------------------

app = Dash(
    __name__,
    external_stylesheets=[dmc.styles.ALL],
    suppress_callback_exceptions=True,
)
app.title = "Hi-C Contact Map Browser"

COOL_FILE_PATH: str | None = None

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def build_navbar() -> dmc.Paper:
    """JBrowse-style navigation bar."""
    return dmc.Paper(
        shadow="xs",
        p="xs",
        radius="md",
        mb="sm",
        children=dmc.Group(
            gap="sm",
            wrap="nowrap",
            children=[
                # Data source
                dmc.Select(
                    id="data-source-select",
                    data=[
                        {"value": "synthetic", "label": "Synthetic"},
                        {"value": "file", "label": "File"},
                    ],
                    value="file" if COOL_FILE_PATH else "synthetic",
                    w=110,
                    size="sm",
                ),
                dmc.TextInput(
                    id="file-path-input",
                    placeholder="path/to/file.cool",
                    value=COOL_FILE_PATH or "",
                    w=200,
                    size="sm",
                    style={"display": "block" if COOL_FILE_PATH else "none"},
                ),
                dmc.Divider(orientation="vertical", h=30),
                # Chromosome
                dmc.Select(
                    id="chrom-select",
                    data=[],
                    searchable=True,
                    w=130,
                    size="sm",
                    placeholder="Chromosome",
                ),
                # Resolution (for mcool)
                dmc.Select(
                    id="resolution-select",
                    data=[],
                    w=100,
                    size="sm",
                    placeholder="Resolution",
                ),
                dmc.Divider(orientation="vertical", h=30),
                # Position input
                dmc.TextInput(
                    id="position-input",
                    placeholder="e.g. 50-100 (Mb)",
                    w=140,
                    size="sm",
                ),
                # Navigation buttons
                dmc.ActionIcon(
                    dmc.Text("⟪", size="lg", fw=700),
                    id="nav-far-left",
                    variant="light",
                    size="sm",
                ),
                dmc.ActionIcon(
                    dmc.Text("◀", size="sm"),
                    id="nav-left",
                    variant="light",
                    size="sm",
                ),
                dmc.ActionIcon(
                    dmc.Text("▶", size="sm"),
                    id="nav-right",
                    variant="light",
                    size="sm",
                ),
                dmc.ActionIcon(
                    dmc.Text("⟫", size="lg", fw=700),
                    id="nav-far-right",
                    variant="light",
                    size="sm",
                ),
                dmc.Divider(orientation="vertical", h=30),
                # Zoom buttons
                dmc.ActionIcon(
                    dmc.Text("−", size="lg", fw=700),
                    id="zoom-out",
                    variant="light",
                    color="blue",
                    size="sm",
                ),
                dmc.ActionIcon(
                    dmc.Text("+", size="lg", fw=700),
                    id="zoom-in",
                    variant="light",
                    color="blue",
                    size="sm",
                ),
                dmc.ActionIcon(
                    dmc.Text("⊞", size="lg"),
                    id="zoom-fit",
                    variant="light",
                    color="gray",
                    size="sm",
                ),
            ],
        ),
    )


def build_settings_drawer() -> dmc.Paper:
    """Collapsible settings panel below navbar."""
    return dmc.Paper(
        shadow="xs",
        p="xs",
        radius="md",
        mb="sm",
        children=dmc.Group(
            gap="md",
            wrap="nowrap",
            children=[
                dmc.Select(
                    id="colorscale-select",
                    label="Color",
                    data=[{"value": k, "label": k} for k in HIC_COLORSCALES],
                    value=DEFAULT_COLORSCALE,
                    w=140,
                    size="xs",
                ),
                dmc.Switch(
                    id="log-scale-switch",
                    label="Log scale",
                    checked=True,
                    size="xs",
                ),
                dmc.Switch(
                    id="upper-triangle-switch",
                    label="Upper triangle",
                    checked=False,
                    size="xs",
                ),
                dmc.NumberInput(
                    id="cap-percentile-input",
                    label="Cap %ile",
                    value=99.5,
                    min=90,
                    max=100,
                    step=0.5,
                    w=80,
                    size="xs",
                ),
                # Synthetic params (hidden when file mode)
                dmc.NumberInput(
                    id="n-bins-input",
                    label="Bins",
                    value=500,
                    min=50,
                    max=2000,
                    step=50,
                    w=80,
                    size="xs",
                    style={"display": "none"},
                ),
                dmc.NumberInput(
                    id="n-tads-input",
                    label="TADs",
                    value=8,
                    min=1,
                    max=30,
                    step=1,
                    w=70,
                    size="xs",
                    style={"display": "none"},
                ),
                dmc.NumberInput(
                    id="n-loops-input",
                    label="Loops",
                    value=5,
                    min=0,
                    max=20,
                    step=1,
                    w=70,
                    size="xs",
                    style={"display": "none"},
                ),
            ],
        ),
    )


def build_layout() -> dmc.MantineProvider:
    """Full application layout."""
    return dmc.MantineProvider(
        forceColorScheme="light",
        children=[
            # Stores
            dcc.Store(id="view-store", data={"start_bp": 0, "end_bp": 0, "chrom_length": 0}),
            dcc.Store(id="data-loaded-store", data=False),
            dmc.Container(
                fluid=True,
                p="sm",
                children=[
                    # Navigation bar
                    build_navbar(),
                    # Settings bar
                    build_settings_drawer(),
                    # Main viewer
                    dmc.Paper(
                        shadow="sm",
                        p="xs",
                        radius="md",
                        children=[
                            dcc.Loading(
                                children=dcc.Graph(
                                    id="browser-graph",
                                    config={
                                        "displayModeBar": True,
                                        "modeBarButtonsToRemove": [
                                            "lasso2d",
                                            "select2d",
                                        ],
                                        "scrollZoom": True,
                                        "displaylogo": False,
                                        "doubleClick": "reset",
                                    },
                                    style={"height": "82vh"},
                                ),
                                type="circle",
                            ),
                            # Info bar
                            dmc.Group(
                                mt="xs",
                                px="sm",
                                gap="lg",
                                children=[
                                    dmc.Text(id="info-text", size="xs", c="dimmed"),
                                    dmc.Text(id="position-text", size="xs", c="dimmed"),
                                ],
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
    Output("n-bins-input", "style"),
    Output("n-tads-input", "style"),
    Output("n-loops-input", "style"),
    Input("data-source-select", "value"),
)
def toggle_source(source):
    """Show/hide file vs synthetic controls."""
    is_file = source == "file"
    return (
        {"display": "block"} if is_file else {"display": "none"},
        {"display": "none"} if is_file else {"display": "block"},
        {"display": "none"} if is_file else {"display": "block"},
        {"display": "none"} if is_file else {"display": "block"},
    )


@callback(
    Output("chrom-select", "data"),
    Output("chrom-select", "value"),
    Output("resolution-select", "data"),
    Output("resolution-select", "value"),
    Input("data-source-select", "value"),
    Input("file-path-input", "value"),
)
def update_metadata(source, file_path):
    """Populate chromosome and resolution dropdowns."""
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
            res_data = [{"value": str(r), "label": _fmt_res(r)} for r in resolutions]
            default_res = str(resolutions[len(resolutions) // 2])
        return chrom_data, default_chrom, res_data, default_res

    chroms = [f"chr{i}" for i in range(1, 23)] + ["chrX"]
    chrom_data = [{"value": c, "label": c} for c in chroms]
    res_data = [
        {"value": str(r), "label": _fmt_res(r)}
        for r in [10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]
    ]
    return chrom_data, "chr1", res_data, "50000"


@callback(
    Output("browser-graph", "figure"),
    Output("info-text", "children"),
    Output("position-text", "children"),
    Output("view-store", "data"),
    Output("position-input", "value"),
    # Triggers
    Input("chrom-select", "value"),
    Input("resolution-select", "value"),
    Input("zoom-in", "n_clicks"),
    Input("zoom-out", "n_clicks"),
    Input("zoom-fit", "n_clicks"),
    Input("nav-left", "n_clicks"),
    Input("nav-right", "n_clicks"),
    Input("nav-far-left", "n_clicks"),
    Input("nav-far-right", "n_clicks"),
    Input("position-input", "n_submit"),
    Input("colorscale-select", "value"),
    Input("log-scale-switch", "checked"),
    Input("upper-triangle-switch", "checked"),
    Input("cap-percentile-input", "value"),
    Input("browser-graph", "relayoutData"),
    # State
    State("data-source-select", "value"),
    State("file-path-input", "value"),
    State("position-input", "value"),
    State("view-store", "data"),
    State("n-bins-input", "value"),
    State("n-tads-input", "value"),
    State("n-loops-input", "value"),
    prevent_initial_call=False,
)
def render_browser(
    chrom,
    resolution,
    _zi,
    _zo,
    _zf,
    _nl,
    _nr,
    _nfl,
    _nfr,
    _pos_submit,
    colorscale,
    log_scale,
    upper_triangle,
    cap_percentile,
    relayout_data,
    source,
    file_path,
    position_text,
    view_store,
    n_bins,
    n_tads,
    n_loops,
):
    """Main render callback — handles all navigation and visualization."""
    import plotly.graph_objects as go

    try:
        # Load data
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

        chrom_len = data.end
        triggered = ctx.triggered_id

        # Determine current view
        vs = view_store.get("start_bp", 0)
        ve = view_store.get("end_bp", 0)
        old_chrom_len = view_store.get("chrom_length", 0)

        # Reset view on chromosome/resolution change or first load
        if (
            triggered in ("chrom-select", "resolution-select", None)
            or ve == 0
            or old_chrom_len != chrom_len
        ):
            vs, ve = 0, chrom_len

        span = ve - vs

        # Handle navigation
        if triggered == "zoom-in":
            delta = span // 4
            vs = vs + delta
            ve = ve - delta
        elif triggered == "zoom-out":
            delta = span // 2
            vs = max(0, vs - delta)
            ve = min(chrom_len, ve + delta)
        elif triggered == "zoom-fit":
            vs, ve = 0, chrom_len
        elif triggered == "nav-left":
            shift = span // 4
            vs = max(0, vs - shift)
            ve = vs + span
        elif triggered == "nav-right":
            shift = span // 4
            ve = min(chrom_len, ve + shift)
            vs = ve - span
        elif triggered == "nav-far-left":
            ve = span
            vs = 0
        elif triggered == "nav-far-right":
            vs = max(0, chrom_len - span)
            ve = chrom_len
        elif triggered == "position-input" and position_text:
            vs, ve = _parse_position(position_text, chrom_len)
        elif triggered == "browser-graph" and relayout_data:
            # Capture zoom from Plotly (rubberband / scroll zoom)
            if "xaxis.range[0]" in relayout_data and "xaxis.range[1]" in relayout_data:
                new_start_mb = relayout_data["xaxis.range[0]"]
                new_end_mb = relayout_data["xaxis.range[1]"]
                vs = max(0, int(new_start_mb * 1_000_000))
                ve = min(chrom_len, int(new_end_mb * 1_000_000))
            elif "xaxis.autorange" in relayout_data:
                vs, ve = 0, chrom_len

        # Clamp
        vs = max(0, vs)
        ve = min(chrom_len, ve)
        if ve <= vs:
            ve = min(vs + data.resolution * 10, chrom_len)

        fig = create_browser_figure(
            data,
            colorscale=colorscale or DEFAULT_COLORSCALE,
            log_scale=bool(log_scale),
            value_cap_percentile=float(cap_percentile or 99.5),
            view_start_bp=vs,
            view_end_bp=ve,
            upper_triangle=bool(upper_triangle),
        )

        n = data.matrix.shape[0]
        view_bins = (ve - vs) // data.resolution
        info = f"Matrix: {n}×{n} | Viewing: {view_bins} bins | {_fmt_res(data.resolution)}"
        pos_display = f"{data.chrom}:{_fmt_bp(vs)}-{_fmt_bp(ve)} ({_fmt_bp(ve - vs)} span)"
        pos_input = f"{vs / 1_000_000:.1f}-{ve / 1_000_000:.1f}"

        new_view = {"start_bp": vs, "end_bp": ve, "chrom_length": chrom_len}
        return fig, info, pos_display, new_view, pos_input

    except Exception as e:
        import traceback

        traceback.print_exc()
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
        return fig, f"Error: {e}", "", view_store, ""


def _parse_position(text: str, chrom_len: int) -> tuple[int, int]:
    """Parse position text like '50-100' (Mb) or '50000000-100000000' (bp)."""
    text = text.strip().replace(",", "").replace(" ", "")
    if "-" in text:
        parts = text.split("-")
        a, b = float(parts[0]), float(parts[1])
    else:
        a = float(text)
        b = a + 10  # Default 10 Mb window

    # If values look like Mb (< 1000), convert
    if a < 1000 and b < 1000:
        a *= 1_000_000
        b *= 1_000_000

    return max(0, int(a)), min(chrom_len, int(b))


def _fmt_res(res: int) -> str:
    if res >= 1_000_000:
        return f"{res // 1_000_000} Mb"
    if res >= 1_000:
        return f"{res // 1_000} kb"
    return f"{res} bp"


def _fmt_bp(bp: int) -> str:
    if bp >= 1_000_000:
        return f"{bp / 1_000_000:.1f} Mb"
    if bp >= 1_000:
        return f"{bp / 1_000:.0f} kb"
    return f"{bp} bp"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """CLI entry point."""
    global COOL_FILE_PATH
    parser = argparse.ArgumentParser(description="Hi-C Contact Map Browser")
    parser.add_argument("--file", "-f", help="Path to .cool or .mcool file")
    parser.add_argument("--port", "-p", type=int, default=8050, help="Port (default: 8050)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    if args.file:
        COOL_FILE_PATH = args.file

    app.run(debug=args.debug, port=args.port)


if __name__ == "__main__":
    main()
