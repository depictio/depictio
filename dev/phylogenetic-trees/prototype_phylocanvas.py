"""
Prototype 4: Phylogenetic Tree Visualization with Phylocanvas 3.

Uses the custom dash-phylotree Dash component wrapping react-phylogeny-tree
(Phylocanvas 3) for native canvas-based tree rendering.

Supports all 5 tree layouts natively:
  rectangular, circular, radial, diagonal, hierarchical

Prerequisites:
    cd packages/dash-phylotree && npm install && npm run build
    pip install -e packages/dash-phylotree

Run: python prototype_phylocanvas.py
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import dash_mantine_components as dmc
import pandas as pd
from dash import Dash, Input, Output, State, callback_context, dcc, html
from dash_iconify import DashIconify
from dash_phylotree import PhyloTree

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

TREE_TYPES = [
    {"value": "rectangular", "label": "Rectangular"},
    {"value": "circular", "label": "Circular"},
    {"value": "radial", "label": "Radial"},
    {"value": "diagonal", "label": "Diagonal"},
    {"value": "hierarchical", "label": "Hierarchical"},
]

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


def build_node_styles(
    metadata_df: pd.DataFrame | None,
    color_by: str | None,
) -> dict:
    """Build Phylocanvas styles dict from metadata.

    Returns a dict like {nodeLabel: {fillStyle: '#color'}} that
    Phylocanvas uses to color individual nodes.
    """
    if metadata_df is None or not color_by or color_by not in metadata_df.columns:
        return {}

    taxon_col = metadata_df.columns[0]
    unique_vals = sorted(metadata_df[color_by].dropna().unique().tolist(), key=str)
    color_map = {str(v): PALETTE[i % len(PALETTE)] for i, v in enumerate(unique_vals)}

    styles = {}
    for _, row in metadata_df.iterrows():
        taxon = str(row[taxon_col])
        val = str(row.get(color_by, ""))
        if val in color_map:
            styles[taxon] = {"fillStyle": color_map[val]}

    return styles


def build_legend(
    metadata_df: pd.DataFrame | None,
    color_by: str | None,
) -> list:
    """Build a DMC legend for the current color mapping."""
    if metadata_df is None or not color_by or color_by not in metadata_df.columns:
        return [dmc.Text("No metadata coloring", size="xs", c="dimmed")]

    unique_vals = sorted(metadata_df[color_by].dropna().unique().tolist(), key=str)
    color_map = {str(v): PALETTE[i % len(PALETTE)] for i, v in enumerate(unique_vals)}

    items = []
    for val, color in color_map.items():
        items.append(
            dmc.Group(
                [
                    html.Div(
                        style={
                            "width": 12,
                            "height": 12,
                            "borderRadius": "50%",
                            "backgroundColor": color,
                            "flexShrink": 0,
                        }
                    ),
                    dmc.Text(val, size="xs"),
                ],
                gap=6,
            )
        )
    return items


def create_app() -> Dash:
    app = Dash(__name__, external_stylesheets=[dmc.styles.ALL])

    default_tree_key = list(SAMPLE_TREES.keys())[1]

    sidebar = dmc.Stack(
        [
            # Tree source
            dmc.Text("Tree Source", fw="bold", size="sm"),
            dmc.Select(
                id="tree-selector",
                label="Sample Tree",
                data=list(SAMPLE_TREES.keys()),
                value=default_tree_key,
            ),
            dmc.Divider(label="or upload", labelPosition="center"),
            dcc.Upload(
                id="newick-upload",
                children=dmc.Button(
                    "Upload .nwk file",
                    leftSection=DashIconify(icon="mdi:upload"),
                    variant="outline",
                    fullWidth=True,
                    size="xs",
                ),
            ),
            dmc.Divider(),
            # Tree type — all 5 Phylocanvas layouts
            dmc.Text("Tree Type", fw="bold", size="sm"),
            dmc.SegmentedControl(
                id="tree-type",
                data=TREE_TYPES,
                value="rectangular",
                orientation="vertical",
                fullWidth=True,
            ),
            dmc.Divider(),
            # Visual controls
            dmc.Text("Display Options", fw="bold", size="sm"),
            dmc.Switch(id="show-labels", label="Show leaf labels", checked=True),
            dmc.Switch(id="align-labels", label="Align labels", checked=False),
            dmc.Text("Node size", size="xs", c="dimmed"),
            dmc.Slider(
                id="node-size",
                min=1,
                max=20,
                value=7,
                step=1,
                marks=[
                    {"value": 1, "label": "1"},
                    {"value": 10, "label": "10"},
                    {"value": 20, "label": "20"},
                ],
            ),
            dmc.Text("Font size", size="xs", c="dimmed"),
            dmc.Slider(
                id="font-size",
                min=6,
                max=20,
                value=10,
                step=1,
                marks=[
                    {"value": 6, "label": "6"},
                    {"value": 14, "label": "14"},
                    {"value": 20, "label": "20"},
                ],
            ),
            dmc.Text("Line width", size="xs", c="dimmed"),
            dmc.Slider(
                id="line-width",
                min=1,
                max=5,
                value=2,
                step=0.5,
                marks=[
                    {"value": 1, "label": "1"},
                    {"value": 3, "label": "3"},
                    {"value": 5, "label": "5"},
                ],
            ),
            dmc.Divider(),
            # Metadata
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
            # Legend
            html.Div(id="legend-container"),
            dmc.Divider(),
            # Selection info
            dmc.Text("Selection", fw="bold", size="sm"),
            dmc.Paper(
                dmc.Text(id="selection-info", size="xs", style={"whiteSpace": "pre-wrap"}),
                p="xs",
                withBorder=True,
                style={"minHeight": 40, "maxHeight": 120, "overflowY": "auto"},
            ),
        ],
        gap="xs",
        p="md",
        style={"overflowY": "auto"},
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
                                        DashIconify(icon="mdi:tree", width=28, color="teal"),
                                        dmc.Title(
                                            "Phylogenetic Tree — Phylocanvas Prototype", order=3
                                        ),
                                        dmc.Badge("Phylocanvas 3", variant="light", color="teal"),
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
                    dmc.AppShellNavbar(sidebar),
                    dmc.AppShellMain(
                        html.Div(
                            id="tree-container",
                            style={"height": "calc(100vh - 60px)", "width": "100%"},
                        ),
                    ),
                ],
                header={"height": 60},
                navbar={"width": 300, "breakpoint": "sm"},
            ),
            dcc.Store(id="current-newick", data=SAMPLE_TREES[default_tree_key]),
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
        new = "dark" if current == "light" else "light"
        return new, new

    @app.callback(
        Output("current-newick", "data"),
        Input("tree-selector", "value"),
        Input("newick-upload", "contents"),
        prevent_initial_call=True,
    )
    def update_newick(selected, upload_contents):
        ctx = callback_context
        trigger = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
        if "newick-upload" in trigger and upload_contents:
            _, content_string = upload_contents.split(",")
            return base64.b64decode(content_string).decode("utf-8").strip()
        if selected in SAMPLE_TREES:
            return SAMPLE_TREES[selected]
        return SAMPLE_TREES[default_tree_key]

    @app.callback(
        Output("current-metadata", "data"),
        Output("color-by", "data"),
        Output("color-by", "value"),
        Output("color-by", "disabled"),
        Output("metadata-status", "children"),
        Input("metadata-upload", "contents"),
        Input("tree-selector", "value"),
    )
    def update_metadata(upload_contents, selected_sample):
        ctx = callback_context
        trigger = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
        metadata_df = None

        if "tree-selector" in trigger or not ctx.triggered:
            if selected_sample == "Bacteria (21 taxa)":
                p = DATA_DIR / "sample_metadata.csv"
                if p.exists():
                    metadata_df = pd.read_csv(p)
            elif selected_sample == "Mammals (15 taxa)":
                p = DATA_DIR / "mammal_metadata.csv"
                if p.exists():
                    metadata_df = pd.read_csv(p)

        if "metadata-upload" in trigger and upload_contents:
            _, content_string = upload_contents.split(",")
            decoded = base64.b64decode(content_string).decode("utf-8")
            metadata_df = pd.read_csv(io.StringIO(decoded))

        if metadata_df is not None:
            cols = list(metadata_df.columns[1:])
            opts = [{"value": c, "label": c} for c in cols]
            default = cols[0] if cols else None
            status = f"{len(metadata_df)} rows, {len(cols)} fields"
            return metadata_df.to_json(), opts, default, False, status

        return None, [], None, True, "No metadata"

    @app.callback(
        Output("tree-container", "children"),
        Output("legend-container", "children"),
        Input("current-newick", "data"),
        Input("tree-type", "value"),
        Input("show-labels", "checked"),
        Input("align-labels", "checked"),
        Input("node-size", "value"),
        Input("font-size", "value"),
        Input("line-width", "value"),
        Input("current-metadata", "data"),
        Input("color-by", "value"),
    )
    def render_tree(
        newick,
        tree_type,
        show_labels,
        align_labels,
        node_size,
        font_size,
        line_width,
        meta_json,
        color_by,
    ):
        if not newick:
            return html.Div("No tree data"), []

        metadata_df = None
        if meta_json:
            metadata_df = pd.read_json(io.StringIO(meta_json))

        styles = build_node_styles(metadata_df, color_by)
        legend = build_legend(metadata_df, color_by)

        tree_component = PhyloTree(
            id="phylo-tree",
            newick=newick,
            treeType=tree_type,
            interactive=True,
            showZoom=True,
            nodeSize=node_size,
            fontSize=font_size,
            lineWidth=line_width,
            showLabels=show_labels,
            alignLabels=align_labels,
            styles=styles,
            width="100%",
            height="100%",
        )

        return tree_component, legend

    @app.callback(
        Output("selection-info", "children"),
        Input("phylo-tree", "selectedIds"),
    )
    def show_selection(selected_ids):
        if not selected_ids:
            return "Click nodes to select"
        return f"{len(selected_ids)} selected:\n" + "\n".join(selected_ids)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=8054)
