"""
Prototype 3: Combined Phylogenetic Tree Viewer.

Full-featured prototype combining Plotly and Cytoscape rendering engines
with a Microreact-inspired UI. Includes:
- Tab-based engine selection (Plotly traces vs Cytoscape graph)
- All tree layouts: rectangular, circular, radial, diagonal, dagre, force-directed
- Metadata coloring with legend
- Newick file upload + sample trees
- Dark/light theme support
- Node info panel on click

Run: python prototype_combined.py

Architecture notes for future depictio integration:
- Tree parsing/coords in tree_utils.py → would become depictio/models/components/tree.py
- Rendering → depictio/dash/modules/tree_component/utils.py
- UI controls → depictio/dash/modules/tree_component/design_ui.py
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import dash_cytoscape as cyto
import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dcc, html
from dash_iconify import DashIconify
from tree_utils import (
    compute_circular_coords,
    compute_diagonal_coords,
    compute_radial_coords,
    compute_rectangular_coords,
    merge_metadata_to_nodes,
    parse_newick,
)

cyto.load_extra_layouts()

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

PLOTLY_LAYOUTS = [
    {"value": "rectangular", "label": "Rectangular"},
    {"value": "circular", "label": "Circular"},
    {"value": "radial", "label": "Radial"},
    {"value": "diagonal", "label": "Diagonal"},
]

CYTOSCAPE_LAYOUTS = [
    {"value": "preset", "label": "Phylogram"},
    {"value": "dagre", "label": "Dagre"},
    {"value": "breadthfirst", "label": "Breadthfirst"},
    {"value": "circle", "label": "Circle"},
    {"value": "cose", "label": "Force-directed"},
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


# ---------------------------------------------------------------------------
# Plotly builder (from prototype_plotly)
# ---------------------------------------------------------------------------


def _build_plotly_figure(
    newick_str: str,
    layout_type: str,
    show_labels: bool,
    metadata_df: pd.DataFrame | None,
    color_by: str | None,
    theme: str,
) -> go.Figure:
    tree = parse_newick(newick_str)

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

    if metadata_df is not None:
        taxon_col = metadata_df.columns[0]
        nodes = merge_metadata_to_nodes(nodes, metadata_df, taxon_col)

    color_map: dict[str, str] = {}
    if color_by and metadata_df is not None and color_by in metadata_df.columns:
        unique_vals = sorted(metadata_df[color_by].dropna().unique().tolist(), key=str)
        color_map = {str(v): PALETTE[i % len(PALETTE)] for i, v in enumerate(unique_vals)}

    is_dark = theme == "dark"
    line_color = "#888" if is_dark else "#555"
    text_color = "#ddd" if is_dark else "#333"
    node_color = "#aaa" if is_dark else "#666"

    fig = go.Figure()

    # Edges
    if layout_type == "circular":
        for edge in edges:
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

    # Nodes
    leaf_nodes = [n for n in nodes if n["is_leaf"]]
    internal_nodes = [n for n in nodes if not n["is_leaf"]]

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

    if color_by and color_map:
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
                    name="Other",
                    showlegend=True,
                )
            )
    else:
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
                showlegend=False,
            )
        )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        xaxis={
            "visible": False,
            "scaleanchor": "y" if layout_type in ("circular", "radial") else None,
        },
        yaxis={"visible": False, "autorange": "reversed" if layout_type == "rectangular" else True},
        legend={"font": {"color": text_color, "size": 11}, "bgcolor": "rgba(0,0,0,0)"},
        hovermode="closest",
        dragmode="pan",
    )
    return fig


# ---------------------------------------------------------------------------
# Cytoscape builder (from prototype_cytoscape)
# ---------------------------------------------------------------------------


def _build_cytoscape_elements(
    newick_str: str,
    metadata_df: pd.DataFrame | None,
    color_by: str | None,
) -> list[dict]:
    tree = parse_newick(newick_str)
    coords = compute_rectangular_coords(tree)
    nodes = coords["nodes"]

    if metadata_df is not None:
        taxon_col = metadata_df.columns[0]
        nodes = merge_metadata_to_nodes(nodes, metadata_df, taxon_col)

    color_map: dict[str, str] = {}
    if color_by and metadata_df is not None and color_by in metadata_df.columns:
        unique_vals = sorted(metadata_df[color_by].dropna().unique().tolist(), key=str)
        color_map = {str(v): PALETTE[i % len(PALETTE)] for i, v in enumerate(unique_vals)}

    elements = []
    x_scale, y_scale = 800, 40

    for i, node in enumerate(nodes):
        node_id = node["name"] if node["name"] else f"internal_{i}"
        meta = node.get("metadata", {})
        tooltip_parts = [node["name"]] if node["name"] else []
        for k, v in meta.items():
            tooltip_parts.append(f"{k}: {v}")

        node_color = "#666"
        if color_by and meta:
            val = str(meta.get(color_by, ""))
            if val in color_map:
                node_color = color_map[val]

        elements.append(
            {
                "data": {
                    "id": node_id,
                    "label": node["name"].replace("_", " ") if node["is_leaf"] else "",
                    "is_leaf": node["is_leaf"],
                    "tooltip": "\n".join(tooltip_parts),
                    "color": node_color,
                },
                "position": {"x": node["x"] * x_scale, "y": node["y"] * y_scale},
                "classes": "leaf" if node["is_leaf"] else "internal",
            }
        )

    # Build edges from tree structure
    tree = parse_newick(newick_str)
    edge_count = 0

    def _get_node_id_for_clade(clade, depth):
        if clade.name:
            return clade.name
        for j, n in enumerate(nodes):
            if not n["is_leaf"] and not n["name"] and abs(n["x"] - depth) < 1e-8:
                return f"internal_{j}"
        return f"fallback_{depth}"

    def _add_edges(clade, parent_id, depth):
        nonlocal edge_count
        current_id = _get_node_id_for_clade(clade, depth)
        if parent_id is not None:
            elements.append(
                {"data": {"id": f"edge_{edge_count}", "source": parent_id, "target": current_id}}
            )
            edge_count += 1
        for child in clade.clades:
            _add_edges(child, current_id, depth + (child.branch_length or 0.0))

    _add_edges(tree.root, None, 0.0)
    return elements


def _get_cyto_stylesheet(theme: str) -> list[dict]:
    is_dark = theme == "dark"
    edge_color = "#666" if is_dark else "#999"
    label_color = "#ddd" if is_dark else "#333"

    return [
        {
            "selector": "node.leaf",
            "style": {
                "width": 12,
                "height": 12,
                "background-color": "data(color)",
                "label": "data(label)",
                "font-size": "10px",
                "text-valign": "center",
                "text-halign": "right",
                "text-margin-x": 8,
                "color": label_color,
                "border-width": 1,
                "border-color": "#fff" if is_dark else "#333",
            },
        },
        {
            "selector": "node.internal",
            "style": {"width": 5, "height": 5, "background-color": "#888"},
        },
        {
            "selector": "edge",
            "style": {"width": 1.5, "line-color": edge_color, "curve-style": "bezier"},
        },
        {
            "selector": ":selected",
            "style": {"background-color": "#ff0", "border-width": 3},
        },
    ]


# ---------------------------------------------------------------------------
# Dash App
# ---------------------------------------------------------------------------


def create_app() -> Dash:
    app = Dash(__name__, external_stylesheets=[dmc.styles.ALL])

    sidebar = dmc.Stack(
        [
            # Tree source
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
                    size="xs",
                ),
            ),
            dmc.Divider(),
            # Engine
            dmc.Text("Rendering Engine", fw="bold", size="sm"),
            dmc.SegmentedControl(
                id="engine",
                data=[
                    {"value": "plotly", "label": "Plotly"},
                    {"value": "cytoscape", "label": "Cytoscape"},
                ],
                value="plotly",
                fullWidth=True,
            ),
            # Layout (dynamic based on engine)
            dmc.Text("Layout", fw="bold", size="sm"),
            dmc.SegmentedControl(
                id="layout-type",
                data=PLOTLY_LAYOUTS,
                value="rectangular",
                orientation="vertical",
                fullWidth=True,
            ),
            dmc.Divider(),
            # Display options
            dmc.Switch(id="show-labels", label="Show leaf labels", checked=True),
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
            dmc.Divider(),
            dmc.Text("Node Info", fw="bold", size="sm"),
            dmc.Paper(
                dmc.Text(id="node-info", size="xs", style={"whiteSpace": "pre-wrap"}),
                p="xs",
                withBorder=True,
                style={"minHeight": 50},
            ),
        ],
        gap="xs",
        p="md",
        style={"overflowY": "auto"},
    )

    main_content = html.Div(
        [
            # Plotly container
            html.Div(
                dcc.Graph(
                    id="tree-graph",
                    config={"scrollZoom": True, "displayModeBar": True},
                    style={"height": "100%", "width": "100%"},
                ),
                id="plotly-container",
                style={"height": "100%", "display": "block"},
            ),
            # Cytoscape container
            html.Div(
                cyto.Cytoscape(
                    id="tree-cytoscape",
                    layout={"name": "preset"},
                    style={"width": "100%", "height": "100%"},
                    elements=[],
                    stylesheet=_get_cyto_stylesheet("light"),
                    responsive=True,
                ),
                id="cytoscape-container",
                style={"height": "100%", "display": "none"},
            ),
        ],
        style={"height": "calc(100vh - 60px)"},
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
                                        dmc.Title("Phylogenetic Tree Viewer", order=3),
                                        dmc.Badge("prototype", variant="light", color="teal"),
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
                    dmc.AppShellMain(main_content),
                ],
                header={"height": 60},
                navbar={"width": 300, "breakpoint": "sm"},
            ),
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
        new = "dark" if current == "light" else "light"
        return new, new

    @app.callback(
        Output("layout-type", "data"),
        Output("layout-type", "value"),
        Input("engine", "value"),
    )
    def update_layout_options(engine):
        if engine == "cytoscape":
            return CYTOSCAPE_LAYOUTS, "preset"
        return PLOTLY_LAYOUTS, "rectangular"

    @app.callback(
        Output("plotly-container", "style"),
        Output("cytoscape-container", "style"),
        Input("engine", "value"),
    )
    def toggle_engine_visibility(engine):
        if engine == "cytoscape":
            return {"height": "100%", "display": "none"}, {"height": "100%", "display": "block"}
        return {"height": "100%", "display": "block"}, {"height": "100%", "display": "none"}

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
        return SAMPLE_TREES[list(SAMPLE_TREES.keys())[1]]

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
        Output("tree-graph", "figure"),
        Input("engine", "value"),
        Input("current-newick", "data"),
        Input("layout-type", "value"),
        Input("show-labels", "checked"),
        Input("current-metadata", "data"),
        Input("color-by", "value"),
        Input("current-theme", "data"),
    )
    def render_plotly(engine, newick, layout_type, show_labels, meta_json, color_by, theme):
        if engine != "plotly" or not newick:
            return go.Figure()
        meta_df = pd.read_json(io.StringIO(meta_json)) if meta_json else None
        return _build_plotly_figure(newick, layout_type, show_labels, meta_df, color_by, theme)

    @app.callback(
        Output("tree-cytoscape", "elements"),
        Output("tree-cytoscape", "layout"),
        Output("tree-cytoscape", "stylesheet"),
        Input("engine", "value"),
        Input("current-newick", "data"),
        Input("layout-type", "value"),
        Input("current-metadata", "data"),
        Input("color-by", "value"),
        Input("current-theme", "data"),
    )
    def render_cytoscape(engine, newick, layout_type, meta_json, color_by, theme):
        if engine != "cytoscape" or not newick:
            return [], {"name": "preset"}, _get_cyto_stylesheet(theme)
        meta_df = pd.read_json(io.StringIO(meta_json)) if meta_json else None
        elements = _build_cytoscape_elements(newick, meta_df, color_by)
        layout_config = {"name": layout_type, "animate": True, "animationDuration": 500}
        if layout_type == "dagre":
            layout_config.update({"rankDir": "LR", "spacingFactor": 1.5})
        elif layout_type == "breadthfirst":
            layout_config.update({"directed": True, "spacingFactor": 1.5})
        return elements, layout_config, _get_cyto_stylesheet(theme)

    @app.callback(
        Output("node-info", "children"),
        Input("tree-cytoscape", "tapNodeData"),
        Input("tree-graph", "clickData"),
        Input("engine", "value"),
    )
    def show_node_info(cyto_data, plotly_click, engine):
        if engine == "cytoscape" and cyto_data:
            return cyto_data.get("tooltip", cyto_data.get("label", ""))
        if engine == "plotly" and plotly_click:
            point = plotly_click["points"][0]
            text = point.get("hovertext", point.get("text", ""))
            return text.replace("<br>", "\n").replace("<b>", "").replace("</b>", "")
        return "Click a node to see details"

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=8053)
