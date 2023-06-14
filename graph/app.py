import dash
import dash_cytoscape as cyto
import dash_html_components as html
import dash_core_components as dcc
import dash_table
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
import pandas as pd
import numpy as np
import random

# Load extra layouts
cyto.load_extra_layouts()

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
server = app.server

# Create nodes
nodes = []
num_nodes = 20

for i in range(num_nodes):
    node_id = f"species{i + 1}"
    node_label = f"Species {i + 1}"
    node_href = f"https://via.placeholder.com/150/{np.base_repr(np.random.randint(0, 16777215), base=16).zfill(6)}/FFFFFF?text=Species{i + 1}"

    num_edges = random.randint(1, 3) if i < num_nodes - 2 else random.randint(8, 12)

    nodes.append(
        {
            "data": {
                "id": node_id,
                "label": node_label,
                "href": node_href,
                "num_edges": num_edges,
            }
        }
    )
# Create edges
edges = []
num_edges = 0

for source_node in nodes:
    source_node_id = source_node["data"]["id"]
    available_targets = [
        node
        for node in nodes
        if node["data"]["id"] != source_node_id and node["data"]["num_edges"] > 0
    ]

    num_source_edges = source_node["data"]["num_edges"]

    while num_source_edges > 0 and len(available_targets) > 0:
        num_target_edges = min(num_source_edges, len(available_targets))
        selected_targets = random.sample(available_targets, num_target_edges)

        for target_node in selected_targets:
            target_node_id = target_node["data"]["id"]

            edge_id = f"edge{num_edges + 1}"
            intensity = random.uniform(0.1, 1.0)
            edge_image = f"https://via.placeholder.com/150/{np.base_repr(np.random.randint(0, 16777215), base=16).zfill(6)}/FFFFFF?text={source_node_id}-{target_node_id}"

            edges.append(
                {
                    "data": {
                        "id": edge_id,
                        "source": source_node_id,
                        "target": target_node_id,
                        "image": edge_image,
                        "intensity": intensity,
                    }
                }
            )

            num_edges += 1
            num_source_edges -= 1
            # target_node["data"]["num_edges"] -= 1

        available_targets = [
            node
            for node in nodes
            if node["data"]["id"] != source_node_id and node["data"]["num_edges"] > 0
        ]

    source_node["data"]["num_edges"] = num_source_edges

cyto_graph = cyto.Cytoscape(
    id="cytoscape-graph",
    layout={"name": "cola"},
    style={"width": "100vw", "height": "50vh"},
    elements=nodes + edges,
    responsive=True,
)

modal = dbc.Modal(
    [
        dbc.ModalHeader("Edge Image"),
        dbc.ModalBody(html.Img(id="modal-image", src="", height="300px")),
        dbc.ModalFooter(dbc.Button("Close", id="close", className="ml-auto")),
    ],
    id="modal",
    size="lg",
    is_open=False,
)

app.layout = html.Div(
    [
        cyto_graph,
        modal,
        html.Div(id="node-info", children="No node selected"),
    ]
)


@app.callback(
    Output("node-info", "children"),
    [Input("cytoscape-graph", "tapNodeData")],
    [State("cytoscape-graph", "elements")],
)
def update_info(node_data, elements):
    if node_data is None:
        return "No node selected"
    else:
        node_id = node_data["id"]
        edges_data = [
            {
                "Property": f"Property {str(random.randint(1,3))}",
                "Intensity": round(edge["data"]["intensity"], 4),
                "Target": edge["data"]["target"]
                if edge["data"]["source"] == node_id
                else edge["data"]["source"],
            }
            for edge in elements
            if edge["data"].get("source") == node_id
            or edge["data"].get("target") == node_id
        ]
        table = dash_table.DataTable(
            data=edges_data,
            columns=[
                {"name": "Property", "id": "Property"},
                {"name": "Intensity", "id": "Intensity"},
                {"name": "Target", "id": "Target"},
            ],
            style_as_list_view=True,
            style_cell={
                "backgroundColor": "white",
                "font-family": "Arial",
                "minWidth": "0px",
                "maxWidth": "180px",
                "whiteSpace": "normal",
                "textAlign": "center",
            },
            style_header={
                "backgroundColor": "white",
                "fontWeight": "bold",
                "textAlign": "center",
            },
            style_table={
                "width": "40%",
                "margin-left": "auto",
                "margin-right": "auto",
            },
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": "rgb(248, 248, 248)"},
                {
                    "if": {
                        "column_id": "Property",
                        "filter_query": '{Property} eq "Property 1"',
                    },
                    "backgroundColor": "pink",
                    "color": "black",
                },
                {
                    "if": {
                        "column_id": "Property",
                        "filter_query": '{Property} eq "Property 2"',
                    },
                    "backgroundColor": "lightgreen",
                    "color": "black",
                },
                {
                    "if": {
                        "column_id": "Property",
                        "filter_query": '{Property} eq "Property 3"',
                    },
                    "backgroundColor": "lightblue",
                    "color": "black",
                },
            ],
        )
        link = html.A(
            f"Open {node_data['label']} data in new tab",
            href=node_data["href"],
            target="_blank",
        )
        num_edges = len(
            edges_data
        )  # Count the number of edges connected to the current node
        return html.Div(
            [
                html.H5(
                    f"Node: {node_data['label']}, number of edges {num_edges}",
                    style={"textAlign": "center"},
                ),
                html.Div(table),
                # html.P("Link:", style={"textAlign": "center"}),
                html.Div(link, style={"textAlign": "center"}),
            ]
        )


@app.callback(
    Output("modal", "is_open"),
    [Input("cytoscape-graph", "tapEdgeData"), Input("close", "n_clicks")],
    [State("modal", "is_open")],
)
def toggle_modal(edge_data, close_clicks, is_open):
    if edge_data or close_clicks:
        return not is_open
    return is_open


@app.callback(
    Output("modal-image", "src"),
    [Input("cytoscape-graph", "tapEdgeData")],
)
def update_modal_src(edge_data):
    if edge_data:
        return edge_data["image"]
    return ""


from colorsys import hls_to_rgb


@app.callback(
    Output("cytoscape-graph", "stylesheet"),
    [Input("cytoscape-graph", "elements")],
)
def update_node_color(elements):
    elements_dict = {"nodes": [], "edges": []}
    for element in elements:
        if "source" in element.get("data", {}):
            elements_dict["edges"].append(element)
        else:
            elements_dict["nodes"].append(element)

    max_edge_count = max(
        sum(
            1
            for edge in elements_dict["edges"]
            if edge["data"].get("source") == node["data"]["id"]
            or edge["data"].get("target") == node["data"]["id"]
        )
        for node in elements_dict["nodes"]
    )

    stylesheet = []

    for node in elements_dict["nodes"]:
        node_id = node["data"]["id"]
        edge_count = sum(
            1
            for edge in elements_dict["edges"]
            if edge["data"].get("source") == node_id
            or edge["data"].get("target") == node_id
        )
        hue = 240 - (edge_count / max_edge_count) * 120
        lightness = 50
        saturation = 75

        red, green, blue = hls_to_rgb(hue / 360, lightness / 100, saturation / 100)
        rgb_color = f"rgb({int(red * 255)}, {int(green * 255)}, {int(blue * 255)})"

        node_style = {
            "selector": f'node[id="{node_id}"]',
            "style": {
                "background-color": rgb_color,
                "label": node["data"]["label"].replace("Species ", ""),
                "text-valign": "center",
                "text-halign": "center",
            },
        }
        stylesheet.append(node_style)

    for edge in elements_dict["edges"]:
        edge_id = edge["data"]["id"]
        intensity = edge["data"].get(
            "intensity", 1
        )  # Default intensity to 1 if not provided
        edge_style = {
            "selector": f'edge[id="{edge_id}"]',
            "style": {
                "width": intensity * 5,  # Adjust the width based on intensity
                "line-color": "gray",
            },
        }
        stylesheet.append(edge_style)

    return stylesheet


if __name__ == "__main__":
    app.run_server(debug=True)
