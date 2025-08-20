#!/usr/bin/env python3
"""
Depictio Cytoscape Joins Component

A module for integrating data collection joins visualization directly into Depictio's
existing Dash application. This creates reusable components that can be embedded
into the project data collections management interface.
"""

import dash_cytoscape as cyto
import dash_mantine_components as dmc
from dash_iconify import DashIconify

from dash import html
from depictio.dash.colors import colors


def create_joins_visualization_section(elements=None, theme="light"):
    """
    Create a complete joins visualization section for Depictio.

    Args:
        elements: Cytoscape elements (nodes and edges)
        theme: "light" or "dark" theme

    Returns:
        dmc.Stack: Complete joins visualization section
    """
    if elements is None:
        elements = []

    # Theme-specific colors using Depictio palette
    if theme == "light":
        border_color = "#dee2e6"
    else:
        border_color = "#404040"

    return dmc.Stack(
        [
            # Header with controls
            dmc.Group(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:graph-outline", width=24, color=colors["teal"]),
                            dmc.Title("Data Collection Joins", order=3, c=colors["teal"]),
                        ],
                        gap="sm",
                    ),
                    # dmc.Group(
                    #     [
                    #         dmc.Button(
                    #             "Reset Layout",
                    #             id="joins-reset-layout-btn",
                    #             leftSection=DashIconify(icon="mdi:refresh", width=16),
                    #             variant="light",
                    #             color="gray",
                    #             size="sm",
                    #         )
                    #     ],
                    #     gap="xs",
                    # ),
                ],
                justify="space-between",
                align="center",
                mb="sm",
            ),
            # Info alert
            dmc.Alert(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:information-outline", width=20),
                            dmc.Text(
                                [
                                    "This network shows relationships between data collections. ",
                                    "Each group represents a data collection with its columns as nodes. ",
                                    "Edges show join relationships between columns.",
                                ],
                                size="sm",
                            ),
                        ]
                    ),
                ],
                color="blue",
                variant="light",
                mb="sm",
            ),
            # Cytoscape visualization
            # html.Div(
            #     [
            #         cyto.Cytoscape(
            #             id="depictio-cytoscape-joins",
            #             elements=elements,
            #             stylesheet=[
            #                 {
            #                     "selector": "node",
            #                     "style": {
            #                         "content": "data(label)",
            #                         "background-color": colors["blue"],
            #                         "color": text_color,
            #                         "text-valign": "center",
            #                         "text-halign": "center",
            #                         "border-width": 1,
            #                         "border-color": colors["teal"],
            #                     },
            #                 },
            #                 {
            #                     "selector": "edge",
            #                     "style": {
            #                         "target-arrow-color": colors["orange"],
            #                         "target-arrow-shape": "triangle",
            #                         "line-color": colors["orange"],
            #                         "width": 2,
            #                     },
            #                 },
            #                 {
            #                     "selector": "node:hover",
            #                     "style": {
            #                         "border-width": 3,
            #                         "border-color": colors["pink"],
            #                     },
            #                 },
            #                 {
            #                     "selector": "edge:hover",
            #                     "style": {
            #                         "width": 4,
            #                         "opacity": 0.8,
            #                     },
            #                 },
            #                 {
            #                     "selector": ":selected",
            #                     "style": {
            #                         "border-width": 4,
            #                         "border-color": colors["green"],
            #                     },
            #                 },
            #             ],
            #             layout={
            #                 "name": "preset",
            #                 "animate": True,
            #                 "animationDuration": 500,
            #                 "fit": True,
            #                 "padding": 50,
            #             },
            #             style={"width": "100%", "height": "600px"},
            #             # responsive=True,
            #             minZoom=0.2,
            #             maxZoom=3.0,
            #             wheelSensitivity=0.1,
            #             autoRefreshLayout=True,  # Enable automatic layout refresh for better responsiveness
            #             userPanningEnabled=True,
            #             userZoomingEnabled=True,
            #             boxSelectionEnabled=True,  # Enable box selection for better user interaction
            #             autoungrabify=False,  # Allow node grabbing
            #         )
            #     ],
            #     style={
            #         "padding": "12px",
            #         "border": f"1px solid {border_color}",
            #         "borderRadius": "8px",
            #         # "backgroundColor": bg_color,
            #         "position": "relative",
            #     },
            # ),
            # COMMENTED OUT COMPLEX VERSION:
            html.Div(
                [
                    cyto.Cytoscape(
                        id="depictio-cytoscape-joins",
                        elements=elements,
                        stylesheet=get_depictio_cytoscape_stylesheet(theme),
                        layout={
                            "name": "preset",  # Use preset positions for better control
                            "animate": True,
                            "animationDuration": 500,
                            "fit": True,  # Enable auto-fit to ensure visibility
                            "padding": 50,  # Increased padding for better mouse interaction
                        },
                        style={
                            "width": "100%",
                            "height": "600px",
                            "backgroundColor": "var(--app-surface-color, #ffffff)",
                            "border": f"1px solid {border_color}",
                            "borderRadius": "8px",
                        },
                        # responsive=True,
                        minZoom=0.2,
                        maxZoom=3.0,
                        wheelSensitivity=0.1,
                        autoRefreshLayout=True,  # Enable automatic layout refresh for better responsiveness
                        userPanningEnabled=True,
                        userZoomingEnabled=True,
                        boxSelectionEnabled=True,  # Enable box selection for better user interaction
                        autoungrabify=False,  # Allow node grabbing
                    )
                ],
                style={
                    "padding": "12px",
                    "border": f"1px solid {border_color}",
                    "borderRadius": "8px",
                    "backgroundColor": "var(--app-surface-color, #ffffff)",
                    "position": "relative",  # Ensure proper positioning context
                    "zIndex": 1,  # Lower z-index to avoid event blocking
                },
            ),
            # Selection details panel
            dmc.Paper(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:cursor-default-click", width=20, color="#6c757d"),
                            dmc.Title("Selection Details", order=4, size="md"),
                        ],
                        gap="sm",
                        mb="sm",
                    ),
                    html.Div(
                        id="depictio-joins-selection-info",
                        children=dmc.Text(
                            "Click on a node or edge to see details", c="gray", size="sm"
                        ),
                    ),
                ],
                p="md",
                mt="sm",
                withBorder=True,
            ),
        ],
        gap="md",
    )


def get_depictio_cytoscape_stylesheet(theme="light"):
    """
    Get Depictio-themed cytoscape stylesheet.

    Args:
        theme: "light" or "dark" theme

    Returns:
        List of cytoscape style dictionaries
    """
    # Use Depictio color palette
    if theme == "light":
        text_color = "#212529"
        group_bg = "#f8f9fa"
        node_bg = "#e3f2fd"
        join_column_bg = f"{colors['orange']}20"
    else:
        text_color = "#ffffff"
        group_bg = "#1e1e1e"
        node_bg = "#263238"
        join_column_bg = f"{colors['orange']}30"

    return [
        # Workflow group styling (for advanced projects)
        {
            "selector": ".workflow-group",
            "style": {
                "background-color": group_bg,
                "border-color": colors["blue"],
                "border-width": 1,
                "border-style": "dashed",
                "label": "data(label)",
                "text-valign": "top",
                "text-halign": "center",
                "color": text_color,
                "font-size": "12px",
                "font-weight": "bold",
                "padding": "20px",
                "shape": "round-rectangle",
                "opacity": 0.4,
            },
        },
        # Data collection background styling (independent elements, not parent-child)
        {
            "selector": ".data-collection-background",
            "style": {
                "background-color": group_bg,
                "border-color": colors["teal"],
                "border-width": 2,
                "border-style": "solid",
                "label": "data(label)",
                "text-valign": "top",
                "text-halign": "center",
                "color": colors["teal"],  # Use high-contrast teal color that works in both themes
                "font-size": "16px",  # Increased font size for better visibility
                "font-weight": "bold",
                "shape": "round-rectangle",
                "width": "180px",
                "height": "data(box_height)",  # Dynamic height based on column count
                "text-margin-y": -15,
                "text-wrap": "wrap",
                "text-max-width": "160px",
                "z-index": 1,
                "opacity": 0.8,  # Higher opacity for better visibility
                "text-opacity": 1.0,  # Full text opacity regardless of element opacity
            },
        },
        # Styling for DCs with many columns (taller boxes)
        {
            "selector": ".dc-columns-7, .dc-columns-8, .dc-columns-9, .dc-columns-10",
            "style": {
                "height": "550px",  # Extra tall for many columns
                "width": "200px",  # Slightly wider
                "text-margin-y": -25,  # Title further up for tall boxes
                "border-width": 3,  # Thicker border for emphasis
            },
        },
        # Alternative representations for highly connected DCs
        {
            "selector": ".dc-central-hub",  # For DCs with many connections
            "style": {
                "shape": "hexagon",
                "width": "300px",
                "height": "350px",
                "border-color": colors["orange"],
                "border-width": 3,
                "background-color": f"{colors['orange']}20",
            },
        },
        {
            "selector": ".dc-few-connections",  # For DCs with 1-2 connections
            "style": {"shape": "round-rectangle", "width": "200px", "height": "300px"},
        },
        {
            "selector": ".dc-no-connections",  # For isolated DCs
            "style": {"shape": "ellipse", "width": "180px", "height": "250px", "opacity": 0.7},
        },
        # Regular column nodes - must be behind edges
        {
            "selector": ".column-node",
            "style": {
                "background-color": node_bg,
                "border-color": colors["blue"],
                "border-width": 1,
                "border-style": "solid",
                "label": "data(label)",
                "color": text_color,
                "text-valign": "center",
                "text-halign": "center",
                "font-size": "10px",
                "width": "140px",  # Wider to accommodate longer names
                "height": "35px",  # Taller for better text fit
                "shape": "round-rectangle",
                "opacity": 0.7,
                "text-opacity": 0.8,
                "text-wrap": "wrap",  # Wrap long text
                "text-max-width": "130px",  # Max width before wrapping
                "text-overflow-wrap": "anywhere",  # Break long words
                "z-index": 10,
            },
        },
        # Join column nodes (highlighted) - still behind edges
        {
            "selector": ".join-column",
            "style": {
                "border-width": 2,
                "border-color": colors["orange"],
                "background-color": join_column_bg,
                "font-weight": "bold",
                "opacity": 0.9,
                "z-index": 2,  # Slightly higher than regular columns but still low
            },
        },
        # Join edges - absolute maximum z-index
        {
            "selector": ".join-edge",
            "style": {
                "target-arrow-shape": "triangle",
                "target-arrow-color": colors["teal"],
                "line-color": colors["teal"],
                "width": 10,  # Extra thick edges
                "opacity": 1,
                "overlay-opacity": 0,
                "overlay-padding": 0,
                "z-index": 50,  # Moderate z-index for proper layering
                "z-compound-depth": "top",  # Force edges to top compound level
                "z-index-compare": "manual",  # Manual z-index comparison
            },
        },
        # Adjacent edges (straight lines for directly connected DCs)
        {"selector": ".edge-adjacent", "style": {"curve-style": "straight", "line-style": "solid"}},
        # Distant edges (curved over top for non-adjacent DCs)
        {
            "selector": ".edge-distant",
            "style": {
                "curve-style": "unbundled-bezier",
                "control-point-distances": "-200 -200",
                "control-point-weights": "0.2 0.8",
            },
        },
        # Inner join styling
        {
            "selector": ".join-inner",
            "style": {
                "line-style": "solid",
                "width": 8,  # Extra thick for visibility
                "line-color": colors["teal"],
                "target-arrow-shape": "triangle",
                "target-arrow-color": colors["teal"],
                "target-arrow-size": 15,
            },
        },
        # Inner join - adjacent (straight)
        {"selector": ".join-inner.edge-adjacent", "style": {"curve-style": "straight"}},
        # Inner join - distant (curved)
        {
            "selector": ".join-inner.edge-distant",
            "style": {
                "curve-style": "unbundled-bezier",
                "control-point-distances": "-250 -250",
                "control-point-weights": "0.15 0.85",
            },
        },
        # Left join styling
        {
            "selector": ".join-left",
            "style": {
                "line-style": "dashed",
                "width": 7,
                "line-color": colors["teal"],
                "target-arrow-shape": "square",
                "target-arrow-color": colors["teal"],
                "target-arrow-size": 12,
            },
        },
        # Left join - distant (curved)
        {
            "selector": ".join-left.edge-distant",
            "style": {
                "curve-style": "unbundled-bezier",
                "control-point-distances": "-220 -220",
                "control-point-weights": "0.18 0.82",
            },
        },
        # Right join styling
        {
            "selector": ".join-right",
            "style": {
                "line-style": "dotted",
                "width": 7,
                "line-color": colors["teal"],
                "target-arrow-shape": "diamond",
                "target-arrow-color": colors["teal"],
                "target-arrow-size": 12,
            },
        },
        # Right join - distant (curved)
        {
            "selector": ".join-right.edge-distant",
            "style": {
                "curve-style": "unbundled-bezier",
                "control-point-distances": "-190 -190",
                "control-point-weights": "0.22 0.78",
            },
        },
        # Outer join styling
        {
            "selector": ".join-outer",
            "style": {
                "line-style": "solid",
                "width": 6,
                "line-color": colors["teal"],
                "line-cap": "round",
                "target-arrow-shape": "circle",
                "target-arrow-color": colors["teal"],
                "target-arrow-size": 10,
            },
        },
        # Outer join - distant (curved)
        {
            "selector": ".join-outer.edge-distant",
            "style": {
                "curve-style": "unbundled-bezier",
                "control-point-distances": "-160 -160",
                "control-point-weights": "0.25 0.75",
            },
        },
        # Hover effects
        {
            "selector": ".column-node:hover, .data-collection-group:hover",
            "style": {"border-width": 3, "scale": 1.05},
        },
        # Selected styling
        {
            "selector": ":selected",
            "style": {"border-width": 4, "border-color": colors["pink"], "scale": 1.1},
        },
        # Edge hover
        {"selector": ".join-edge:hover", "style": {"width": 5, "opacity": 1}},
    ]


def generate_sample_elements():
    """
    Generate sample elements using the better layout from the original prototype.

    Returns:
        List of cytoscape elements
    """
    # Sample data collections with various column name lengths
    sample_data_collections = [
        {
            "id": "dc1",
            "name": "Users",
            "tag": "users_table",
            "columns": [
                "user_id",
                "full_name",
                "email_address",
                "department_id",
                "created_timestamp",
            ],
            "joins": [
                {"on_columns": ["department_id"], "how": "left", "with_dc": ["departments_table"]}
            ],
        },
        {
            "id": "dc2",
            "name": "Departments",
            "tag": "departments_table",
            "columns": [
                "dept_id",
                "department_name",
                "manager_user_id",
                "annual_budget",
                "location",
                "floor_number",
                "phone_extension",
                "cost_center_code",
                "head_count",
                "established_date",
            ],
            "joins": [{"on_columns": ["dept_id"], "how": "left", "with_dc": ["users_table"]}],
        },
        {
            "id": "dc3",
            "name": "Projects",
            "tag": "projects_table",
            "columns": [
                "project_id",
                "project_title",
                "project_manager_id",
                "current_status",
                "start_date",
            ],
            "joins": [
                {"on_columns": ["project_manager_id"], "how": "inner", "with_dc": ["users_table"]}
            ],
        },
    ]

    # Use the original prototype's better layout logic
    elements = []

    # Track column positions for layout
    dc_positions = {}

    # Create data collection groups and column nodes
    for i, dc in enumerate(sample_data_collections):
        dc_id = dc["id"]
        dc_name = dc["name"]
        dc_tag = dc["tag"]
        columns = dc["columns"]

        # Calculate positions for this data collection
        x_offset = i * 350  # More space between data collections horizontally
        dc_positions[dc_tag] = {"x": x_offset, "columns": {}}

        # Calculate dynamic background box size based on number of columns
        num_columns = len(columns)
        box_height = max(
            320, num_columns * 45 + 100
        )  # Min 320px, or 45px per column + more padding

        # Center the background box on the column range
        first_column_y = 140
        last_column_y = 140 + ((num_columns - 1) * 50)
        center_y = (first_column_y + last_column_y) / 2

        # Create background data collection box (no parent-child relationship)
        elements.append(
            {
                "data": {
                    "id": f"dc_bg_{dc_id}",
                    "label": f"{dc_name}\n({dc_tag})",
                    "type": "dc_background",
                    "column_count": num_columns,
                    "box_height": box_height,
                },
                "position": {"x": x_offset + 100, "y": center_y},  # Centered on column range
                "classes": f"data-collection-background dc-columns-{min(num_columns, 10)}",  # Max 10 for styling
            }
        )

        # Create column nodes as independent elements (no parent)
        for j, column in enumerate(columns):
            column_id = f"{dc_tag}_{column}"
            y_offset = 140 + (j * 50)  # Start lower and tighter spacing

            dc_positions[dc_tag]["columns"][column] = {
                "x": x_offset + 100,
                "y": y_offset,
                "node_id": column_id,
            }

            # Check if this column is part of a join
            is_join_column = False
            if "joins" in dc:
                for join in dc["joins"]:
                    if column in join.get("on_columns", []):
                        is_join_column = True
                        break

            elements.append(
                {
                    "data": {
                        "id": column_id,
                        "label": column,
                        "type": "column",
                        "dc_tag": dc_tag,
                        "dc_name": dc_name,
                        "is_join_column": is_join_column,
                    },
                    "position": {"x": x_offset + 100, "y": y_offset},
                    "classes": "column-node join-column" if is_join_column else "column-node",
                }
            )

    # Create edges for joins
    edge_counter = 0
    for dc in sample_data_collections:
        dc_tag = dc["tag"]

        if "joins" in dc:
            for join in dc["joins"]:
                on_columns = join["on_columns"]
                join_type = join["how"]
                target_dc_tags = join["with_dc"]

                for target_dc_tag in target_dc_tags:
                    # Find the target data collection
                    target_dc = next(
                        (d for d in sample_data_collections if d["tag"] == target_dc_tag), None
                    )
                    if not target_dc:
                        continue

                    # Create edges between matching columns
                    for col in on_columns:
                        source_node = f"{dc_tag}_{col}"

                        # Find matching column in target DC (might have different name)
                        target_col = None
                        if target_dc_tag == "departments_table" and col == "department_id":
                            target_col = "dept_id"
                        elif target_dc_tag == "users_table" and col == "dept_id":
                            target_col = "department_id"
                        elif target_dc_tag == "users_table" and col == "project_manager_id":
                            target_col = "user_id"  # Project manager is a user
                        elif target_dc_tag == "users_table" and col == "manager_user_id":
                            target_col = "user_id"  # Department manager is a user
                        else:
                            target_col = col  # Default: same name

                        target_node = f"{target_dc_tag}_{target_col}"

                        # Check if target column exists
                        target_dc_obj = next(
                            (d for d in sample_data_collections if d["tag"] == target_dc_tag), None
                        )
                        if target_dc_obj and target_col in target_dc_obj["columns"]:
                            # Determine if DCs are adjacent (next to each other in layout)
                            source_dc_index = next(
                                i
                                for i, d in enumerate(sample_data_collections)
                                if d["tag"] == dc_tag
                            )
                            target_dc_index = next(
                                i
                                for i, d in enumerate(sample_data_collections)
                                if d["tag"] == target_dc_tag
                            )

                            # Adjacent if they are next to each other (difference of 1)
                            is_adjacent = abs(source_dc_index - target_dc_index) == 1
                            adjacency_class = "edge-adjacent" if is_adjacent else "edge-distant"

                            elements.append(
                                {
                                    "data": {
                                        "id": f"edge_{edge_counter}",
                                        "source": source_node,
                                        "target": target_node,
                                        "label": f"{join_type}",
                                        "join_type": join_type,
                                        "is_adjacent": is_adjacent,
                                    },
                                    "classes": f"join-edge join-{join_type} {adjacency_class}",
                                }
                            )
                            edge_counter += 1

    return elements


def create_selection_details_content(selected_data):
    """
    Create content for the selection details panel.

    Args:
        selected_data: Selected node or edge data

    Returns:
        Dash component showing selection details
    """
    if not selected_data:
        return dmc.Text("Click on a node or edge to see details", c="gray", size="sm")

    data = selected_data[0]  # First selected item
    element_type = data.get("type", "unknown")

    if element_type == "column":
        is_join = data.get("is_join_column", False)
        return dmc.Stack(
            [
                dmc.Group(
                    [
                        DashIconify(
                            icon="mdi:table-column",
                            width=18,
                            color=colors["orange"] if is_join else colors["blue"],
                        ),
                        dmc.Text(f"Column: {data['label']}", fw="bold", size="sm"),
                    ]
                ),
                dmc.Group(
                    [
                        dmc.Badge(
                            "Join Column" if is_join else "Regular Column",
                            color="orange" if is_join else "blue",
                            size="xs",
                        ),
                        dmc.Badge(
                            data.get("dc_tag", data.get("dc_name", "Unknown DC")),
                            color="gray",
                            size="xs",
                        ),
                    ]
                ),
            ],
            gap="xs",
        )

    elif element_type == "data_collection":
        return dmc.Stack(
            [
                dmc.Group(
                    [
                        DashIconify(icon="mdi:database", width=18, color=colors["teal"]),
                        dmc.Text(f"Data Collection: {data['label']}", fw="bold", size="sm"),
                    ]
                ),
                dmc.Text(f"ID: {data['id']}", size="xs", c="gray", ff="monospace"),
            ],
            gap="xs",
        )

    elif "join_type" in data:  # Edge
        return dmc.Stack(
            [
                dmc.Group(
                    [
                        DashIconify(icon="mdi:arrow-right-bold", width=18, color=colors["orange"]),
                        dmc.Text(f"Join: {data.get('label', 'Unknown')}", fw="bold", size="sm"),
                    ]
                ),
                dmc.Text(f"From: {data.get('source', 'Unknown')}", size="xs", c="gray"),
                dmc.Text(f"To: {data.get('target', 'Unknown')}", size="xs", c="gray"),
            ],
            gap="xs",
        )

    return dmc.Text("Unknown element type", c="gray", size="sm")


# Callback functions that can be registered in the main app
def register_joins_callbacks(app):
    """
    Register all callbacks for the joins visualization.

    Args:
        app: Dash application instance
    """
    from dash import Input, Output, callback

    @callback(
        Output("depictio-joins-selection-info", "children", allow_duplicate=True),
        [
            Input("depictio-cytoscape-joins", "selectedNodeData"),
            Input("depictio-cytoscape-joins", "selectedEdgeData"),
        ],
        prevent_initial_call=True,
    )
    def update_selection_info(selected_nodes, selected_edges):
        """Update selection info panel based on selected elements."""
        selected_data = selected_nodes or selected_edges
        return create_selection_details_content(selected_data)

    # @callback(
    #     Output("depictio-cytoscape-joins", "layout"),
    #     [Input("joins-reset-layout-btn", "n_clicks")],
    #     prevent_initial_call=True,
    # )
    # def reset_layout(n_clicks):
    #     """Reset the layout to preset positions."""
    #     if n_clicks:
    #         return {
    #             "name": "preset",
    #             "animate": True,
    #             "animationDuration": 500,
    #             "fit": True,  # Enable auto-fit for better visibility
    #             "padding": 50,  # Increased padding for better interaction
    #         }
    #     return no_update


# Example usage for testing
if __name__ == "__main__":
    # This creates a simple test to verify the components work
    import dash
    from dash import html

    app = dash.Dash(__name__)

    # Create test layout
    app.layout = dmc.MantineProvider(
        [
            dmc.Container(
                [
                    dmc.Title("Depictio Cytoscape Joins Test", order=1, mb="lg"),
                    create_joins_visualization_section(
                        elements=generate_sample_elements(), theme="light"
                    ),
                ],
                size="xl",
                p="md",
            )
        ]
    )

    # Register callbacks
    register_joins_callbacks(app)

    print("🧪 Testing Depictio Cytoscape Joins Component")
    print("Visit: http://localhost:8054")
    app.run(debug=True, port=8054)
