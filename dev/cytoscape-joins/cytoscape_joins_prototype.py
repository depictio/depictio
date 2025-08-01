#!/usr/bin/env python3
"""
Cytoscape Data Collection Joins Visualization Prototype

This prototype demonstrates a network visualization of data collection joins using Dash Cytoscape.
- Each data collection is represented as a group/cluster
- Each column within a data collection is a node
- Edges connect joined columns across different data collections
- Theme-aware styling for dark/light modes
"""

import dash
import dash_cytoscape as cyto
import dash_mantine_components as dmc
from dash import Input, Output, callback, html, no_update
from dash_iconify import DashIconify

# Sample data to simulate data collections with joins
SAMPLE_DATA_COLLECTIONS = [
    {
        "id": "dc1",
        "name": "Users",
        "tag": "users_table",
        "columns": ["user_id", "name", "email", "department_id", "created_at"],
        "joins": [
            {
                "on_columns": ["department_id"],
                "how": "left",
                "with_dc": ["departments_table"]
            }
        ]
    },
    {
        "id": "dc2", 
        "name": "Departments",
        "tag": "departments_table",
        "columns": ["dept_id", "dept_name", "manager_id", "budget"],
        "joins": [
            {
                "on_columns": ["dept_id"],
                "how": "left", 
                "with_dc": ["users_table"]
            }
        ]
    },
    {
        "id": "dc3",
        "name": "Projects", 
        "tag": "projects_table",
        "columns": ["project_id", "project_name", "manager_id", "status", "start_date"],
        "joins": [
            {
                "on_columns": ["manager_id"],
                "how": "inner",
                "with_dc": ["users_table"]
            }
        ]
    }
]

# Cytoscape color schemes for dark/light themes
LIGHT_THEME = {
    "background": "#ffffff",
    "data_collection": "#f8f9fa",
    "data_collection_border": "#dee2e6",
    "column_node": "#e3f2fd",
    "column_node_border": "#1976d2",
    "column_text": "#212529",
    "join_edge": "#ff9800",
    "join_edge_text": "#212529",
    "group_label": "#495057"
}

DARK_THEME = {
    "background": "#121212",
    "data_collection": "#1e1e1e",
    "data_collection_border": "#404040",
    "column_node": "#263238",
    "column_node_border": "#64b5f6",
    "column_text": "#ffffff",
    "join_edge": "#ffb74d",
    "join_edge_text": "#ffffff",
    "group_label": "#ffffff"
}


def generate_cytoscape_elements(data_collections, theme="light"):
    """
    Generate cytoscape elements from data collections data.
    
    Args:
        data_collections: List of data collection dictionaries
        theme: "light" or "dark" theme (for future use)
        
    Returns:
        List of cytoscape elements (nodes and edges)
    """
    elements = []
    # Theme parameter available for future element-specific styling
    
    # Track column positions for layout
    dc_positions = {}
    column_counter = 0
    
    # Create data collection groups and column nodes
    for i, dc in enumerate(data_collections):
        dc_id = dc["id"]
        dc_name = dc["name"]
        dc_tag = dc["tag"]
        columns = dc["columns"]
        
        # Calculate positions for this data collection
        x_offset = i * 300  # Space data collections horizontally
        dc_positions[dc_tag] = {"x": x_offset, "columns": {}}
        
        # Create parent group node for the data collection
        elements.append({
            "data": {
                "id": f"dc_group_{dc_id}",
                "label": f"{dc_name}\n({dc_tag})",
                "parent": None,
                "type": "data_collection"
            },
            "position": {"x": x_offset + 100, "y": 50},
            "classes": "data-collection-group"
        })
        
        # Create column nodes within the data collection
        for j, column in enumerate(columns):
            column_id = f"{dc_tag}_{column}"
            y_offset = 120 + (j * 60)  # Space columns vertically
            
            dc_positions[dc_tag]["columns"][column] = {
                "x": x_offset + 100,
                "y": y_offset,
                "node_id": column_id
            }
            
            elements.append({
                "data": {
                    "id": column_id,
                    "label": column,
                    "parent": f"dc_group_{dc_id}",
                    "type": "column",
                    "dc_tag": dc_tag,
                    "dc_name": dc_name
                },
                "position": {"x": x_offset + 100, "y": y_offset},
                "classes": "column-node"
            })
            column_counter += 1
    
    # Create edges for joins
    edge_counter = 0
    for dc in data_collections:
        dc_tag = dc["tag"]
        
        if "joins" in dc:
            for join in dc["joins"]:
                on_columns = join["on_columns"]
                join_type = join["how"]
                target_dc_tags = join["with_dc"]
                
                for target_dc_tag in target_dc_tags:
                    # Find the target data collection
                    target_dc = next((d for d in data_collections if d["tag"] == target_dc_tag), None)
                    if not target_dc:
                        continue
                        
                    # Create edges between matching columns
                    for col in on_columns:
                        source_node = f"{dc_tag}_{col}"
                        
                        # Find matching column in target DC (might have different name)
                        # For now, assume same column name - could be enhanced with mapping
                        target_col = None
                        if target_dc_tag == "departments_table" and col == "department_id":
                            target_col = "dept_id"
                        elif target_dc_tag == "users_table" and col == "dept_id":  
                            target_col = "department_id"
                        elif target_dc_tag == "users_table" and col == "manager_id":
                            target_col = "user_id"  # Manager is a user
                        else:
                            target_col = col  # Default: same name
                            
                        target_node = f"{target_dc_tag}_{target_col}"
                        
                        # Check if target column exists
                        target_dc_obj = next((d for d in data_collections if d["tag"] == target_dc_tag), None)
                        if target_dc_obj and target_col in target_dc_obj["columns"]:
                            elements.append({
                                "data": {
                                    "id": f"edge_{edge_counter}",
                                    "source": source_node,
                                    "target": target_node,
                                    "label": f"{join_type} join",
                                    "join_type": join_type
                                },
                                "classes": "join-edge"
                            })
                            edge_counter += 1
    
    return elements


def get_cytoscape_stylesheet(theme="light"):
    """
    Generate cytoscape stylesheet for the given theme.
    
    Args:
        theme: "light" or "dark" theme
        
    Returns:
        List of cytoscape style dictionaries
    """
    colors = LIGHT_THEME if theme == "light" else DARK_THEME
    
    return [
        # Data collection group styling
        {
            "selector": ".data-collection-group",
            "style": {
                "background-color": colors["data_collection"],
                "border-color": colors["data_collection_border"],
                "border-width": 2,
                "border-style": "solid",
                "label": "data(label)",
                "text-valign": "top",
                "text-halign": "center",
                "color": colors["group_label"],
                "font-size": "14px",
                "font-weight": "bold",
                "padding": "10px",
                "shape": "round-rectangle",
                "width": "200px",
                "height": "auto"
            }
        },
        
        # Column node styling
        {
            "selector": ".column-node",
            "style": {
                "background-color": colors["column_node"],
                "border-color": colors["column_node_border"],
                "border-width": 2,
                "border-style": "solid",
                "label": "data(label)",
                "color": colors["column_text"],
                "text-valign": "center",
                "text-halign": "center",
                "font-size": "12px",
                "width": "120px",
                "height": "30px",
                "shape": "round-rectangle"
            }
        },
        
        # Join edge styling
        {
            "selector": ".join-edge",
            "style": {
                "curve-style": "bezier",
                "target-arrow-shape": "triangle",
                "target-arrow-color": colors["join_edge"],
                "line-color": colors["join_edge"],
                "line-style": "solid",
                "width": 3,
                "label": "data(label)",
                "font-size": "10px",
                "color": colors["join_edge_text"],
                "text-rotation": "autorotate",
                "text-margin-y": -10
            }
        },
        
        # Hover effects
        {
            "selector": ".column-node:hover",
            "style": {
                "border-width": 3,
                "scale": 1.1
            }
        },
        
        # Selected node styling
        {
            "selector": ".column-node:selected",
            "style": {
                "border-width": 4,
                "border-color": "#e91e63",
                "background-color": "#fce4ec"
            }
        }
    ]


# Initialize Dash app
app = dash.Dash(__name__)

app.layout = dmc.MantineProvider(
    [
        dmc.Container([
            # Header
            dmc.Title("Data Collection Joins Visualization", order=1, mb="lg"),
            
            # Theme toggle and controls
            dmc.Group([
                dmc.SegmentedControl(
                    id="theme-toggle",
                    value="light",
                    data=[
                        {"value": "light", "label": "Light"},
                        {"value": "dark", "label": "Dark"}
                    ],
                    color="blue"
                ),
                dmc.Button(
                    "Reset Layout",
                    id="reset-layout-btn",
                    leftSection=DashIconify(icon="mdi:refresh", width=16),
                    variant="outline"
                ),
                dmc.Button(
                    "Fit to View", 
                    id="fit-view-btn",
                    leftSection=DashIconify(icon="mdi:fit-to-page", width=16),
                    variant="outline"
                )
            ], mb="md"),
            
            # Info panel
            dmc.Alert(
                [
                    DashIconify(icon="mdi:information-outline", width=20),
                    dmc.Text([
                        "This visualization shows data collection joins as a network graph. ",
                        "Each rectangular group represents a data collection, with columns as nodes inside. ",
                        "Edges connect joined columns across collections. ",
                        "Click nodes to see details, drag to reposition."
                    ], size="sm")
                ],
                color="blue",
                variant="light",
                mb="md"
            ),
            
            # Cytoscape component
            dmc.Paper([
                cyto.Cytoscape(
                    id="cytoscape-joins",
                    elements=generate_cytoscape_elements(SAMPLE_DATA_COLLECTIONS, "light"),
                    stylesheet=get_cytoscape_stylesheet("light"),
                    layout={
                        "name": "preset",  # Use preset positions
                        "animate": True,
                        "animationDuration": 500
                    },
                    style={
                        "width": "100%",
                        "height": "600px",
                        "background-color": LIGHT_THEME["background"]
                    },
                    responsive=True,
                    minZoom=0.3,
                    maxZoom=3.0,
                    wheelSensitivity=0.1
                )
            ], p="md", withBorder=True),
            
            # Selection info panel
            dmc.Paper([
                dmc.Title("Selection Details", order=3, size="h4", mb="sm"),
                html.Div(id="selection-info", children="Click on a node to see details")
            ], p="md", mt="md", withBorder=True)
            
        ], size="xl", p="md")
    ],
    id="mantine-provider"
)


# Callbacks
@callback(
    [Output("cytoscape-joins", "elements"),
     Output("cytoscape-joins", "stylesheet"),  
     Output("cytoscape-joins", "style"),
     Output("mantine-provider", "theme")],
    [Input("theme-toggle", "value")],
    prevent_initial_call=False
)
def update_theme(theme):
    """Update cytoscape theme based on toggle."""
    colors = LIGHT_THEME if theme == "light" else DARK_THEME
    
    elements = generate_cytoscape_elements(SAMPLE_DATA_COLLECTIONS, theme)
    stylesheet = get_cytoscape_stylesheet(theme)
    style = {
        "width": "100%", 
        "height": "600px",
        "background-color": colors["background"]
    }
    
    mantine_theme = {
        "colorScheme": theme
    }
    
    return elements, stylesheet, style, mantine_theme


@callback(
    Output("cytoscape-joins", "layout"),
    [Input("reset-layout-btn", "n_clicks")],
    prevent_initial_call=True
)
def reset_layout(n_clicks):
    """Reset layout to preset positions."""
    if n_clicks:
        return {
            "name": "preset",
            "animate": True, 
            "animationDuration": 500
        }
    return no_update


@callback(
    Output("selection-info", "children"),
    [Input("cytoscape-joins", "selectedNodeData")],
    prevent_initial_call=True
)
def display_selected_node(selected_nodes):
    """Display information about selected nodes."""
    if not selected_nodes:
        return "Click on a node to see details"
    
    node = selected_nodes[0]  # Show first selected node
    node_type = node.get("type", "unknown")
    
    if node_type == "column":
        return dmc.Stack([
            dmc.Group([
                DashIconify(icon="mdi:table-column", width=20, color="blue"),
                dmc.Text(f"Column: {node['label']}", fw="bold")
            ]),
            dmc.Text(f"Data Collection: {node.get('dc_name', 'Unknown')}"),
            dmc.Text(f"Tag: {node.get('dc_tag', 'Unknown')}"),
            dmc.Code(f"ID: {node['id']}")
        ], gap="xs")
    
    elif node_type == "data_collection":
        return dmc.Stack([
            dmc.Group([
                DashIconify(icon="mdi:database", width=20, color="green"),
                dmc.Text(f"Data Collection: {node['label']}", fw="bold")
            ]),
            dmc.Code(f"ID: {node['id']}")
        ], gap="xs")
    
    return dmc.Text("Unknown node type")


# Fit-to-view callback (simplified version)
@callback(
    Output("cytoscape-joins", "zoom"),
    [Input("fit-view-btn", "n_clicks")],
    prevent_initial_call=True
)
def fit_to_view(n_clicks):
    """Trigger a zoom reset to fit all elements."""
    if n_clicks:
        return {"zoom": 1, "pan": {"x": 0, "y": 0}}
    return no_update


if __name__ == "__main__":
    app.run(debug=True, port=8052)