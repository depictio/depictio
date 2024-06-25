import dash
import dash_cytoscape as cyto

# import dash_html_components as html
# import dash_core_components as dcc
from dash import dcc, html
from dash import dash_table
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
import pandas as pd
import numpy as np
import random
import dash_leaflet as dl
import dash_leaflet.express as dlx
from dash_extensions.javascript import arrow_function
from utils import Graph, generate_metadata

# Load extra layouts
cyto.load_extra_layouts()

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
server = app.server


# Some sample locations for the markers
locations = [
    {"name": "London", "lat": 51.5074, "lon": -0.1278},
    {"name": "Paris", "lat": 48.8566, "lon": 2.3522},
    {"name": "Berlin", "lat": 52.5200, "lon": 13.4050},
    {"name": "Rome", "lat": 41.9028, "lon": 12.4964},
]

locations_graph = {}
for j, city_dict in enumerate(locations):
    random.seed(j)
    locations_graph[city_dict["name"]] = Graph(
        random.randint(17, 22), city_dict["name"]
    )


metadata = generate_metadata(locations)
for location, data in metadata.items():
    print(f"{location}: {data}")


# Convert the location dict to geojson format

# print(dlx.dicts_to_geojson(locations))


def point_to_layer(feature, latlng):
    return dl.Marker(
        position=latlng, children=[dl.Tooltip(feature["properties"]["name"])]
    )


bermuda = dlx.dicts_to_geojson(locations)

# Create the map
leaflet_map = dl.Map(
    children=[
        dl.TileLayer(),
        dl.GeoJSON(
            data=bermuda,
            id="markers",
            cluster=True,
            zoomToBounds=True,
            # options=dict(pointToLayer=point_to_layer),
        ),
        # options=dict(pointToLayer=lambda geojson, latlng: dl.Marker(latlng, children=[dl.Tooltip(geojson["properties"]["name"])])))
    ],
    id="leaflet-map",
    style={
        "width": "100%",
        "height": "50vh",
        "margin": "auto",
        "display": "block",
        "border": "0.5px solid grey",
    },
)


cyto_graph = cyto.Cytoscape(
    id="cytoscape-graph",
    layout={"name": "cola"},
    style={"width": "50vw", "height": "50vh", "border": "0.5px solid grey"},
    elements=[] + [],
    # elements=locations_graph[locations[0]["name"]].nodes + locations_graph[locations[0]["name"]].edges,
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
        dbc.Row(
            [
                dbc.Col(html.Div([leaflet_map]), width=6),
                dbc.Col(html.Div([cyto_graph]), width=6),
            ],
            align="center",
        ),
        dbc.Row(
            [
                dbc.Col(html.Div(id="city-info", children="No city selected")),
                dbc.Col(html.Div(id="node-info", children="No node selected")),
            ]
        ),
        modal,
    ]
)


@app.callback(
    [
        Output("cytoscape-graph", "elements"),
        Output("node-info", "children"),
        Output("city-info", "children"),
    ],
    [Input("markers", "click_feature"), Input("cytoscape-graph", "tapNodeData")],
    [State("cytoscape-graph", "elements")],
)
def update_info(feature, node_data, elements):
    ctx = dash.callback_context
    if not ctx.triggered:
        return elements, "No node selected", "No city selected"
    else:
        input_id = ctx.triggered[0]["prop_id"].split(".")[0]

    # print(input_id)

    if input_id == "markers":
        if feature is not None:
            name = feature["properties"]["name"]
            nodes = locations_graph[name].nodes
            edges = locations_graph[name].edges

            columns_mapping = {
                "name": "Location",
                "lat": "Latitude",
                "lon": "Longitude",
                "time": "Time",
                "temperature": "Temperature (°C)",
                "humidity": "Humidity (%)",
                "pressure": "Pressure (hPa)",
            }

            # Transpose the metadata
            transposed_metadata = pd.DataFrame([metadata[name]]).rename(
                columns_mapping, axis=1
            )

            transposed_metadata = transposed_metadata.T.reset_index()
            print(transposed_metadata)

            # Rename the columns
            transposed_metadata.columns = ["Parameter", "Value"]
            print(transposed_metadata)
            print(transposed_metadata.to_dict("records"))

            # Melt the DataFrame to reshape it into two columns
            # transposed_metadata = transposed_metadata.melt(id_vars=["Parameter"], var_name="Location", value_name="Value")
            # print(transposed_metadata)

            metadata_table = dash_table.DataTable(
                data=transposed_metadata.to_dict("records"),
                columns=[
                    {"name": "Parameter", "id": "Parameter"},
                    {"name": "Value", "id": "Value"},
                ],
                style_cell={"textAlign": "center"},
                style_header={"fontWeight": "bold"},
            )

            return nodes + edges, "No node selected", metadata_table
            # return nodes + edges, "No node selected", f"You clicked on {name} marker"
        else:
            return elements, "No node selected", "No city selected"
    elif input_id == "cytoscape-graph":
        # print(node_data)
        # print(elements)
        if node_data is None:
            return elements, "No node selected", "No city selected"
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
                    "width": "60%",
                    "margin-left": "auto",
                    "margin-right": "auto",
                },
                style_data_conditional=[
                    {
                        "if": {"row_index": "odd"},
                        "backgroundColor": "rgb(248, 248, 248)",
                    },
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

            if feature is not None:
                name = feature["properties"]["name"]

                columns_mapping = {
                    "name": "Location",
                    "lat": "Latitude",
                    "lon": "Longitude",
                    "time": "Time",
                    "temperature": "Temperature (°C)",
                    "humidity": "Humidity (%)",
                    "pressure": "Pressure (hPa)",
                }

                # Transpose the metadata
                transposed_metadata = pd.DataFrame([metadata[name]]).rename(
                    columns_mapping, axis=1
                )

                transposed_metadata = transposed_metadata.T.reset_index()
                print(transposed_metadata)

                # Rename the columns
                transposed_metadata.columns = ["Parameter", "Value"]
                print(transposed_metadata)
                print(transposed_metadata.to_dict("records"))

                # Melt the DataFrame to reshape it into two columns
                # transposed_metadata = transposed_metadata.melt(id_vars=["Parameter"], var_name="Location", value_name="Value")
                # print(transposed_metadata)

                metadata_table = dash_table.DataTable(
                    data=transposed_metadata.to_dict("records"),
                    columns=[
                        {"name": "Parameter", "id": "Parameter"},
                        {"name": "Value", "id": "Value"},
                    ],
                    style_cell={"textAlign": "center"},
                    style_header={"fontWeight": "bold"},
                )
                return (
                    elements,
                    html.Div(
                        [
                            html.H5(
                                f"Node: {node_data['label']}, number of edges {num_edges}",
                                style={"textAlign": "center"},
                            ),
                            html.Div(table),
                            # html.P("Link:", style={"textAlign": "center"}),
                            html.Div(link, style={"textAlign": "center"}),
                        ]
                    ),
                    metadata_table,
                    # f"You clicked on {name} marker",
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

    # Calculate max_edge_count or assign it a default value
    if elements_dict["nodes"]:
        max_edge_count = max(
            sum(
                1
                for edge in elements_dict["edges"]
                if edge["data"].get("source") == node["data"]["id"]
                or edge["data"].get("target") == node["data"]["id"]
            )
            for node in elements_dict["nodes"]
        )
    else:
        max_edge_count = 1  # Default value, change if needed

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
    app.run_server(debug=True, port=8052)
