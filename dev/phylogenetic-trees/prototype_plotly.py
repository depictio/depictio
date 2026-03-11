"""
Prototype 1: Phylogenetic Tree Visualization with Pure Plotly Traces.

Renders trees using Plotly scatter/line traces with computed coordinates.
Supports rectangular, circular, radial, and diagonal layouts.
Includes metadata annotation on leaf nodes.

Run: python prototype_plotly.py

Inspired by:
- Microreact (https://microreact.org/) tree visualization
- empet/Phylogenetic-trees (https://github.com/empet/Phylogenetic-trees)
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dcc
from dash_iconify import DashIconify
from tree_utils import (
    compute_circular_coords,
    compute_diagonal_coords,
    compute_radial_coords,
    compute_rectangular_coords,
    merge_metadata_to_nodes,
    parse_newick,
)

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "data"

SAMPLE_TREES = {
    "Mammals (15 taxa)": (DATA_DIR / "sample_tree.nwk").read_text().strip(),
    "Bacteria (21 taxa)": (DATA_DIR / "bacterial_tree.nwk").read_text().strip(),
    "Simple example": "((A:0.1,B:0.2):0.3,(C:0.4,(D:0.5,E:0.6):0.1):0.2);",
}

# Add nf-core pipeline trees if downloaded (see download_nfcore_trees.sh)
NFCORE_DIR = DATA_DIR / "nfcore"
if (NFCORE_DIR / "ampliseq_tree.nwk").exists():
    SAMPLE_TREES["ampliseq (nf-core)"] = (NFCORE_DIR / "ampliseq_tree.nwk").read_text().strip()
if (NFCORE_DIR / "viralrecon_tree.nwk").exists():
    SAMPLE_TREES["viralrecon (nf-core)"] = (NFCORE_DIR / "viralrecon_tree.nwk").read_text().strip()

LAYOUT_TYPES = [
    {"value": "rectangular", "label": "Rectangular"},
    {"value": "circular", "label": "Circular"},
    {"value": "radial", "label": "Radial (unrooted)"},
    {"value": "diagonal", "label": "Diagonal"},
]

# Color palettes for metadata
PALETTE = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]


def build_plotly_figure(
    newick_str: str,
    layout_type: str = "rectangular",
    show_labels: bool = True,
    show_branch_lengths: bool = False,
    metadata_df: pd.DataFrame | None = None,
    color_by: str | None = None,
    theme: str = "light",
) -> go.Figure:
    """Build a Plotly figure for a phylogenetic tree.

    Args:
        newick_str: Newick format tree string.
        layout_type: One of rectangular, circular, radial, diagonal.
        show_labels: Whether to show leaf labels.
        show_branch_lengths: Whether to show branch length annotations.
        metadata_df: Optional DataFrame with metadata for leaf coloring.
        color_by: Column name in metadata_df to use for coloring leaves.
        theme: 'light' or 'dark'.

    Returns:
        Plotly Figure object.
    """
    tree = parse_newick(newick_str)

    # Compute coordinates based on layout type
    if layout_type == "circular":
        coords = compute_circular_coords(tree)
    elif layout_type == "radial":
        coords = compute_radial_coords(tree)
    elif layout_type == "diagonal":
        coords = compute_diagonal_coords(tree)
    else:
        coords = compute_rectangular_coords(tree)

    nodes = coords["nodes"]
    edges = coords["edges"]

    # Merge metadata if available
    if metadata_df is not None:
        taxon_col = metadata_df.columns[0]
        nodes = merge_metadata_to_nodes(nodes, metadata_df, taxon_col)

    # Build color map
    color_map: dict[str, str] = {}
    if color_by and metadata_df is not None and color_by in metadata_df.columns:
        unique_vals = sorted(metadata_df[color_by].dropna().unique().tolist(), key=str)
        color_map = {str(v): PALETTE[i % len(PALETTE)] for i, v in enumerate(unique_vals)}

    # Theme settings
    is_dark = theme == "dark"
    bg_color = "rgba(0,0,0,0)"
    line_color = "#888" if is_dark else "#555"
    text_color = "#ddd" if is_dark else "#333"
    node_color = "#aaa" if is_dark else "#666"

    fig = go.Figure()

    # Draw edges
    if layout_type == "circular":
        # Circular layout has arc + radial edges
        for edge in edges:
            # Arc
            fig.add_trace(
                go.Scatter(
                    x=edge["arc_x"],
                    y=edge["arc_y"],
                    mode="lines",
                    line={"color": line_color, "width": 1.5},
                    hoverinfo="skip",
                    showlegend=False,
                )
            )
            # Radial line
            fig.add_trace(
                go.Scatter(
                    x=edge["radial_x"],
                    y=edge["radial_y"],
                    mode="lines",
                    line={"color": line_color, "width": 1.5},
                    hoverinfo="skip",
                    showlegend=False,
                )
            )
    else:
        # Rectangular, diagonal, radial: simple line segments
        for edge in edges:
            fig.add_trace(
                go.Scatter(
                    x=[edge["x0"], edge["x1"]],
                    y=[edge["y0"], edge["y1"]],
                    mode="lines",
                    line={"color": line_color, "width": 1.5},
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    # Draw nodes
    leaf_nodes = [n for n in nodes if n["is_leaf"]]
    internal_nodes = [n for n in nodes if not n["is_leaf"]]

    # Internal nodes (small dots)
    if internal_nodes:
        fig.add_trace(
            go.Scatter(
                x=[n["x"] for n in internal_nodes],
                y=[n["y"] for n in internal_nodes],
                mode="markers",
                marker={"size": 4, "color": node_color},
                hoverinfo="skip",
                showlegend=False,
            )
        )

    # Leaf nodes - colored by metadata if available
    if color_by and color_map:
        # Group by metadata value
        groups: dict[str, list[dict]] = {}
        ungrouped: list[dict] = []
        for node in leaf_nodes:
            meta = node.get("metadata", {})
            val = str(meta.get(color_by, ""))
            if val and val in color_map:
                groups.setdefault(val, []).append(node)
            else:
                ungrouped.append(node)

        for val, group_nodes in groups.items():
            hover_texts = []
            for n in group_nodes:
                meta = n.get("metadata", {})
                parts = [f"<b>{n['name']}</b>"]
                for k, v in meta.items():
                    parts.append(f"{k}: {v}")
                hover_texts.append("<br>".join(parts))

            fig.add_trace(
                go.Scatter(
                    x=[n["x"] for n in group_nodes],
                    y=[n["y"] for n in group_nodes],
                    mode="markers+text" if show_labels else "markers",
                    marker={
                        "size": 10,
                        "color": color_map[val],
                        "line": {"width": 1, "color": "white"},
                    },
                    text=[n["name"].replace("_", " ") for n in group_nodes]
                    if show_labels
                    else None,
                    textposition="middle right" if layout_type == "rectangular" else "top center",
                    textfont={"size": 10, "color": text_color},
                    hovertext=hover_texts,
                    hoverinfo="text",
                    name=val,
                    showlegend=True,
                )
            )

        if ungrouped:
            fig.add_trace(
                go.Scatter(
                    x=[n["x"] for n in ungrouped],
                    y=[n["y"] for n in ungrouped],
                    mode="markers+text" if show_labels else "markers",
                    marker={"size": 8, "color": node_color},
                    text=[n["name"].replace("_", " ") for n in ungrouped] if show_labels else None,
                    textposition="middle right" if layout_type == "rectangular" else "top center",
                    textfont={"size": 10, "color": text_color},
                    hovertext=[n["name"] for n in ungrouped],
                    hoverinfo="text",
                    name="Other",
                    showlegend=True,
                )
            )
    else:
        # No metadata coloring
        hover_texts = []
        for n in leaf_nodes:
            meta = n.get("metadata", {})
            parts = [f"<b>{n['name']}</b>"]
            for k, v in meta.items():
                parts.append(f"{k}: {v}")
            hover_texts.append("<br>".join(parts))

        fig.add_trace(
            go.Scatter(
                x=[n["x"] for n in leaf_nodes],
                y=[n["y"] for n in leaf_nodes],
                mode="markers+text" if show_labels else "markers",
                marker={"size": 8, "color": "#1f77b4", "line": {"width": 1, "color": "white"}},
                text=[n["name"].replace("_", " ") for n in leaf_nodes] if show_labels else None,
                textposition="middle right" if layout_type == "rectangular" else "top center",
                textfont={"size": 10, "color": text_color},
                hovertext=hover_texts,
                hoverinfo="text",
                name="Leaves",
                showlegend=False,
            )
        )

    # Layout
    fig.update_layout(
        paper_bgcolor=bg_color,
        plot_bgcolor=bg_color,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        xaxis={
            "visible": False,
            "scaleanchor": "y" if layout_type in ("circular", "radial") else None,
        },
        yaxis={"visible": False, "autorange": "reversed" if layout_type == "rectangular" else True},
        legend={
            "font": {"color": text_color, "size": 11},
            "bgcolor": "rgba(0,0,0,0)",
            "x": 1.0,
            "y": 1.0,
        },
        hovermode="closest",
        dragmode="pan",
    )

    return fig


# ---------------------------------------------------------------------------
# Dash App
# ---------------------------------------------------------------------------


def create_app() -> Dash:
    app = Dash(
        __name__,
        external_stylesheets=[dmc.styles.ALL],
    )

    app.layout = dmc.MantineProvider(
        id="mantine-provider",
        forceColorScheme="light",
        children=[
            dmc.AppShell(
                [
                    dmc.AppShellHeader(
                        dmc.Group(
                            [
                                dmc.Group(
                                    [
                                        DashIconify(icon="mdi:tree", width=28, color="green"),
                                        dmc.Title("Phylogenetic Tree — Plotly Prototype", order=3),
                                    ]
                                ),
                                dmc.ActionIcon(
                                    DashIconify(icon="mdi:theme-light-dark", width=20),
                                    id="theme-toggle",
                                    variant="subtle",
                                    size="lg",
                                ),
                            ],
                            justify="space-between",
                            px="md",
                            h="100%",
                        ),
                    ),
                    dmc.AppShellNavbar(
                        dmc.Stack(
                            [
                                dmc.Text("Tree Source", fw="bold", size="sm"),
                                dmc.Select(
                                    id="tree-selector",
                                    label="Sample Tree",
                                    data=list(SAMPLE_TREES.keys()),
                                    value=list(SAMPLE_TREES.keys())[1],
                                ),
                                dmc.Divider(label="or upload", labelPosition="center"),
                                dcc.Upload(
                                    id="newick-upload",
                                    children=dmc.Button(
                                        "Upload .nwk file",
                                        leftSection=DashIconify(icon="mdi:upload"),
                                        variant="outline",
                                        fullWidth=True,
                                    ),
                                ),
                                dmc.Divider(),
                                dmc.Text("Layout", fw="bold", size="sm"),
                                dmc.SegmentedControl(
                                    id="layout-type",
                                    data=LAYOUT_TYPES,
                                    value="rectangular",
                                    orientation="vertical",
                                    fullWidth=True,
                                ),
                                dmc.Divider(),
                                dmc.Text("Display Options", fw="bold", size="sm"),
                                dmc.Switch(
                                    id="show-labels",
                                    label="Show leaf labels",
                                    checked=True,
                                ),
                                dmc.Switch(
                                    id="show-branch-lengths",
                                    label="Show branch lengths",
                                    checked=False,
                                ),
                                dmc.Divider(),
                                dmc.Text("Metadata", fw="bold", size="sm"),
                                dcc.Upload(
                                    id="metadata-upload",
                                    children=dmc.Button(
                                        "Upload metadata CSV",
                                        leftSection=DashIconify(icon="mdi:table"),
                                        variant="outline",
                                        fullWidth=True,
                                        size="xs",
                                    ),
                                ),
                                dmc.Select(
                                    id="color-by",
                                    label="Color by",
                                    data=[],
                                    value=None,
                                    clearable=True,
                                    disabled=True,
                                ),
                                dmc.Text(id="metadata-status", size="xs", c="dimmed"),
                            ],
                            gap="xs",
                            p="md",
                        ),
                    ),
                    dmc.AppShellMain(
                        dcc.Graph(
                            id="tree-graph",
                            config={
                                "scrollZoom": True,
                                "displayModeBar": True,
                                "modeBarButtonsToRemove": ["toImage", "lasso2d", "select2d"],
                            },
                            style={"height": "100%", "width": "100%"},
                        ),
                        style={"height": "calc(100vh - 60px)"},
                    ),
                ],
                header={"height": 60},
                navbar={"width": 280, "breakpoint": "sm"},
            ),
            # Hidden stores
            dcc.Store(id="current-newick", data=SAMPLE_TREES[list(SAMPLE_TREES.keys())[1]]),
            dcc.Store(id="current-metadata", data=None),
            dcc.Store(id="current-theme", data="light"),
        ],
    )

    # -----------------------------------------------------------------------
    # Callbacks
    # -----------------------------------------------------------------------

    @app.callback(
        Output("mantine-provider", "forceColorScheme"),
        Output("current-theme", "data"),
        Input("theme-toggle", "n_clicks"),
        State("current-theme", "data"),
        prevent_initial_call=True,
    )
    def toggle_theme(n_clicks, current):
        new_theme = "dark" if current == "light" else "light"
        return new_theme, new_theme

    @app.callback(
        Output("current-newick", "data"),
        Input("tree-selector", "value"),
        Input("newick-upload", "contents"),
        State("newick-upload", "filename"),
        prevent_initial_call=True,
    )
    def update_newick(selected_sample, upload_contents, upload_filename):
        ctx = callback_context
        if not ctx.triggered:
            return SAMPLE_TREES[list(SAMPLE_TREES.keys())[1]]

        trigger_id = ctx.triggered[0]["prop_id"]

        if "newick-upload" in trigger_id and upload_contents:
            # Decode uploaded file
            content_type, content_string = upload_contents.split(",")
            decoded = base64.b64decode(content_string).decode("utf-8")
            return decoded.strip()

        if selected_sample and selected_sample in SAMPLE_TREES:
            return SAMPLE_TREES[selected_sample]

        return SAMPLE_TREES[list(SAMPLE_TREES.keys())[1]]

    @app.callback(
        Output("current-metadata", "data"),
        Output("color-by", "data"),
        Output("color-by", "value"),
        Output("color-by", "disabled"),
        Output("metadata-status", "children"),
        Input("metadata-upload", "contents"),
        Input("tree-selector", "value"),
        State("metadata-upload", "filename"),
    )
    def update_metadata(upload_contents, selected_sample, upload_filename):
        ctx = callback_context
        trigger_id = ctx.triggered[0]["prop_id"] if ctx.triggered else ""

        metadata_df = None

        # Auto-load matching metadata for sample trees
        if "tree-selector" in trigger_id or not ctx.triggered:
            if selected_sample == "Bacteria (21 taxa)":
                meta_path = DATA_DIR / "sample_metadata.csv"
                if meta_path.exists():
                    metadata_df = pd.read_csv(meta_path)
            elif selected_sample == "Mammals (15 taxa)":
                meta_path = DATA_DIR / "mammal_metadata.csv"
                if meta_path.exists():
                    metadata_df = pd.read_csv(meta_path)

        # Handle uploaded metadata
        if "metadata-upload" in trigger_id and upload_contents:
            content_type, content_string = upload_contents.split(",")
            decoded = base64.b64decode(content_string).decode("utf-8")
            metadata_df = pd.read_csv(io.StringIO(decoded))

        if metadata_df is not None:
            cols = [c for c in metadata_df.columns[1:]]  # Skip taxon column
            col_options = [{"value": c, "label": c} for c in cols]
            default_color = cols[0] if cols else None
            status = f"Loaded: {len(metadata_df)} rows, {len(cols)} fields"
            return metadata_df.to_json(), col_options, default_color, False, status

        return None, [], None, True, "No metadata loaded"

    @app.callback(
        Output("tree-graph", "figure"),
        Input("current-newick", "data"),
        Input("layout-type", "value"),
        Input("show-labels", "checked"),
        Input("show-branch-lengths", "checked"),
        Input("current-metadata", "data"),
        Input("color-by", "value"),
        Input("current-theme", "data"),
    )
    def render_tree(
        newick_str, layout_type, show_labels, show_branch_lengths, metadata_json, color_by, theme
    ):
        if not newick_str:
            return go.Figure()

        metadata_df = None
        if metadata_json:
            metadata_df = pd.read_json(io.StringIO(metadata_json))

        fig = build_plotly_figure(
            newick_str=newick_str,
            layout_type=layout_type,
            show_labels=show_labels,
            show_branch_lengths=show_branch_lengths,
            metadata_df=metadata_df,
            color_by=color_by,
            theme=theme,
        )
        return fig

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=8051)
