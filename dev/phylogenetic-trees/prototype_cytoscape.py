"""
Prototype 2: Phylogenetic Tree Visualization with Dash Cytoscape.

Renders trees using Cytoscape.js with built-in layout algorithms.
Supports dagre (hierarchical), breadthfirst, circle, and preset (manual coords).
Includes node selection, highlighting, and metadata tooltips.

Run: python prototype_cytoscape.py

Inspired by:
- Dash Cytoscape Biopython example (https://dash.plotly.com/cytoscape/biopython)
- Microreact interactive tree (https://microreact.org/)
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import dash_cytoscape as cyto
import dash_mantine_components as dmc
import pandas as pd
from dash import Dash, Input, Output, State, callback_context, dcc
from dash_iconify import DashIconify
from tree_utils import (
    compute_rectangular_coords,
    merge_metadata_to_nodes,
    parse_newick,
)

# Load extra cytoscape layouts
cyto.load_extra_layouts()

DATA_DIR = Path(__file__).parent / "data"

SAMPLE_TREES = {
    "Mammals (15 taxa)": (DATA_DIR / "sample_tree.nwk").read_text().strip(),
    "Bacteria (21 taxa)": (DATA_DIR / "bacterial_tree.nwk").read_text().strip(),
    "Simple example": "((A:0.1,B:0.2):0.3,(C:0.4,(D:0.5,E:0.6):0.1):0.2);",
}

LAYOUT_OPTIONS = [
    {"value": "preset", "label": "Phylogram (preset coords)"},
    {"value": "dagre", "label": "Dagre (hierarchical)"},
    {"value": "breadthfirst", "label": "Breadthfirst"},
    {"value": "circle", "label": "Circle"},
    {"value": "concentric", "label": "Concentric"},
    {"value": "cose", "label": "CoSE (force-directed)"},
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


def newick_to_cytoscape_elements(
    newick_str: str,
    layout_type: str = "preset",
    metadata_df: pd.DataFrame | None = None,
    color_by: str | None = None,
) -> list[dict]:
    """Convert a Newick tree string to Cytoscape elements.

    For 'preset' layout, uses computed rectangular coordinates.
    For other layouts, Cytoscape handles positioning.

    Returns:
        List of Cytoscape element dicts (nodes + edges).
    """
    tree = parse_newick(newick_str)
    coords = compute_rectangular_coords(tree)
    nodes = coords["nodes"]

    # Merge metadata
    if metadata_df is not None:
        taxon_col = metadata_df.columns[0]
        nodes = merge_metadata_to_nodes(nodes, metadata_df, taxon_col)

    # Build color map
    color_map: dict[str, str] = {}
    if color_by and metadata_df is not None and color_by in metadata_df.columns:
        unique_vals = sorted(metadata_df[color_by].dropna().unique().tolist(), key=str)
        color_map = {str(v): PALETTE[i % len(PALETTE)] for i, v in enumerate(unique_vals)}

    elements = []
    node_ids: dict[tuple[float, float], str] = {}

    # Scale factor for preset layout
    x_scale = 800
    y_scale = 40

    for i, node in enumerate(nodes):
        node_id = node["name"] if node["name"] else f"internal_{i}"
        node_ids[(node["x"], node["y"])] = node_id

        # Build tooltip from metadata
        meta = node.get("metadata", {})
        tooltip_parts = [node["name"]] if node["name"] else []
        for k, v in meta.items():
            tooltip_parts.append(f"{k}: {v}")
        tooltip = "\n".join(tooltip_parts)

        # Determine color
        node_color = "#666"
        group_label = ""
        if color_by and meta:
            val = str(meta.get(color_by, ""))
            if val in color_map:
                node_color = color_map[val]
                group_label = val

        classes = "leaf" if node["is_leaf"] else "internal"

        element: dict = {
            "data": {
                "id": node_id,
                "label": node["name"].replace("_", " ") if node["is_leaf"] else "",
                "is_leaf": node["is_leaf"],
                "tooltip": tooltip,
                "color": node_color,
                "group_label": group_label,
                "branch_length": node["branch_length"],
            },
            "classes": classes,
        }

        if layout_type == "preset":
            element["position"] = {
                "x": node["x"] * x_scale,
                "y": node["y"] * y_scale,
            }

        elements.append(element)

    # Build edges using the rectangular coordinate structure
    # Re-traverse the tree to get parent-child relationships
    tree = parse_newick(newick_str)
    edge_id = 0

    def add_edges(clade, parent_id=None):
        nonlocal edge_id
        name = clade.name or ""
        # Find this node in our nodes list
        node_id = None
        for j, n in enumerate(nodes):
            n_name = n["name"] if n["name"] else f"internal_{j}"
            if clade.name and n["name"] == clade.name:
                node_id = n_name
                break
            if not clade.name and not n["is_leaf"] and abs(n["x"] - _get_x(clade, tree)) < 1e-10:
                node_id = f"internal_{j}"
                break

        if node_id is None:
            node_id = name or f"node_{edge_id}"

        if parent_id is not None:
            elements.append(
                {
                    "data": {
                        "id": f"edge_{edge_id}",
                        "source": parent_id,
                        "target": node_id,
                    }
                }
            )
            edge_id += 1

        for child in clade.clades:
            add_edges(child, node_id)

    # Simpler edge building: use coordinates to match
    # Build from tree structure directly
    elements_edges = _build_edges_from_tree(tree, nodes)
    elements.extend(elements_edges)

    return elements


def _get_x(clade, tree) -> float:
    """Get x-position (depth) of a clade."""
    depth = 0.0
    path = tree.get_path(clade)
    if path:
        for c in path:
            depth += c.branch_length or 0.0
    return depth


def _build_edges_from_tree(tree, nodes: list[dict]) -> list[dict]:
    """Build cytoscape edges from tree parent-child relationships."""
    edges = []
    node_lookup: dict[str, str] = {}

    # Create a mapping from clade to node_id
    internal_counter = [0]

    def _get_node_id(clade, depth: float) -> str:
        if clade.name:
            return clade.name

        # Match internal node by position
        for i, n in enumerate(nodes):
            if not n["is_leaf"] and not n["name"]:
                candidate_id = f"internal_{i}"
                if (
                    candidate_id not in node_lookup.values()
                    or node_lookup.get(id(clade)) == candidate_id
                ):
                    if abs(n["x"] - depth) < 1e-8:
                        node_lookup[id(clade)] = candidate_id
                        return candidate_id

        fallback = f"internal_{internal_counter[0]}"
        internal_counter[0] += 1
        return fallback

    edge_count = 0

    def _traverse(clade, parent_id: str | None, depth: float):
        nonlocal edge_count
        current_id = _get_node_id(clade, depth)

        if parent_id is not None:
            edges.append(
                {
                    "data": {
                        "id": f"edge_{edge_count}",
                        "source": parent_id,
                        "target": current_id,
                    }
                }
            )
            edge_count += 1

        for child in clade.clades:
            child_depth = depth + (child.branch_length or 0.0)
            _traverse(child, current_id, child_depth)

    _traverse(tree.root, None, 0.0)
    return edges


def get_cytoscape_stylesheet(theme: str = "light") -> list[dict]:
    """Build Cytoscape stylesheet for tree rendering."""
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
            "style": {
                "width": 5,
                "height": 5,
                "background-color": "#888",
                "shape": "ellipse",
            },
        },
        {
            "selector": "edge",
            "style": {
                "width": 1.5,
                "line-color": edge_color,
                "curve-style": "bezier",
                "target-arrow-shape": "none",
            },
        },
        {
            "selector": ":selected",
            "style": {
                "background-color": "#ff0",
                "border-color": "#ff0",
                "border-width": 3,
            },
        },
        {
            "selector": "node:active",
            "style": {
                "overlay-opacity": 0,
            },
        },
    ]


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
                                        DashIconify(
                                            icon="mdi:graph-outline", width=28, color="teal"
                                        ),
                                        dmc.Title(
                                            "Phylogenetic Tree — Cytoscape Prototype", order=3
                                        ),
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
                                dmc.Text("Layout Algorithm", fw="bold", size="sm"),
                                dmc.SegmentedControl(
                                    id="layout-type",
                                    data=LAYOUT_OPTIONS,
                                    value="preset",
                                    orientation="vertical",
                                    fullWidth=True,
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
                                dmc.Divider(),
                                dmc.Text("Node Info", fw="bold", size="sm"),
                                dmc.Paper(
                                    dmc.Text(
                                        id="node-info", size="xs", style={"whiteSpace": "pre-wrap"}
                                    ),
                                    p="xs",
                                    withBorder=True,
                                    style={"minHeight": 60},
                                ),
                            ],
                            gap="xs",
                            p="md",
                        ),
                    ),
                    dmc.AppShellMain(
                        cyto.Cytoscape(
                            id="tree-cytoscape",
                            layout={"name": "preset"},
                            style={"width": "100%", "height": "calc(100vh - 60px)"},
                            elements=[],
                            stylesheet=get_cytoscape_stylesheet("light"),
                            responsive=True,
                            userPanningEnabled=True,
                            userZoomingEnabled=True,
                            boxSelectionEnabled=True,
                        ),
                    ),
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
        new_theme = "dark" if current == "light" else "light"
        return new_theme, new_theme

    @app.callback(
        Output("current-newick", "data"),
        Input("tree-selector", "value"),
        Input("newick-upload", "contents"),
        prevent_initial_call=True,
    )
    def update_newick(selected_sample, upload_contents):
        ctx = callback_context
        trigger_id = ctx.triggered[0]["prop_id"] if ctx.triggered else ""

        if "newick-upload" in trigger_id and upload_contents:
            content_type, content_string = upload_contents.split(",")
            decoded = base64.b64decode(content_string).decode("utf-8")
            return decoded.strip()

        if selected_sample in SAMPLE_TREES:
            return SAMPLE_TREES[selected_sample]

        return SAMPLE_TREES[list(SAMPLE_TREES.keys())[1]]

    @app.callback(
        Output("current-metadata", "data"),
        Output("color-by", "data"),
        Output("color-by", "value"),
        Output("color-by", "disabled"),
        Input("metadata-upload", "contents"),
        Input("tree-selector", "value"),
    )
    def update_metadata(upload_contents, selected_sample):
        ctx = callback_context
        trigger_id = ctx.triggered[0]["prop_id"] if ctx.triggered else ""

        metadata_df = None

        if "tree-selector" in trigger_id or not ctx.triggered:
            if selected_sample == "Bacteria (21 taxa)":
                meta_path = DATA_DIR / "sample_metadata.csv"
                if meta_path.exists():
                    metadata_df = pd.read_csv(meta_path)
            elif selected_sample == "Mammals (15 taxa)":
                meta_path = DATA_DIR / "mammal_metadata.csv"
                if meta_path.exists():
                    metadata_df = pd.read_csv(meta_path)

        if "metadata-upload" in trigger_id and upload_contents:
            content_type, content_string = upload_contents.split(",")
            decoded = base64.b64decode(content_string).decode("utf-8")
            metadata_df = pd.read_csv(io.StringIO(decoded))

        if metadata_df is not None:
            cols = list(metadata_df.columns[1:])
            col_options = [{"value": c, "label": c} for c in cols]
            default_color = cols[0] if cols else None
            return metadata_df.to_json(), col_options, default_color, False

        return None, [], None, True

    @app.callback(
        Output("tree-cytoscape", "elements"),
        Output("tree-cytoscape", "layout"),
        Output("tree-cytoscape", "stylesheet"),
        Input("current-newick", "data"),
        Input("layout-type", "value"),
        Input("current-metadata", "data"),
        Input("color-by", "value"),
        Input("current-theme", "data"),
    )
    def render_tree(newick_str, layout_type, metadata_json, color_by, theme):
        if not newick_str:
            return [], {"name": "preset"}, get_cytoscape_stylesheet(theme)

        metadata_df = None
        if metadata_json:
            metadata_df = pd.read_json(io.StringIO(metadata_json))

        elements = newick_to_cytoscape_elements(
            newick_str,
            layout_type=layout_type,
            metadata_df=metadata_df,
            color_by=color_by,
        )

        layout_config = {"name": layout_type, "animate": True, "animationDuration": 500}

        if layout_type == "dagre":
            layout_config.update({"rankDir": "LR", "spacingFactor": 1.5})
        elif layout_type == "breadthfirst":
            layout_config.update({"directed": True, "spacingFactor": 1.5})
        elif layout_type == "concentric":
            layout_config.update({"minNodeSpacing": 40})

        stylesheet = get_cytoscape_stylesheet(theme)

        return elements, layout_config, stylesheet

    @app.callback(
        Output("node-info", "children"),
        Input("tree-cytoscape", "tapNodeData"),
    )
    def display_node_info(data):
        if not data:
            return "Click a node to see details"

        tooltip = data.get("tooltip", "")
        if tooltip:
            return tooltip

        label = data.get("label", data.get("id", ""))
        return f"Node: {label}"

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=8052)
