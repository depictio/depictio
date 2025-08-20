"""
Project Data Collections Management Module

This module provides a Dash layout and callbacks for managing data collections
within a project. It allows administrators and project owners to add, modify,
and remove data collections, as well as upload new datasets.

The module is organized into:
- API utility functions for data fetching and manipulation
- UI component definitions
- Layout definition
- Modular callback functions for handling user interactions
"""

import base64

import dash_ag_grid as dag
import dash_mantine_components as dmc
import polars as pl
from bson import ObjectId
from dash_iconify import DashIconify

import dash
from dash import Input, Output, ctx, dcc, html
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.api_calls import api_call_fetch_delta_table_info, api_call_fetch_project_by_id
from depictio.dash.colors import colors
from depictio.dash.components.depictio_cytoscape_joins import (
    create_joins_visualization_section,
    generate_sample_elements,
    register_joins_callbacks,
)
from depictio.dash.layouts.layouts_toolbox import (
    create_data_collection_delete_modal,
    create_data_collection_edit_name_modal,
    create_data_collection_modal,
    create_data_collection_overwrite_modal,
)
from depictio.models.models.projects import Project


def calculate_total_storage_size(data_collections):
    """
    Calculate the total storage size across all data collections.

    Args:
        data_collections: List of data collection objects

    Returns:
        int: Total size in bytes across all data collections
    """
    total_bytes = 0

    if not data_collections:
        return total_bytes

    for dc in data_collections:
        # Handle dict or object access
        if isinstance(dc, dict):
            flexible_metadata = dc.get("flexible_metadata", {})
        else:
            flexible_metadata = getattr(dc, "flexible_metadata", {})

        if isinstance(flexible_metadata, dict):
            deltatable_size_bytes = flexible_metadata.get("deltatable_size_bytes", 0)
        else:
            deltatable_size_bytes = (
                getattr(flexible_metadata, "deltatable_size_bytes", 0) if flexible_metadata else 0
            )

        if deltatable_size_bytes and isinstance(deltatable_size_bytes, (int, float)):
            total_bytes += int(deltatable_size_bytes)

    return total_bytes


def format_storage_size(size_bytes):
    """
    Format storage size in bytes to human-readable format.

    Args:
        size_bytes (int): Size in bytes

    Returns:
        tuple: (formatted_size_str, unit_str) for display
    """
    if size_bytes == 0:
        return "0", "bytes"
    elif size_bytes < 1024:
        return f"{size_bytes}", "bytes"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f}", "KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / (1024**2):.1f}", "MB"
    elif size_bytes < 1024**4:
        return f"{size_bytes / (1024**3):.1f}", "GB"
    else:
        return f"{size_bytes / (1024**4):.1f}", "TB"


def get_data_collection_size_display(data_collection):
    """
    Get formatted size display string for a data collection.

    Args:
        data_collection: Data collection object or dict

    Returns:
        str: Formatted size string for display
    """
    try:
        # Extract flexible_metadata
        if isinstance(data_collection, dict):
            flexible_metadata = data_collection.get("flexible_metadata", {})
        else:
            flexible_metadata = getattr(data_collection, "flexible_metadata", {})

        # Extract size_bytes
        if isinstance(flexible_metadata, dict):
            size_bytes = flexible_metadata.get("deltatable_size_bytes", 0)
        else:
            size_bytes = (
                getattr(flexible_metadata, "deltatable_size_bytes", 0) if flexible_metadata else 0
            )

        # Format and return
        if size_bytes and isinstance(size_bytes, (int, float)):
            formatted_size, unit = format_storage_size(size_bytes)
            return f"{formatted_size} {unit}"
        else:
            return "N/A"
    except Exception:
        return "N/A"


def create_project_type_indicator(project_type):
    """
    Create a project type indicator badge.

    Args:
        project_type: "basic" or "advanced"

    Returns:
        dmc.Group: Project type indicator component
    """
    if project_type.lower() == "basic":
        color = "teal"
        description = "Simple project with direct data collection management"
    else:  # advanced
        color = "orange"
        description = "Advanced project with workflow-based data collections"

    return dmc.Group(
        [
            dmc.Group(
                [
                    DashIconify(icon="mdi:jira", width=20, color=color),
                    dmc.Text("Project Type:", size="sm", fw="bold", c="gray"),
                    dmc.Badge(project_type.title(), color=color, variant="light"),
                ],
                gap="xs",
                align="center",
            ),
            dmc.Text(description, size="xs", c="gray", style={"fontStyle": "italic"}),
        ],
        justify="space-between",
        align="center",
        style={
            "padding": "0.5rem 1rem",
            "backgroundColor": "var(--app-surface-color, #f8f9fa)",
            "borderRadius": "0.5rem",
            "border": "1px solid var(--app-border-color, #dee2e6)",
        },
    )


def create_workflow_card(workflow, selected_workflow_id=None):
    """
    Create a clickable workflow card displaying workflow information.

    Args:
        workflow: Workflow object
        selected_workflow_id: ID of currently selected workflow

    Returns:
        html.Div: Clickable workflow card component
    """
    is_selected = str(workflow.id) == selected_workflow_id
    card_style = {
        "cursor": "pointer",
        "transition": "all 0.2s ease",
        "border": f"2px solid {colors['teal']}"
        if is_selected
        else "1px solid var(--app-border-color, #ddd)",
        "backgroundColor": f"rgba({colors['teal']}, 0.05)"
        if is_selected
        else "var(--app-surface-color, #ffffff)",
    }

    # Get engine icon
    engine_icons = {
        "snakemake": "vscode-icons:file-type-snakemake",
        "nextflow": "vscode-icons:file-type-nextflow",
        "python": "vscode-icons:file-type-python",
        "r": "vscode-icons:file-type-r",
        "bash": "vscode-icons:file-type-bash",
        "galaxy": "vscode-icons:file-type-galaxy",
        "cwl": "vscode-icons:file-type-cwl",
        "rust": "vscode-icons:file-type-rust",
    }
    engine_icon = engine_icons.get(workflow.engine.name.lower(), "hugeicons:workflow-square-01")

    return html.Div(
        [
            dmc.Paper(
                [
                    dmc.Group(
                        [
                            DashIconify(icon=engine_icon, width=24),
                            dmc.Stack(
                                [
                                    dmc.Text(workflow.name, fw="bold", size="sm"),
                                    dmc.Group(
                                        [
                                            dmc.Badge(
                                                workflow.engine.name, color="blue", size="xs"
                                            ),
                                            dmc.Badge(
                                                f"{len(workflow.data_collections)} DCs",
                                                color="green",
                                                size="xs",
                                            ),
                                        ],
                                        gap="xs",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        gap="sm",
                        justify="flex-start",
                    ),
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    dmc.Text("Repository:", size="xs", fw="bold", c="gray"),
                                    dmc.Anchor(
                                        workflow.repository_url.split("/")[-1]
                                        if workflow.repository_url
                                        else "N/A",
                                        href=workflow.repository_url,
                                        target="_blank",
                                        size="xs",
                                        c="blue",
                                    )
                                    if workflow.repository_url
                                    else dmc.Text("N/A", size="xs", c="gray"),
                                ],
                                gap="xs",
                            ),
                            dmc.Group(
                                [
                                    dmc.Text("Catalog:", size="xs", fw="bold", c="gray"),
                                    dmc.Text(
                                        workflow.catalog.name if workflow.catalog else "N/A",
                                        size="xs",
                                        c="gray",
                                    ),
                                ],
                                gap="xs",
                            ),
                            dmc.Group(
                                [
                                    dmc.Text("Version:", size="xs", fw="bold", c="gray"),
                                    dmc.Text(
                                        workflow.version if workflow.version else "N/A",
                                        size="xs",
                                        c="gray",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        gap="xs",
                        mt="sm",
                    ),
                ],
                withBorder=True,
                shadow="sm" if not is_selected else "md",
                radius="md",
                p="md",
                style=card_style,
            )
        ],
        id={"type": "workflow-card", "index": str(workflow.id)},
        n_clicks=0,
        style={"cursor": "pointer"},
    )


def create_workflows_manager_section(workflows, selected_workflow_id=None):
    """
    Create the workflows manager section.

    Args:
        workflows: List of workflow objects
        selected_workflow_id: ID of currently selected workflow

    Returns:
        dmc.Stack: Workflows manager section
    """
    if not workflows:
        return dmc.Card(
            [
                dmc.Center(
                    [
                        dmc.Stack(
                            [
                                DashIconify(
                                    icon="mdi:workflow",
                                    width=48,
                                    color="gray",
                                    style={"opacity": 0.5},
                                ),
                                dmc.Text(
                                    "No workflows available",
                                    size="lg",
                                    c="gray",
                                    ta="center",
                                ),
                                dmc.Text(
                                    "This project doesn't have any workflows configured",
                                    size="sm",
                                    c="gray",
                                    ta="center",
                                ),
                            ],
                            align="center",
                            gap="sm",
                        )
                    ],
                    p="xl",
                ),
            ],
            withBorder=True,
            shadow="sm",
            radius="md",
            p="lg",
        )

    workflow_cards = [create_workflow_card(wf, selected_workflow_id) for wf in workflows]

    return dmc.Stack(
        [
            dmc.Group(
                [
                    DashIconify(icon="mdi:workflow", width=24, color=colors["blue"]),
                    dmc.Text("Workflows Manager", fw="bold", size="lg"),
                    dmc.Badge(
                        f"{len(workflows)} {'workflow' if len(workflows) == 1 else 'workflows'}",
                        color="blue",
                        variant="light",
                    ),
                ],
                gap="sm",
            ),
            dmc.Text(
                "Select a workflow to view its data collections",
                size="sm",
                c="gray",
            ),
            dmc.SimpleGrid(
                cols=3,
                children=workflow_cards,
                spacing="lg",
            ),
        ],
        gap="xl",
    )


def create_unified_data_collections_manager_section(
    data_collections, project_type="basic", workflow_name=None
):
    """
    Create a unified data collections manager section for both Basic and Advanced projects.

    Args:
        data_collections: List of data collection objects
        project_type: "basic" or "advanced"
        workflow_name: Name of selected workflow (for advanced projects only)

    Returns:
        dmc.Stack: Unified data collections manager section
    """
    # Overview cards
    overview_cards = dmc.SimpleGrid(
        cols=3,
        children=[
            # Total Collections card
            dmc.Card(
                [
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    DashIconify(
                                        icon="mdi:database-outline",
                                        width=20,
                                        color=colors["blue"],
                                    ),
                                    dmc.Text("Total Collections", fw="bold", size="sm"),
                                ],
                                justify="center",
                                align="center",
                                gap="xs",
                            ),
                            dmc.Center(
                                dmc.Text(
                                    str(len(data_collections)) if data_collections else "0",
                                    size="xl",
                                    fw="bold",
                                    c=colors["blue"],
                                )
                            ),
                            dmc.Center(dmc.Text("Data Collections", size="xs", c="gray")),
                        ],
                        gap="sm",
                        align="center",
                    )
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                p="lg",
            ),
            # Metatypes card
            dmc.Card(
                [
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    DashIconify(
                                        icon="mdi:tag-multiple",
                                        width=20,
                                        color=colors["green"],
                                    ),
                                    dmc.Text("Collection Types", fw="bold", size="sm"),
                                ],
                                justify="center",
                                align="center",
                                gap="xs",
                            ),
                            dmc.Group(
                                [
                                    dmc.Stack(
                                        [
                                            dmc.Text(
                                                str(
                                                    sum(
                                                        1
                                                        for dc in data_collections
                                                        if dc.config.metatype
                                                        and dc.config.metatype.lower()
                                                        == "aggregate"
                                                    )
                                                )
                                                if data_collections
                                                else "0",
                                                size="lg",
                                                fw="bold",
                                                c=colors["green"],
                                                ta="center",
                                            ),
                                            dmc.Text("Aggregate", size="xs", c="gray", ta="center"),
                                        ],
                                        gap="xs",
                                        align="center",
                                    ),
                                    dmc.Divider(
                                        orientation="vertical",
                                        style={"height": "50px", "alignSelf": "center"},
                                    ),
                                    dmc.Stack(
                                        [
                                            dmc.Text(
                                                str(
                                                    sum(
                                                        1
                                                        for dc in data_collections
                                                        if dc.config.metatype
                                                        and dc.config.metatype.lower() == "metadata"
                                                    )
                                                )
                                                if data_collections
                                                else "0",
                                                size="lg",
                                                fw="bold",
                                                c=colors["green"],
                                                ta="center",
                                            ),
                                            dmc.Text("Metadata", size="xs", c="gray", ta="center"),
                                        ],
                                        gap="xs",
                                        align="center",
                                    ),
                                ],
                                justify="space-around",
                                align="center",
                                style={"flex": 1},  # Take up remaining space in the card
                            ),
                        ],
                        gap="md",  # Add space between title and content
                        justify="center",
                    )
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                p="lg",
            ),
            # Total Size card - re-enabled with storage calculation
            dmc.Card(
                [
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    DashIconify(
                                        icon="mdi:harddisk",
                                        width=20,
                                        color=colors["orange"],
                                    ),
                                    dmc.Text("Total Storage", fw="bold", size="sm"),
                                ],
                                justify="center",
                                align="center",
                                gap="xs",
                            ),
                            html.Div(
                                id="storage-size-display",
                                style={"textAlign": "center"},
                            ),
                        ],
                        gap="sm",
                        align="center",
                    )
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                p="lg",
            ),
        ],
    )

    # Data collections list
    if data_collections:
        dc_items = []
        for dc in data_collections:
            dc_card = html.Div(
                [
                    dmc.Card(
                        [
                            dmc.Group(
                                [
                                    # Main data collection info
                                    dmc.Group(
                                        [
                                            DashIconify(
                                                icon="mdi:table"
                                                if dc.config.type.lower() == "table"
                                                else "mdi:file-document",
                                                width=20,
                                                color=colors["teal"],
                                            ),
                                            dmc.Badge(dc.config.type, color="blue", size="xs"),
                                            dmc.Badge(
                                                dc.config.metatype or "Unknown",
                                                color="gray",
                                                size="xs",
                                            ),
                                            dmc.Text(dc.data_collection_tag, fw="bold", size="sm"),
                                        ],
                                        gap="sm",
                                        align="center",
                                        style={"flex": 1},
                                    ),
                                    # Action buttons
                                    dmc.Group(
                                        [
                                            dmc.Tooltip(
                                                dmc.ActionIcon(
                                                    DashIconify(
                                                        icon="mdi:database-refresh", width=16
                                                    ),
                                                    id={
                                                        "type": "dc-overwrite-button",
                                                        "index": dc.data_collection_tag,
                                                    },
                                                    variant="subtle",
                                                    color="orange",
                                                    size="sm",
                                                    disabled=False,  # Will be controlled by callback
                                                ),
                                                label="Overwrite data",
                                                position="top",
                                            ),
                                            dmc.Tooltip(
                                                dmc.ActionIcon(
                                                    DashIconify(icon="mdi:pencil", width=16),
                                                    id={
                                                        "type": "dc-edit-name-button",
                                                        "index": dc.data_collection_tag,
                                                    },
                                                    variant="subtle",
                                                    color="blue",
                                                    size="sm",
                                                    disabled=False,  # Will be controlled by callback
                                                ),
                                                label="Edit name",
                                                position="top",
                                            ),
                                            dmc.Tooltip(
                                                dmc.ActionIcon(
                                                    DashIconify(icon="mdi:delete", width=16),
                                                    id={
                                                        "type": "dc-delete-button",
                                                        "index": dc.data_collection_tag,
                                                    },
                                                    variant="subtle",
                                                    color="red",
                                                    size="sm",
                                                    disabled=False,  # Will be controlled by callback
                                                ),
                                                label="Delete",
                                                position="top",
                                            ),
                                        ],
                                        gap="xs",
                                        align="center",
                                    ),
                                ],
                                justify="space-between",
                                align="center",
                            ),
                        ],
                        withBorder=True,
                        shadow="xs",
                        radius="md",
                        p="sm",
                        style={
                            "cursor": "pointer",
                            "transition": "box-shadow 0.2s ease",
                        },
                    )
                ],
                id={"type": "data-collection-card", "index": dc.data_collection_tag},
                n_clicks=0,
                style={"cursor": "pointer"},
            )
            dc_items.append(dc_card)

        data_collections_list = dmc.Stack(dc_items, gap="sm")
    else:
        data_collections_list = dmc.Center(
            [
                dmc.Stack(
                    [
                        DashIconify(
                            icon="mdi:database-off-outline",
                            width=48,
                            color="gray",
                            style={"opacity": 0.5},
                        ),
                        dmc.Text(
                            "No data collections yet",
                            size="lg",
                            c="gray",
                            ta="center",
                        ),
                        dmc.Text(
                            "Upload your first data collection to get started",
                            size="sm",
                            c="gray",
                            ta="center",
                        ),
                    ],
                    align="center",
                    gap="sm",
                )
            ],
            p="xl",
        )

    # Create project type badge and description
    if project_type == "basic":
        project_badge = dmc.Badge("Basic Project", color="cyan", variant="light")
        description = "Managing data collections for this basic project"
    else:
        project_badge = dmc.Badge("Advanced Project", color="orange", variant="light")
        if workflow_name:
            description = f"Managing data collections for workflow: {workflow_name}"
        else:
            description = "Managing data collections for this advanced project"

    return dmc.Stack(
        [
            dmc.Group(
                [
                    DashIconify(icon="mdi:database", width=24, color=colors["teal"]),
                    dmc.Text("Data Collections Manager", fw="bold", size="lg"),
                    project_badge,
                ],
                gap="sm",
            ),
            dmc.Text(
                description,
                size="sm",
                c="gray",
            ),
            overview_cards,
            dmc.Card(
                [
                    dmc.Group(
                        [
                            dmc.Group(
                                [
                                    dmc.Text("Data Collections", fw="bold", size="lg"),
                                    dmc.Badge(
                                        f"{len(data_collections)} collections",
                                        color="teal",
                                        variant="light",
                                    ),
                                ],
                                gap="md",
                                align="center",
                            ),
                            dmc.Button(
                                "Create Data Collection",
                                id="create-data-collection-button",
                                leftSection=DashIconify(icon="mdi:plus", width=16),
                                variant="filled",
                                color="teal",
                                size="sm",
                                radius="md",
                                disabled=False,  # Will be controlled by callback
                            ),
                        ],
                        justify="space-between",
                        align="center",
                    ),
                    dmc.Divider(my="md"),
                    data_collections_list,
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                p="lg",
                mt="md",
            ),
            # Data Collection Viewer Section
            dmc.Card(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:eye", width=24, color=colors["blue"]),
                            dmc.Text("Data Collection Viewer", fw="bold", size="lg"),
                            dmc.Badge("Select a Data Collection", color="gray", variant="light"),
                        ],
                        gap="md",
                        align="center",
                    ),
                    dmc.Divider(my="md"),
                    html.Div(id="data-collection-viewer-content"),
                ],
                withBorder=True,
                shadow="sm",
                radius="md",
                p="lg",
                mt="xl",
            ),
            # Hidden modals for data collection actions
            html.Div(id="dc-action-modals-container", children=[]),
        ],
        gap="xl",
    )


def create_basic_project_data_collections_section(data_collections):
    """
    Legacy wrapper for basic projects - redirects to unified function.

    Args:
        data_collections: List of data collection objects

    Returns:
        dmc.Stack: Data collections section for basic projects
    """
    return create_unified_data_collections_manager_section(
        data_collections=data_collections, project_type="basic"
    )


def create_data_collections_manager_section(workflow=None):
    """
    Create the data collections manager section based on selected workflow.

    Args:
        workflow: Selected workflow object (None if no workflow selected)

    Returns:
        dmc.Stack: Data collections manager section
    """
    if not workflow:
        return dmc.Card(
            [
                dmc.Center(
                    [
                        dmc.Stack(
                            [
                                DashIconify(
                                    icon="mdi:database-outline",
                                    width=48,
                                    color="gray",
                                    style={"opacity": 0.5},
                                ),
                                dmc.Text(
                                    "Select a workflow to continue",
                                    size="lg",
                                    c="gray",
                                    ta="center",
                                ),
                                dmc.Text(
                                    "Choose a workflow from above to view its data collections",
                                    size="sm",
                                    c="gray",
                                    ta="center",
                                ),
                            ],
                            align="center",
                            gap="sm",
                        )
                    ],
                    p="xl",
                ),
            ],
            withBorder=True,
            shadow="sm",
            radius="md",
            p="lg",
        )

    # Use the unified function for advanced projects with selected workflow
    data_collections = workflow.data_collections if workflow else []
    workflow_name = getattr(workflow, "name", "Unknown Workflow")

    return create_unified_data_collections_manager_section(
        data_collections=data_collections, project_type="advanced", workflow_name=workflow_name
    )


def create_data_collection_viewer_content(
    data_collection=None, delta_info=None, workflow_info=None
):
    """
    Create the content for the data collection viewer section.

    Args:
        data_collection: Selected data collection object or data
        delta_info: Delta table information from API
        workflow_info: Workflow information containing registration_time

    Returns:
        html.Div: Data collection viewer content
    """
    if not data_collection:
        return dmc.Center(
            [
                dmc.Stack(
                    [
                        DashIconify(
                            icon="mdi:table-eye",
                            width=48,
                            color="gray",
                            style={"opacity": 0.5},
                        ),
                        dmc.Text(
                            "No data collection selected",
                            size="lg",
                            c="gray",
                            ta="center",
                        ),
                        dmc.Text(
                            "Select a data collection above to preview its contents",
                            size="sm",
                            c="gray",
                            ta="center",
                        ),
                    ],
                    align="center",
                    gap="sm",
                )
            ],
            p="xl",
        )

    # Extract data collection info (could be from dict or object)
    dc_tag = (
        data_collection.get("data_collection_tag")
        if isinstance(data_collection, dict)
        else getattr(data_collection, "data_collection_tag", "Unknown")
    )
    dc_type = (
        data_collection.get("config", {}).get("type")
        if isinstance(data_collection, dict)
        else getattr(data_collection.config, "type", "unknown")
    )
    dc_metatype = (
        data_collection.get("config", {}).get("metatype")
        if isinstance(data_collection, dict)
        else getattr(data_collection.config, "metatype", "Unknown")
    )

    return dmc.Stack(
        [
            # Data collection header info
            dmc.Group(
                [
                    DashIconify(
                        icon="mdi:table" if dc_type.lower() == "table" else "mdi:file-document",
                        width=32,
                        color=colors["teal"],
                    ),
                    dmc.Stack(
                        [
                            dmc.Text(dc_tag, fw="bold", size="xl"),
                            # dmc.Group(
                            #     [
                            #         dmc.Badge(dc_type, color="blue", size="sm"),
                            #         dmc.Badge(dc_metatype, color="gray", size="sm"),
                            #     ],
                            #     gap="sm",
                            # ),
                        ],
                        # gap="xs",
                    ),
                ],
                gap="md",
                align="center",
            ),
            # Detailed data collection information
            dmc.Divider(my="md"),
            dmc.SimpleGrid(
                cols=2,
                spacing="lg",
                children=[
                    # Configuration Details
                    dmc.Card(
                        [
                            dmc.Group(
                                [
                                    DashIconify(icon="mdi:cog", width=20, color=colors["blue"]),
                                    dmc.Text("Configuration", fw="bold", size="md"),
                                ],
                                gap="xs",
                                align="center",
                            ),
                            dmc.Divider(my="sm"),
                            dmc.Stack(
                                [
                                    dmc.Group(
                                        [
                                            dmc.Text(
                                                "Data Collection ID:",
                                                size="sm",
                                                fw="bold",
                                                c="gray",
                                            ),
                                            dmc.Text(
                                                data_collection.get("id")
                                                if isinstance(data_collection, dict)
                                                else str(getattr(data_collection, "id", "N/A")),
                                                size="sm",
                                                ff="monospace",
                                            ),
                                        ],
                                        justify="space-between",
                                    ),
                                    dmc.Group(
                                        [
                                            dmc.Text("Type:", size="sm", fw="bold", c="gray"),
                                            dmc.Badge(dc_type, color="blue", size="xs"),
                                        ],
                                        justify="space-between",
                                    ),
                                    dmc.Group(
                                        [
                                            dmc.Text("Metatype:", size="sm", fw="bold", c="gray"),
                                            dmc.Badge(
                                                dc_metatype or "Unknown", color="gray", size="xs"
                                            ),
                                        ],
                                        justify="space-between",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        withBorder=True,
                        shadow="xs",
                        radius="md",
                        p="md",
                    ),
                    # Delta Table Information
                    dmc.Card(
                        [
                            dmc.Group(
                                [
                                    DashIconify(icon="mdi:delta", width=20, color=colors["green"]),
                                    dmc.Text("Delta Table Details", fw="bold", size="md"),
                                ],
                                gap="xs",
                                align="center",
                            ),
                            dmc.Divider(my="sm"),
                            dmc.Stack(
                                [
                                    dmc.Group(
                                        [
                                            dmc.Text(
                                                "Delta Location:", size="sm", fw="bold", c="gray"
                                            ),
                                            dmc.Text(
                                                delta_info.get("delta_table_location", "N/A")
                                                if delta_info
                                                else "N/A",
                                                size="sm",
                                                ff="monospace",
                                            ),
                                        ],
                                        justify="space-between",
                                    ),
                                    dmc.Group(
                                        [
                                            dmc.Text(
                                                "Last Aggregated:", size="sm", fw="bold", c="gray"
                                            ),
                                            dmc.Text(
                                                # Get the most recent aggregation time from delta_info
                                                (
                                                    delta_info.get("aggregation", [{}])[-1].get(
                                                        "aggregation_time", "Never"
                                                    )
                                                    if delta_info and delta_info.get("aggregation")
                                                    else "Never"
                                                ),
                                                size="sm",
                                            ),
                                        ],
                                        justify="space-between",
                                    ),
                                    dmc.Group(
                                        [
                                            dmc.Text("Format:", size="sm", fw="bold", c="gray"),
                                            dmc.Badge(
                                                # Access format through proper config structure
                                                (
                                                    data_collection.get("config", {})
                                                    .get("dc_specific_properties", {})
                                                    .get("format")
                                                    if isinstance(data_collection, dict)
                                                    else getattr(
                                                        getattr(
                                                            data_collection.config,
                                                            "dc_specific_properties",
                                                            None,
                                                        ),
                                                        "format",
                                                        "Unknown",
                                                    )
                                                    if hasattr(data_collection, "config")
                                                    else "Unknown"
                                                )
                                                or "Unknown",
                                                color="blue",
                                                size="xs",
                                            ),
                                        ],
                                        justify="space-between",
                                    ),
                                    # Add size information from flexible_metadata
                                    dmc.Group(
                                        [
                                            dmc.Text("Size:", size="sm", fw="bold", c="gray"),
                                            dmc.Text(
                                                get_data_collection_size_display(data_collection),
                                                size="sm",
                                                ff="monospace",
                                            ),
                                        ],
                                        justify="space-between",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        withBorder=True,
                        shadow="xs",
                        radius="md",
                        p="md",
                    ),
                ],
            ),
            # Description and Additional Info
            dmc.Card(
                [
                    dmc.Group(
                        [
                            DashIconify(
                                icon="mdi:information-outline", width=20, color=colors["orange"]
                            ),
                            dmc.Text("Additional Information", fw="bold", size="md"),
                        ],
                        gap="xs",
                        align="center",
                    ),
                    dmc.Divider(my="sm"),
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    dmc.Text("Description:", size="sm", fw="bold", c="gray"),
                                    dmc.Text(
                                        data_collection.get("description")
                                        if isinstance(data_collection, dict)
                                        else getattr(
                                            data_collection,
                                            "description",
                                            "No description available",
                                        ),
                                        size="sm",
                                    ),
                                ],
                                justify="flex-start",
                                align="flex-start",
                            ),
                            dmc.Group(
                                [
                                    dmc.Text("Created:", size="sm", fw="bold", c="gray"),
                                    dmc.Text(
                                        workflow_info.get("registration_time", "N/A")
                                        if workflow_info
                                        else "N/A",
                                        size="sm",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        gap="sm",
                    ),
                ],
                withBorder=True,
                shadow="xs",
                radius="md",
                p="md",
                mt="md",
            ),
            # Data Visualization Section
            dmc.Card(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:table-eye", width=20, color=colors["teal"]),
                            dmc.Text("Data Preview", fw="bold", size="md"),
                        ],
                        gap="xs",
                        align="center",
                    ),
                    dmc.Divider(my="sm"),
                    dmc.Stack(
                        [
                            dmc.Group(
                                [
                                    # dmc.Text("Rows to load:", size="sm", c="gray"),
                                    dmc.NumberInput(
                                        id="dc-viewer-row-limit",
                                        value=1000,
                                        min=100,
                                        max=10000,
                                        step=100,
                                        w="120px",
                                        style={"display": "none"},
                                    ),
                                    dmc.Button(
                                        "Load Data",
                                        id="dc-viewer-load-btn",
                                        leftSection=DashIconify(icon="mdi:table-refresh"),
                                        variant="light",
                                        size="sm",
                                    ),
                                ],
                                gap="md",
                                align="center",
                            ),
                            dmc.Divider(),
                            html.Div(id="dc-viewer-data-content"),
                        ],
                        gap="md",
                    ),
                ],
                withBorder=True,
                shadow="xs",
                radius="md",
                p="md",
                mt="md",
            ),
        ],
        gap="md",
    )


def create_data_collections_landing_ui():
    """
    Create the landing UI for data collections management.

    Returns:
        html.Div: The complete landing UI layout
    """
    # Create data collection modal
    data_collection_modal, data_collection_modal_id = create_data_collection_modal()

    return html.Div(
        [
            # Store components for state management
            dcc.Store(id="project-data-store", data={}),
            dcc.Store(id="selected-workflow-store", data=None),
            dcc.Store(id="selected-data-collection-store", data=None),
            # Data collection creation modal
            data_collection_modal,
            # Header section
            dmc.Stack(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:database", width=32, color=colors["teal"]),
                            dmc.Title(
                                "Project Data Manager",
                                order=2,
                                style={"color": colors["teal"]},
                            ),
                        ],
                        gap="md",
                    ),
                    dmc.Text(
                        "Manage workflows and data collections for your project",
                        size="lg",
                        c="gray",
                    ),
                    # Project type indicator
                    html.Div(id="project-type-indicator"),
                    dmc.Divider(),
                ],
                gap="lg",
                mb="xl",
            ),
            # Workflows Manager Section
            html.Div(id="workflows-manager-section", style={"marginBottom": "3rem"}),
            # Data Collections Manager Section
            html.Div(id="data-collections-manager-section", style={"marginTop": "2rem"}),
            # Data Collection Joins Visualization Section
            html.Div(
                id="joins-visualization-section",
                children=[
                    dmc.Divider(
                        label="Data Collection Relationships", labelPosition="center", my="xl"
                    ),
                    create_joins_visualization_section(
                        elements=[],  # Will be populated by callback
                        theme="light",  # Will be updated by theme callback
                    ),
                ],
                style={"display": "none", "marginTop": "3rem"},  # Hidden by default
            ),
            # Hidden placeholder for future content
            html.Div(id="data-collections-content", style={"display": "none"}),
        ],
        style={"padding": "2rem", "maxWidth": "1400px", "margin": "0 auto"},
    )


# Main layout for the data collections management page
layout = create_data_collections_landing_ui()


def register_project_data_collections_callbacks(app):
    """
    Register callbacks for project data collections functionality.

    Args:
        app: Dash application instance
    """

    # Register the joins visualization callbacks
    register_joins_callbacks(app)

    # Data collection viewer data visualization callback
    @app.callback(
        Output("dc-viewer-data-content", "children"),
        [
            Input("dc-viewer-load-btn", "n_clicks"),
            Input("dc-viewer-row-limit", "value"),
        ],
        [
            dash.State("selected-data-collection-store", "data"),
            dash.State("project-data-store", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def load_dc_viewer_data(n_clicks, row_limit, selected_dc_data, project_data, local_data):
        """Load and display data in the data collection viewer using AG Grid."""
        if not n_clicks or not selected_dc_data:
            return dmc.Center(
                [
                    dmc.Text(
                        "Click 'Load Data' to preview the data collection contents",
                        size="sm",
                        c="gray",
                        ta="center",
                    )
                ],
                py="xl",
            )

        try:
            # selected_dc_data is the selected_dc_tag (string), not the DC ID
            # We need to find the actual DC ID from project_data using the tag
            selected_dc_tag = selected_dc_data
            selected_dc_id = None

            if not isinstance(project_data, dict):
                return dmc.Alert("Invalid project data format", color="red")

            # Find the data collection ID based on the tag
            if project_data.get("project_type") == "basic":
                # For basic projects, look in direct data collections
                data_collections = project_data.get("data_collections", [])
                for dc in data_collections:
                    if dc.get("data_collection_tag") == selected_dc_tag:
                        selected_dc_id = dc.get("id")
                        break
            else:
                # For advanced projects, look in workflows
                workflows = project_data.get("workflows", [])
                for workflow in workflows:
                    for dc in workflow.get("data_collections", []):
                        if dc.get("data_collection_tag") == selected_dc_tag:
                            selected_dc_id = dc.get("id")
                            break
                    if selected_dc_id:
                        break

            if not selected_dc_id:
                return dmc.Alert(
                    f"Could not find data collection ID for tag: {selected_dc_tag}", color="red"
                )

            # Handle project_data - could be string or dict
            if isinstance(project_data, dict):
                project_type = project_data.get("type", "basic")
            else:
                project_type = "basic"  # Default fallback
            workflow_id = None

            if project_type == "advanced" and isinstance(project_data, dict):
                # For advanced projects, get workflow from stored data
                workflows = project_data.get("workflows", [])
                if workflows:
                    # Use first workflow for now
                    workflow_id = workflows[0].get("id")

            # Get authentication token - handle both dict and other types
            if isinstance(local_data, dict):
                token = local_data.get("access_token")
            else:
                token = None

            # Load the dataframe
            df, error = load_data_collection_dataframe(
                workflow_id=workflow_id,
                data_collection_id=selected_dc_id,
                token=token,
                limit_rows=row_limit or 1000,
            )

            if error:
                return dmc.Alert(
                    f"Error loading data: {error}",
                    color="red",
                    title="Loading Error",
                )

            if df is None or df.height == 0:
                return dmc.Alert(
                    "No data found in the selected data collection.",
                    color="yellow",
                    title="No Data",
                )

            # Convert to pandas for AG Grid (more compatible)
            df_pd = df.to_pandas()

            # Handle column names with dots - rename DataFrame columns for AG Grid compatibility
            column_mapping = {}
            for col in df_pd.columns:
                if "." in col:
                    safe_col_name = col.replace(".", "_")
                    column_mapping[col] = safe_col_name
                    logger.debug(
                        f"🔍 DC Viewer: Found column with dot: '{col}', mapping to '{safe_col_name}'"
                    )
                else:
                    column_mapping[col] = col

            # Rename DataFrame columns to safe names
            df_pd = df_pd.rename(columns=column_mapping)

            # Create column definitions
            column_defs = []
            original_columns = list(column_mapping.keys())
            for original_col in original_columns:
                safe_col = column_mapping[original_col]

                col_def = {
                    "headerName": original_col,  # Keep original name for display
                    "field": safe_col,  # Use safe name for field reference
                    "filter": True,
                    "sortable": True,
                    "resizable": True,
                }

                # Set appropriate column types based on the DataFrame data
                if df_pd[safe_col].dtype in ["int64", "float64"]:
                    col_def["type"] = "numericColumn"
                elif df_pd[safe_col].dtype == "bool":
                    col_def["cellRenderer"] = "agCheckboxCellRenderer"
                    col_def["cellEditor"] = "agCheckboxCellEditor"

                column_defs.append(col_def)

            # Create AG Grid
            grid = dag.AgGrid(
                id="dc-viewer-grid",
                columnDefs=column_defs,
                rowData=df_pd.to_dict("records"),
                defaultColDef={
                    "filter": True,
                    "sortable": True,
                    "resizable": True,
                    "minWidth": 100,
                },
                dashGridOptions={
                    "pagination": True,
                    "paginationPageSize": 25,
                    "domLayout": "normal",
                    "animateRows": True,
                },
                style={"height": "400px", "width": "100%"},
                className="ag-theme-alpine",
            )

            # Create summary info
            summary = dmc.Group(
                [
                    dmc.Text(
                        f"Showing {min(row_limit or 1000, df.height):,} of {df.height:,} rows",
                        size="sm",
                        c="gray",
                    ),
                    dmc.Text(f"{df.width} columns", size="sm", c="gray"),
                ],
                gap="lg",
            )

            return dmc.Stack([summary, dmc.Divider(), grid], gap="sm")

        except Exception as e:
            logger.error(f"Error in DC viewer data callback: {e}")
            return dmc.Alert(
                f"Unexpected error: {str(e)}",
                color="red",
                title="Error",
            )

    @app.callback(
        [
            Output("project-data-store", "data"),
            Output("workflows-manager-section", "children"),
            Output("data-collections-manager-section", "children"),
            Output("project-type-indicator", "children"),
        ],
        [
            Input("url", "pathname"),
            Input("local-store", "data"),
            Input("project-data-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def load_project_data_and_workflows(pathname, local_data, project_data_store):
        """Load project data and populate workflows manager based on project type."""
        ctx_trigger = ctx.triggered_id

        # If triggered by project-data-store change (refresh), handle differently
        if ctx_trigger == "project-data-store" and project_data_store:
            # Only refresh the data collections section, keep other sections unchanged
            try:
                project_id = project_data_store.get("project_id")
                if not project_id or not local_data or not local_data.get("access_token"):
                    return dash.no_update, dash.no_update, dash.no_update, dash.no_update

                # Fetch fresh project data from API
                project_data = api_call_fetch_project_by_id(project_id, local_data["access_token"])
                if not project_data:
                    return dash.no_update, dash.no_update, dash.no_update, dash.no_update

                project = Project.model_validate(project_data)

                # Update the stored project data with fresh data
                if project.project_type == "basic":
                    all_data_collections = []
                    if project.data_collections:
                        all_data_collections.extend(project.data_collections)
                    if project.workflows:
                        for workflow in project.workflows:
                            if workflow.data_collections:
                                all_data_collections.extend(workflow.data_collections)

                    updated_project_store_data = {
                        "project_id": project_id,
                        "project_type": project.project_type,
                        "workflows": [w.model_dump() for w in project.workflows]
                        if project.workflows
                        else [],
                        "data_collections": [dc.model_dump() for dc in all_data_collections],
                        "permissions": project.permissions.dict() if project.permissions else {},
                    }
                    data_collections_section = create_basic_project_data_collections_section(
                        all_data_collections
                    )
                else:
                    updated_project_store_data = {
                        "project_id": project_id,
                        "project_type": project.project_type,
                        "workflows": [w.model_dump() for w in project.workflows]
                        if project.workflows
                        else [],
                        "data_collections": [dc.model_dump() for dc in project.data_collections]
                        if project.data_collections
                        else [],
                        "permissions": project.permissions.dict() if project.permissions else {},
                    }
                    data_collections_section = create_data_collections_manager_section()

                return (
                    updated_project_store_data,
                    dash.no_update,
                    data_collections_section,
                    dash.no_update,
                )

            except Exception as e:
                logger.error(f"Error refreshing project data: {e}")
                return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        # Original logic for URL/local-store changes
        if not pathname or not pathname.startswith("/project/") or not pathname.endswith("/data"):
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        # Extract project ID from URL
        try:
            project_id = pathname.split("/")[-2]
        except IndexError:
            logger.error(f"Could not extract project ID from pathname: {pathname}")
            return {}, html.Div("Error: Invalid project URL"), html.Div(), html.Div()

        # Get authentication token
        if not local_data or not local_data.get("access_token"):
            logger.error("No authentication token available")
            return (
                {"project_id": project_id},
                html.Div("Authentication required"),
                html.Div(),
                html.Div(),
            )

        try:
            # Fetch project data to determine project type
            project_data = api_call_fetch_project_by_id(project_id, local_data["access_token"])
            if not project_data:
                logger.error(f"Failed to fetch project data for {project_id}")
                return dash.no_update, dash.no_update, dash.no_update
            project = Project.model_validate(project_data)

            # Debug project information
            logger.debug(f"Project loaded: {project.name}, type: {project.project_type}")
            logger.debug(
                f"Project workflows count: {len(project.workflows) if project.workflows else 0}"
            )
            logger.debug(
                f"Project data_collections count: {len(project.data_collections) if project.data_collections else 0}"
            )

            # Store project data
            # For basic projects, flatten data collections from workflows into the main data_collections array
            if project.project_type == "basic":
                # Collect all data collections from workflows and direct data collections
                all_data_collections = []
                if project.data_collections:
                    all_data_collections.extend(project.data_collections)
                if project.workflows:
                    for workflow in project.workflows:
                        if workflow.data_collections:
                            all_data_collections.extend(workflow.data_collections)

                project_store_data = {
                    "project_id": project_id,
                    "project_type": project.project_type,
                    "workflows": [w.model_dump() for w in project.workflows]
                    if project.workflows
                    else [],
                    "data_collections": [dc.model_dump() for dc in all_data_collections],
                    "permissions": project.permissions.dict() if project.permissions else {},
                }
            else:
                # Advanced projects store data collections within workflows
                project_store_data = {
                    "project_id": project_id,
                    "project_type": project.project_type,
                    "workflows": [w.model_dump() for w in project.workflows]
                    if project.workflows
                    else [],
                    "data_collections": [dc.model_dump() for dc in project.data_collections]
                    if project.data_collections
                    else [],
                    "permissions": project.permissions.dict() if project.permissions else {},
                }

            # Create sections based on project type
            if project.project_type == "advanced":
                # Advanced projects: Show workflows manager with project workflows
                workflows_section = create_workflows_manager_section(project.workflows)
                data_collections_section = create_data_collections_manager_section()
            else:
                # Basic projects: Skip workflows manager, show data collections directly
                workflows_section = html.Div()  # Empty div

                # For basic projects, data collections might be stored in the workflow
                # Check both direct data collections and workflow data collections
                basic_data_collections = []
                if project.data_collections:
                    basic_data_collections.extend(project.data_collections)

                # Also check if there are data collections in workflows (common for basic projects)
                if project.workflows:
                    for workflow in project.workflows:
                        if workflow.data_collections:
                            basic_data_collections.extend(workflow.data_collections)

                logger.debug(
                    f"Basic project direct data collections count: {len(project.data_collections) if project.data_collections else 0}"
                )
                logger.debug(
                    f"Basic project workflow data collections count: {sum(len(w.data_collections) for w in project.workflows if w.data_collections) if project.workflows else 0}"
                )
                logger.debug(
                    f"Basic project total data collections count: {len(basic_data_collections)}"
                )
                logger.debug(
                    f"Basic project data collections: {[dc.data_collection_tag for dc in basic_data_collections]}"
                )

                data_collections_section = create_basic_project_data_collections_section(
                    basic_data_collections
                )

            # Create project type indicator
            project_type_indicator = create_project_type_indicator(project.project_type)

            return (
                project_store_data,
                workflows_section,
                data_collections_section,
                project_type_indicator,
            )

        except Exception as e:
            logger.error(f"Error loading project data: {e}")
            error_msg = html.Div(
                [
                    dmc.Alert(
                        f"Error loading project: {str(e)}",
                        title="Loading Error",
                        color="red",
                        icon=DashIconify(icon="mdi:alert"),
                    )
                ]
            )
            return {"project_id": project_id}, error_msg, html.Div(), html.Div()

    @app.callback(
        [
            Output("selected-workflow-store", "data"),
            Output("data-collections-manager-section", "children", allow_duplicate=True),
        ],
        [Input({"type": "workflow-card", "index": dash.ALL}, "n_clicks")],
        [dash.State("project-data-store", "data")],
        prevent_initial_call=True,
    )
    def handle_workflow_selection(workflow_clicks, project_data):
        """Handle workflow card selection for advanced projects only."""
        if not any(workflow_clicks) or not project_data:
            return dash.no_update, dash.no_update

        # Only handle workflow selection for advanced projects
        if project_data.get("project_type") != "advanced":
            return dash.no_update, dash.no_update

        # Find which workflow was clicked
        ctx_trigger = ctx.triggered_id
        if not ctx_trigger:
            return dash.no_update, dash.no_update

        selected_workflow_id = ctx_trigger["index"]

        # Find the selected workflow from the stored data
        workflows = project_data.get("workflows", [])
        selected_workflow = None
        for wf in workflows:
            if str(wf.get("id")) == selected_workflow_id:
                selected_workflow = wf
                break

        # Create data collections section for the selected workflow
        if selected_workflow:
            # Reconstruct a mock workflow object with the necessary data
            from types import SimpleNamespace

            # Create a simple workflow-like object with the data we need
            mock_workflow = SimpleNamespace()
            mock_workflow.name = selected_workflow.get("name", "Unknown Workflow")
            mock_workflow.data_collections = []

            # Extract data collections if they exist in the workflow data
            if "data_collections" in selected_workflow:
                for dc_data in selected_workflow["data_collections"]:
                    # Create mock data collection objects
                    mock_dc = SimpleNamespace()
                    mock_dc.data_collection_tag = dc_data.get("data_collection_tag", "Unknown DC")
                    mock_dc.config = SimpleNamespace()
                    mock_dc.config.type = dc_data.get("config", {}).get("type", "unknown")
                    mock_dc.config.metatype = dc_data.get("config", {}).get("metatype", "Unknown")
                    mock_workflow.data_collections.append(mock_dc)

            data_collections_section = create_data_collections_manager_section(mock_workflow)
        else:
            data_collections_section = create_data_collections_manager_section()

        return selected_workflow_id, data_collections_section

    @app.callback(
        Output("workflows-manager-section", "children", allow_duplicate=True),
        [Input("selected-workflow-store", "data")],
        [dash.State("project-data-store", "data")],
        prevent_initial_call=True,
    )
    def update_workflow_selection_visual(selected_workflow_id, project_data):
        """Update workflow cards to show selected state."""
        if not project_data or project_data.get("project_type") != "advanced":
            return dash.no_update

        # Get workflows from project data and reconstruct workflow objects
        workflows_data = project_data.get("workflows", [])
        if not workflows_data:
            return dash.no_update

        # For this visual update, we need to create mock workflow objects to pass to the function
        from types import SimpleNamespace

        workflows = []
        for wf_data in workflows_data:
            mock_wf = SimpleNamespace()
            mock_wf.id = wf_data.get("id")
            mock_wf.name = wf_data.get("name", "Unknown")
            mock_wf.engine = SimpleNamespace()
            mock_wf.engine.name = wf_data.get("engine", {}).get("name", "unknown")
            mock_wf.data_collections = wf_data.get("data_collections", [])
            mock_wf.repository_url = wf_data.get("repository_url")
            mock_wf.catalog = SimpleNamespace() if wf_data.get("catalog") else None
            if mock_wf.catalog:
                mock_wf.catalog.name = wf_data.get("catalog", {}).get("name", "Unknown")
            mock_wf.version = wf_data.get("version")
            workflows.append(mock_wf)

        # Recreate workflows manager section with updated selection
        return create_workflows_manager_section(workflows, selected_workflow_id)

    @app.callback(
        Output("data-collection-viewer-content", "children", allow_duplicate=True),
        [Input("url", "pathname")],
        prevent_initial_call=True,
    )
    def initialize_data_collection_viewer(pathname):
        """Initialize the data collection viewer with empty state."""
        if not pathname or not pathname.startswith("/project/") or not pathname.endswith("/data"):
            return dash.no_update

        return create_data_collection_viewer_content(None, None, None)

    @app.callback(
        [
            Output("selected-data-collection-store", "data"),
            Output("data-collection-viewer-content", "children", allow_duplicate=True),
        ],
        [Input({"type": "data-collection-card", "index": dash.ALL}, "n_clicks")],
        [
            dash.State("project-data-store", "data"),
            dash.State("selected-workflow-store", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_data_collection_selection(dc_clicks, project_data, selected_workflow_id, local_data):
        """Handle data collection card selection and populate viewer."""
        if not any(dc_clicks) or not project_data:
            return dash.no_update, dash.no_update

        # Find which data collection was clicked
        ctx_trigger = ctx.triggered_id
        if not ctx_trigger:
            return dash.no_update, dash.no_update

        selected_dc_tag = ctx_trigger["index"]

        # Find the selected data collection from the project data
        selected_dc = None
        dc_id = None
        workflow_info = None

        if project_data.get("project_type") == "basic":
            # For basic projects, look in direct data collections
            data_collections = project_data.get("data_collections", [])
            for dc in data_collections:
                if dc.get("data_collection_tag") == selected_dc_tag:
                    selected_dc = dc
                    dc_id = dc.get("id")
                    break
        else:
            # For advanced projects, look in the selected workflow's data collections
            if selected_workflow_id:
                workflows = project_data.get("workflows", [])
                for workflow in workflows:
                    if str(workflow.get("id")) == selected_workflow_id:
                        workflow_info = workflow  # Store workflow info for registration_time
                        for dc in workflow.get("data_collections", []):
                            if dc.get("data_collection_tag") == selected_dc_tag:
                                selected_dc = dc
                                dc_id = dc.get("id")
                                break
                        break

        # Fetch delta table information if we have the data collection ID and token
        delta_info = None
        if dc_id and local_data and local_data.get("access_token"):
            try:
                delta_info = api_call_fetch_delta_table_info(str(dc_id), local_data["access_token"])
            except Exception as e:
                logger.error(f"Error fetching delta table info: {e}")

        # Create viewer content with delta information
        viewer_content = create_data_collection_viewer_content(
            selected_dc, delta_info, workflow_info
        )

        return selected_dc_tag, viewer_content

    @app.callback(
        Output("data-collections-content", "children"),
        [
            Input("upload-data-collection-btn", "n_clicks"),
            Input("import-from-url-btn", "n_clicks"),
            Input("create-from-template-btn", "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def handle_data_collection_actions(upload_clicks, import_clicks, template_clicks):
        """Handle data collection action button clicks."""
        ctx_trigger = ctx.triggered_id

        if ctx_trigger == "upload-data-collection-btn":
            logger.info("Upload data collection button clicked")
            # TODO: Implement upload functionality
            return dmc.Alert(
                "Upload functionality coming soon!",
                title="Feature in Development",
                color="blue",
                icon=DashIconify(icon="mdi:information"),
            )
        elif ctx_trigger == "import-from-url-btn":
            logger.info("Import from URL button clicked")
            # TODO: Implement URL import functionality
            return dmc.Alert(
                "URL import functionality coming soon!",
                title="Feature in Development",
                color="blue",
                icon=DashIconify(icon="mdi:information"),
            )
        elif ctx_trigger == "create-from-template-btn":
            logger.info("Create from template button clicked")
            # TODO: Implement template creation functionality
            return dmc.Alert(
                "Template creation functionality coming soon!",
                title="Feature in Development",
                color="blue",
                icon=DashIconify(icon="mdi:information"),
            )

        return dash.no_update

    @app.callback(
        [
            Output("joins-visualization-section", "style"),
            Output("depictio-cytoscape-joins", "elements"),
        ],
        [
            Input("project-data-store", "data"),
            Input("selected-workflow-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_joins_visualization(project_data, selected_workflow_id):
        """Update joins visualization based on project data."""

        if not project_data:
            return {"display": "none"}, []

        # Get data collections based on project type
        data_collections = []

        if project_data.get("project_type") == "basic":
            # Basic projects: use flattened data collections
            data_collections = project_data.get("data_collections", [])
        else:
            # Advanced projects: use selected workflow's data collections
            if selected_workflow_id:
                workflows = project_data.get("workflows", [])
                selected_workflow = next(
                    (w for w in workflows if str(w.get("id")) == selected_workflow_id), None
                )
                if selected_workflow:
                    data_collections = selected_workflow.get("data_collections", [])

        # Check if any data collections have joins
        has_joins = False
        for dc in data_collections:
            config = dc.get("config", {})
            if config.get("join") is not None:
                has_joins = True
                break

        if has_joins and len(data_collections) > 1:
            # Generate cytoscape elements from real Depictio data (inline)
            elements = generate_cytoscape_elements_from_project_data(data_collections)
            return {"display": "block"}, elements
        elif len(data_collections) > 1:
            # Show sample visualization for demonstration (no real joins)
            elements = generate_sample_elements()
            return {"display": "block"}, elements

        # Hide if no data collections or only one DC
        return {"display": "none"}, []

    # Data collection creation modal callbacks
    @app.callback(
        [
            Output("data-collection-creation-separator-container", "style"),
            Output("data-collection-creation-custom-separator-container", "style"),
        ],
        [
            Input("data-collection-creation-format-select", "value"),
            Input("data-collection-creation-separator-select", "value"),
        ],
    )
    def update_separator_visibility(file_format, separator_value):
        """Control visibility of separator options based on file format."""
        # Show separator options only for delimited file formats
        delimited_formats = ["csv", "tsv"]
        show_separator = file_format in delimited_formats

        separator_style = {"display": "block"} if show_separator else {"display": "none"}

        # Show custom separator input if "custom" is selected and format supports it
        show_custom = show_separator and separator_value == "custom"
        custom_style = {"display": "block"} if show_custom else {"display": "none"}

        return separator_style, custom_style

    def _check_user_is_viewer(project_data, local_data):
        """Helper function to check if current user is a viewer."""
        if not project_data or not local_data:
            return True  # Treat as viewer if no data available

        try:
            # Get current user ID from local storage
            current_user_id = local_data.get("user_id")
            if not current_user_id:
                logger.debug("No user_id in local_data - treating as viewer")
                return True  # Treat as viewer if no user ID

            # Get project permissions
            permissions = project_data.get("permissions", {})
            logger.debug(f"Project data : {project_data}")
            if not permissions:
                logger.debug("No permissions in project_data - treating as viewer")
                return True  # Treat as viewer if no permissions data

            logger.debug(f"Checking permissions for user_id: {current_user_id}")
            logger.debug(f"Project permissions: {permissions}")

            # First, check if user is an owner (owners can modify data collections)
            owners = permissions.get("owners", [])
            logger.debug(f"Project owners: {owners}")
            for owner in owners:
                if isinstance(owner, dict):
                    # Project store data uses Pydantic format with 'id'
                    owner_id = owner.get("id")
                    logger.debug(
                        f"Comparing owner_id {owner_id} (type: {type(owner_id)}) with current_user_id {current_user_id} (type: {type(current_user_id)})"
                    )
                    # Handle both string and ObjectId comparisons
                    if str(owner_id) == str(current_user_id):
                        logger.debug("User is an owner - can create data collections")
                        return False  # User is an owner, not a viewer

            # Second, check if user is an editor (editors can modify data collections)
            editors = permissions.get("editors", [])
            for editor in editors:
                if isinstance(editor, dict):
                    # Project store data uses Pydantic format with 'id'
                    editor_id = editor.get("id")
                    # Handle both string and ObjectId comparisons
                    if str(editor_id) == str(current_user_id):
                        logger.debug("User is an editor - can create data collections")
                        return False  # User is an editor, not a viewer

            # Finally, check if user is explicitly a viewer or has wildcard viewer access
            viewers = permissions.get("viewers", [])
            for viewer in viewers:
                if isinstance(viewer, dict):
                    # Project store data uses Pydantic format with 'id'
                    viewer_id = viewer.get("id")
                    # Handle both string and ObjectId comparisons
                    if str(viewer_id) == str(current_user_id):
                        logger.debug("User is explicitly a viewer - cannot create data collections")
                        return True  # User is explicitly a viewer
                elif isinstance(viewer, str) and viewer == "*":
                    # Wildcard viewer access means user is a viewer
                    # (owners and editors already checked above)
                    logger.debug("User has wildcard viewer access - cannot create data collections")
                    return True

            # User has no explicit permissions - treat as viewer for safety
            logger.debug("User has no explicit permissions - treating as viewer for safety")
            logger.debug("User CANNOT create data collections")
            return True

        except Exception as e:
            logger.error(f"Error checking user permissions: {e}")
            return True  # Treat as viewer on error

    @app.callback(
        Output("create-data-collection-button", "disabled"),
        [
            Input("project-data-store", "data"),
            Input("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def control_create_button_access(project_data, local_data):
        """Control access to Create Data Collection button based on user role."""
        return _check_user_is_viewer(project_data, local_data)

    @app.callback(
        [
            Output({"type": "dc-overwrite-button", "index": dash.ALL}, "disabled"),
            Output({"type": "dc-edit-name-button", "index": dash.ALL}, "disabled"),
            Output({"type": "dc-delete-button", "index": dash.ALL}, "disabled"),
        ],
        [
            Input("project-data-store", "data"),
            Input("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def control_dc_action_buttons_access(project_data, local_data):
        """Control access to data collection action buttons based on user role."""
        is_viewer = _check_user_is_viewer(project_data, local_data)

        # Get the number of data collections to return the right number of disabled states
        try:
            if project_data and project_data.get("data_collections"):
                num_dcs = len(project_data["data_collections"])
            else:
                num_dcs = 0

            # Return disabled state for all buttons (same state for all three button types)
            disabled_states = [is_viewer] * num_dcs
            return disabled_states, disabled_states, disabled_states

        except Exception as e:
            logger.error(f"Error controlling DC action buttons: {e}")
            # Return disabled state for safety
            return [], [], []

    @app.callback(
        [
            Output("data-collection-creation-modal", "opened"),
            Output("data-collection-creation-error-alert", "style"),
        ],
        [
            Input("create-data-collection-button", "n_clicks"),
            Input("cancel-data-collection-creation-button", "n_clicks"),
        ],
        [dash.State("data-collection-creation-modal", "opened")],
        prevent_initial_call=True,
    )
    def toggle_data_collection_modal(open_clicks, cancel_clicks, opened):
        """Handle opening and closing of data collection creation modal."""
        if not ctx.triggered:
            return False, {"display": "none"}

        ctx_trigger = ctx.triggered_id

        if ctx_trigger == "create-data-collection-button" and open_clicks:
            # When opening modal, hide error alert
            return True, {"display": "none"}
        elif ctx_trigger == "cancel-data-collection-creation-button" and cancel_clicks:
            # When closing modal, hide error alert
            return False, {"display": "none"}

        return opened, {"display": "none"}

    @app.callback(
        Output("data-collection-creation-file-info", "children"),
        [Input("data-collection-creation-file-upload", "contents")],
        [
            dash.State("data-collection-creation-file-upload", "filename"),
            dash.State("data-collection-creation-file-upload", "last_modified"),
        ],
        prevent_initial_call=True,
    )
    def handle_file_upload(contents, filename, last_modified):
        """Handle file upload and display file information."""
        if not contents or not filename:
            return []

        # Decode the file content to check size
        try:
            content_type, content_string = contents.split(",")
            decoded = base64.b64decode(content_string)
            file_size = len(decoded)

            # Check file size limit (5MB)
            max_size = 5 * 1024 * 1024  # 5MB in bytes
            if file_size > max_size:
                return dmc.Alert(
                    f"File size ({file_size / (1024 * 1024):.1f}MB) exceeds the 5MB limit",
                    color="red",
                    icon=DashIconify(icon="mdi:alert"),
                )

            # Display file info
            return dmc.Card(
                [
                    dmc.Group(
                        [
                            DashIconify(icon="mdi:file-check", width=20, color="green"),
                            dmc.Stack(
                                [
                                    dmc.Text(filename, fw="bold", size="sm"),
                                    dmc.Text(
                                        f"Size: {file_size / 1024:.1f}KB",
                                        size="xs",
                                        c="gray",
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        gap="md",
                        align="center",
                    ),
                ],
                withBorder=True,
                shadow="xs",
                radius="md",
                p="sm",
                style={"backgroundColor": "var(--mantine-color-green-0)"},
            )

        except Exception as e:
            return dmc.Alert(
                f"Error processing file: {str(e)}",
                color="red",
                icon=DashIconify(icon="mdi:alert"),
            )

    @app.callback(
        Output("create-data-collection-creation-submit", "disabled"),
        [
            Input("data-collection-creation-name-input", "value"),
            Input("data-collection-creation-file-upload", "contents"),
        ],
    )
    def update_submit_button_state(name, file_contents):
        """Enable/disable submit button based on form completeness."""
        # Require name and file upload (data type has default value)
        if not name or not file_contents:
            return True
        return False

    @app.callback(
        Output("data-collection-creation-file-info", "children", allow_duplicate=True),
        [
            Input("data-collection-creation-file-upload", "contents"),
            Input("data-collection-creation-format-select", "value"),
            Input("data-collection-creation-separator-select", "value"),
            Input("data-collection-creation-custom-separator-input", "value"),
            Input("data-collection-creation-has-header-switch", "checked"),
        ],
        [
            dash.State("data-collection-creation-file-upload", "filename"),
        ],
        prevent_initial_call=True,
    )
    def validate_file_with_polars(
        contents, file_format, separator, custom_separator, has_header, filename
    ):
        """Validate uploaded file using polars and display detailed information."""
        if not contents or not filename:
            return []

        try:
            # Decode file content
            content_type, content_string = contents.split(",")
            decoded = base64.b64decode(content_string)
            file_size = len(decoded)

            # Check file size limit (5MB)
            max_size = 5 * 1024 * 1024
            if file_size > max_size:
                return dmc.Alert(
                    f"File size ({file_size / (1024 * 1024):.1f}MB) exceeds the 5MB limit",
                    color="red",
                    icon=DashIconify(icon="mdi:alert"),
                )

            # Save file temporarily for polars validation
            import os
            import tempfile

            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_format}") as tmp_file:
                tmp_file.write(decoded)
                temp_file_path = tmp_file.name

            try:
                # Build polars kwargs based on format and user selections
                polars_kwargs = {}

                if file_format in ["csv", "tsv"]:
                    # Determine separator
                    if separator == "custom" and custom_separator:
                        polars_kwargs["separator"] = custom_separator
                    elif separator == "\t":
                        polars_kwargs["separator"] = "\t"
                    elif separator in [",", ";", "|"]:
                        polars_kwargs["separator"] = separator
                    else:
                        polars_kwargs["separator"] = "," if file_format == "csv" else "\t"

                    # Header handling
                    polars_kwargs["has_header"] = has_header

                    # Try to read with polars
                    df = pl.read_csv(temp_file_path, **polars_kwargs)

                elif file_format == "parquet":
                    df = pl.read_parquet(temp_file_path)

                elif file_format == "feather":
                    df = pl.read_ipc(temp_file_path)

                elif file_format in ["xls", "xlsx"]:
                    df = pl.read_excel(temp_file_path, **polars_kwargs)

                else:
                    raise ValueError(f"Unsupported format: {file_format}")

                # File validation successful - show detailed info
                return dmc.Stack(
                    [
                        dmc.Card(
                            [
                                dmc.Group(
                                    [
                                        DashIconify(icon="mdi:file-check", width=20, color="green"),
                                        dmc.Stack(
                                            [
                                                dmc.Text(filename, fw="bold", size="sm"),
                                                dmc.Text(
                                                    f"Size: {file_size / 1024:.1f}KB • Format: {file_format.upper()}",
                                                    size="xs",
                                                    c="gray",
                                                ),
                                            ],
                                            gap="xs",
                                        ),
                                    ],
                                    gap="md",
                                    align="center",
                                ),
                            ],
                            withBorder=True,
                            shadow="xs",
                            radius="md",
                            p="sm",
                            style={"backgroundColor": "var(--mantine-color-green-0)"},
                        ),
                        dmc.Card(
                            [
                                dmc.Text("Data Preview", fw="bold", size="sm", mb="sm"),
                                dmc.SimpleGrid(
                                    cols=2,
                                    children=[
                                        dmc.Stack(
                                            [
                                                dmc.Text("Rows:", size="xs", fw="bold", c="gray"),
                                                dmc.Text(f"{df.height:,}", size="sm"),
                                            ],
                                            gap="xs",
                                        ),
                                        dmc.Stack(
                                            [
                                                dmc.Text(
                                                    "Columns:", size="xs", fw="bold", c="gray"
                                                ),
                                                dmc.Text(f"{df.width}", size="sm"),
                                            ],
                                            gap="xs",
                                        ),
                                    ],
                                    spacing="sm",
                                ),
                                dmc.Text("Column Names:", size="xs", fw="bold", c="gray", mt="sm"),
                                dmc.Text(
                                    ", ".join(df.columns[:10])
                                    + ("..." if len(df.columns) > 10 else ""),
                                    size="xs",
                                    c="gray",
                                ),
                            ],
                            withBorder=True,
                            shadow="xs",
                            radius="md",
                            p="sm",
                            mt="sm",
                        ),
                    ],
                    gap="sm",
                )

            except Exception as e:
                return dmc.Alert(
                    f"File validation failed: {str(e)}",
                    color="red",
                    icon=DashIconify(icon="mdi:alert"),
                    title="Validation Error",
                )

            finally:
                # Clean up temp file
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

        except Exception as e:
            return dmc.Alert(
                f"File processing error: {str(e)}",
                color="red",
                icon=DashIconify(icon="mdi:alert"),
            )

    @app.callback(
        [
            Output("data-collection-creation-modal", "opened", allow_duplicate=True),
            Output("project-data-store", "data", allow_duplicate=True),
            Output("data-collection-creation-error-alert", "children", allow_duplicate=True),
            Output("data-collection-creation-error-alert", "style", allow_duplicate=True),
        ],
        [Input("create-data-collection-creation-submit", "n_clicks")],
        [
            dash.State("data-collection-creation-name-input", "value"),
            dash.State("data-collection-creation-description-input", "value"),
            dash.State("data-collection-creation-type-select", "value"),
            dash.State("data-collection-creation-format-select", "value"),
            dash.State("data-collection-creation-separator-select", "value"),
            dash.State("data-collection-creation-custom-separator-input", "value"),
            dash.State("data-collection-creation-compression-select", "value"),
            dash.State("data-collection-creation-has-header-switch", "checked"),
            dash.State("data-collection-creation-file-upload", "contents"),
            dash.State("data-collection-creation-file-upload", "filename"),
            dash.State("project-data-store", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def submit_data_collection_creation(
        submit_clicks,
        name,
        description,
        data_type,
        file_format,
        separator,
        custom_separator,
        compression,
        has_header,
        file_contents,
        filename,
        project_data,
        local_data,
    ):
        """Handle data collection creation submission with file processing."""
        if not submit_clicks or not name or not file_contents or not filename:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        try:
            from datetime import datetime

            from depictio.dash.api_calls import api_call_create_data_collection

            logger.info(f"Creating data collection: {name}")

            # Get current project information
            if not project_data or "project_id" not in project_data:
                logger.error("No project information available")
                return (
                    dash.no_update,
                    dash.no_update,
                    "No project information available",
                    {"display": "block"},
                )

            project_id = project_data.get("project_id")
            if not project_id:
                logger.error("No project ID available")
                return (
                    dash.no_update,
                    dash.no_update,
                    "No project ID available",
                    {"display": "block"},
                )

            # Get authentication token from user session
            if not local_data or not local_data.get("access_token"):
                logger.error("No authentication token available")
                return (
                    dash.no_update,
                    dash.no_update,
                    "Authentication required. Please log in.",
                    {"display": "block"},
                )

            token = local_data["access_token"]

            # Call the API function to create the data collection
            result = api_call_create_data_collection(
                name=name,
                description=description or "",
                data_type=data_type,
                file_format=file_format,
                separator=separator,
                custom_separator=custom_separator,
                compression=compression,
                has_header=has_header,
                file_contents=file_contents,
                filename=filename,
                project_id=project_id,
                token=token,
            )

            if result and result.get("success"):
                logger.info(f"Data collection created successfully: {result.get('message')}")

                # Update project data store to trigger refresh
                updated_project_data = project_data.copy()
                updated_project_data["refresh_timestamp"] = datetime.now().isoformat()

                # Close modal and refresh project data (hide error alert)
                return False, updated_project_data, "", {"display": "none"}
            else:
                error_msg = result.get("message", "Unknown error") if result else "API call failed"
                logger.error(f"Data collection creation failed: {error_msg}")
                logger.info("DEBUG: Showing error alert in modal")  # Debug log
                return (
                    dash.no_update,
                    dash.no_update,
                    f"Failed to create data collection: {error_msg}",
                    {"display": "block"},
                )

        except Exception as e:
            logger.error(f"Error creating data collection: {str(e)}")
            logger.info("DEBUG: Showing exception error alert in modal")  # Debug log
            import traceback

            traceback.print_exc()
            return (
                dash.no_update,
                dash.no_update,
                f"Unexpected error: {str(e)}",
                {"display": "block"},
            )

    # Data collection action buttons callbacks
    @app.callback(
        Output("dc-action-modals-container", "children"),
        [
            Input({"type": "dc-overwrite-button", "index": dash.ALL}, "n_clicks"),
            Input({"type": "dc-edit-name-button", "index": dash.ALL}, "n_clicks"),
            Input({"type": "dc-delete-button", "index": dash.ALL}, "n_clicks"),
        ],
        [
            dash.State("project-data-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_dc_action_buttons(overwrite_clicks, edit_clicks, delete_clicks, project_data):
        """Handle data collection action button clicks by creating appropriate modals."""
        ctx_trigger = ctx.triggered_id

        if not ctx_trigger or not any(
            [any(overwrite_clicks), any(edit_clicks), any(delete_clicks)]
        ):
            return []

        if not project_data:
            return []

        # Get the data collection tag from the clicked button
        dc_tag = ctx_trigger["index"]

        # Find the data collection info from project data
        data_collections = project_data.get("data_collections", [])
        dc_info = None
        for dc in data_collections:
            if dc.get("data_collection_tag") == dc_tag:
                dc_info = dc
                break

        if not dc_info:
            return []

        dc_name = dc_info.get("data_collection_tag", "Unknown")
        dc_id = str(dc_info.get("id", ""))

        # Create the appropriate modal based on which button was clicked
        if ctx_trigger["type"] == "dc-overwrite-button":
            modal, modal_id = create_data_collection_overwrite_modal(
                opened=True,
                data_collection_name=dc_name,
                data_collection_id=dc_id,
            )
            return [modal]
        elif ctx_trigger["type"] == "dc-edit-name-button":
            modal, modal_id = create_data_collection_edit_name_modal(
                opened=True,
                current_name=dc_name,
                data_collection_id=dc_id,
            )
            return [modal]
        elif ctx_trigger["type"] == "dc-delete-button":
            modal, modal_id = create_data_collection_delete_modal(
                opened=True,
                data_collection_name=dc_name,
                data_collection_id=dc_id,
            )
            return [modal]

        return []

    # Modal close callbacks
    @app.callback(
        Output("data-collection-overwrite-modal", "opened", allow_duplicate=True),
        [Input("cancel-data-collection-overwrite-button", "n_clicks")],
        prevent_initial_call=True,
    )
    def close_overwrite_modal(cancel_clicks):
        """Close overwrite modal when cancel is clicked."""
        if cancel_clicks:
            return False
        return dash.no_update

    @app.callback(
        Output("data-collection-edit-name-modal", "opened", allow_duplicate=True),
        [Input("cancel-data-collection-edit-name-button", "n_clicks")],
        prevent_initial_call=True,
    )
    def close_edit_name_modal(cancel_clicks):
        """Close edit name modal when cancel is clicked."""
        if cancel_clicks:
            return False
        return dash.no_update

    @app.callback(
        Output("data-collection-delete-modal", "opened", allow_duplicate=True),
        [Input("cancel-data-collection-delete-button", "n_clicks")],
        prevent_initial_call=True,
    )
    def close_delete_modal(cancel_clicks):
        """Close delete modal when cancel is clicked."""
        if cancel_clicks:
            return False
        return dash.no_update

    # Edit name functionality callbacks
    @app.callback(
        [
            Output("data-collection-edit-name-modal", "opened", allow_duplicate=True),
            Output("project-data-store", "data", allow_duplicate=True),
            Output("data-collection-edit-name-error-alert", "children", allow_duplicate=True),
            Output("data-collection-edit-name-error-alert", "style", allow_duplicate=True),
        ],
        [Input("confirm-data-collection-edit-name-submit", "n_clicks")],
        [
            dash.State("data-collection-edit-name-name-input", "value"),
            dash.State("data-collection-edit-name-dc-id", "data"),
            dash.State("project-data-store", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_edit_name_submit(submit_clicks, new_name, dc_id, project_data, local_data):
        """Handle edit name modal submission."""
        if not submit_clicks or not new_name or not dc_id:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        try:
            from datetime import datetime

            from depictio.dash.api_calls import api_call_edit_data_collection_name

            logger.info(f"Editing data collection name: {dc_id} -> {new_name}")

            if not local_data or not local_data.get("access_token"):
                return (
                    dash.no_update,
                    dash.no_update,
                    "Authentication required",
                    {"display": "block"},
                )

            result = api_call_edit_data_collection_name(dc_id, new_name, local_data["access_token"])

            if result and result.get("success"):
                logger.info(f"Data collection name updated successfully: {result.get('message')}")
                # Update project data store to trigger refresh
                updated_project_data = project_data.copy()
                updated_project_data["refresh_timestamp"] = datetime.now().isoformat()
                # Close modal and refresh project data (hide error alert)
                return False, updated_project_data, "", {"display": "none"}
            else:
                error_msg = result.get("message", "Unknown error") if result else "API call failed"
                logger.error(f"Failed to update data collection name: {error_msg}")
                return (
                    dash.no_update,
                    dash.no_update,
                    f"Failed to update name: {error_msg}",
                    {"display": "block"},
                )

        except Exception as e:
            logger.error(f"Error updating data collection name: {str(e)}")
            return (
                dash.no_update,
                dash.no_update,
                f"Unexpected error: {str(e)}",
                {"display": "block"},
            )

    # Delete functionality callbacks
    @app.callback(
        [
            Output("data-collection-delete-modal", "opened", allow_duplicate=True),
            Output("project-data-store", "data", allow_duplicate=True),
            Output("data-collection-delete-error-alert", "children", allow_duplicate=True),
            Output("data-collection-delete-error-alert", "style", allow_duplicate=True),
        ],
        [Input("confirm-data-collection-delete-submit", "n_clicks")],
        [
            dash.State("data-collection-delete-dc-id", "data"),
            dash.State("project-data-store", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_delete_submit(submit_clicks, dc_id, project_data, local_data):
        """Handle delete modal submission."""
        if not submit_clicks or not dc_id:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        try:
            from datetime import datetime

            from depictio.dash.api_calls import api_call_delete_data_collection

            logger.info(f"Deleting data collection: {dc_id}")

            if not local_data or not local_data.get("access_token"):
                return (
                    dash.no_update,
                    dash.no_update,
                    "Authentication required",
                    {"display": "block"},
                )

            result = api_call_delete_data_collection(dc_id, local_data["access_token"])

            if result and result.get("success"):
                logger.info(f"Data collection deleted successfully: {result.get('message')}")
                # Update project data store to trigger refresh
                updated_project_data = project_data.copy()
                updated_project_data["refresh_timestamp"] = datetime.now().isoformat()
                # Close modal and refresh project data (hide error alert)
                return False, updated_project_data, "", {"display": "none"}
            else:
                error_msg = result.get("message", "Unknown error") if result else "API call failed"
                logger.error(f"Failed to delete data collection: {error_msg}")
                return (
                    dash.no_update,
                    dash.no_update,
                    f"Failed to delete: {error_msg}",
                    {"display": "block"},
                )

        except Exception as e:
            logger.error(f"Error deleting data collection: {str(e)}")
            return (
                dash.no_update,
                dash.no_update,
                f"Unexpected error: {str(e)}",
                {"display": "block"},
            )

    # Overwrite functionality callbacks
    @app.callback(
        Output("confirm-data-collection-overwrite-submit", "disabled"),
        [
            Input("data-collection-overwrite-file-upload", "contents"),
            Input("data-collection-overwrite-schema-validation", "children"),
        ],
    )
    def update_overwrite_submit_button_state(file_contents, validation_result):
        """Enable/disable overwrite submit button based on file upload and validation."""
        logger.debug(
            f"Button state update: file_contents={'[PRESENT]' if file_contents else '[MISSING]'}"
        )
        logger.debug(f"Validation result type: {type(validation_result)}")
        logger.debug(f"Validation result: {validation_result}")

        if not file_contents:
            logger.debug("No file contents, disabling button")
            return True

        # Check if validation was successful
        if isinstance(validation_result, list) and len(validation_result) > 0:
            logger.debug(f"Validation result is list with {len(validation_result)} items")
            # Look for a successful validation indicator
            for i, child in enumerate(validation_result):
                logger.debug(f"Checking validation item {i}: {type(child)}")

                # Handle both dict format (from serialization) and component objects
                if isinstance(child, dict) and "props" in child:
                    props = child["props"]
                    logger.debug(f"Item {i} has dict props: color={props.get('color')}")
                    # Check for green color (success)
                    if props.get("color") == "green":
                        logger.debug("Found green validation (dict format), enabling button")
                        return False
                    # Check for validation passed text
                    if (
                        "children" in props
                        and "validation passed" in str(props["children"]).lower()
                    ):
                        logger.debug("Found validation passed text (dict format), enabling button")
                        return False

                elif hasattr(child, "props"):
                    logger.debug(
                        f"Item {i} has object props: {hasattr(child.props, 'color')}, {hasattr(child.props, 'children')}"
                    )
                    # Check for green color (success) and validation passed text
                    if hasattr(child.props, "color") and child.props.color == "green":
                        logger.debug("Found green validation (object format), enabling button")
                        return False
                    if (
                        hasattr(child.props, "children")
                        and "validation passed" in str(child.props.children).lower()
                    ):
                        logger.debug(
                            "Found validation passed text (object format), enabling button"
                        )
                        return False

        # Also check for direct validation success
        if validation_result and isinstance(validation_result, list):
            for i, item in enumerate(validation_result):
                content = ""
                if isinstance(item, dict) and "props" in item and "children" in item["props"]:
                    content = str(item["props"]["children"]).lower()
                elif hasattr(item, "props") and hasattr(item.props, "children"):
                    content = str(item.props.children).lower()

                if content:
                    logger.debug(f"Item {i} content: {content[:100]}")
                    if "schema validation passed" in content or "validation passed" in content:
                        logger.debug("Found validation passed in content, enabling button")
                        return False

        logger.debug("No validation success found, keeping button disabled")
        return True

    @app.callback(
        [
            Output("data-collection-overwrite-file-info", "children"),
            Output("data-collection-overwrite-schema-validation", "children"),
        ],
        [Input("data-collection-overwrite-file-upload", "contents")],
        [
            dash.State("data-collection-overwrite-file-upload", "filename"),
            dash.State("data-collection-overwrite-dc-id", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_overwrite_file_upload(file_contents, filename, dc_id, local_data):
        """Handle file upload for overwrite modal with schema validation."""
        if not file_contents or not filename or not dc_id:
            return [], []

        try:
            import base64
            import tempfile
            from pathlib import Path

            import polars as pl

            from depictio.api.v1.configs.config import settings

            # Decode and save the uploaded file temporarily for validation
            # Debug: Log the file_contents format
            logger.debug(
                f"file_contents format: {file_contents[:100] if file_contents else 'None'}"
            )

            # Handle different file_contents formats
            if file_contents and "," in file_contents:
                # Standard format: "data:mime/type;base64,base64_data"
                base64_data = file_contents.split(",")[1]
                logger.debug(f"Standard format detected, base64 length: {len(base64_data)}")
                file_data = base64.b64decode(base64_data)
            elif file_contents:
                # Fallback: Assume it's already base64 encoded
                try:
                    logger.debug(f"Fallback format detected, content length: {len(file_contents)}")
                    file_data = base64.b64decode(file_contents)
                except Exception as e:
                    logger.error(f"Failed to decode file contents: {e}")
                    return [dmc.Alert("Error decoding file", color="red")], []
            else:
                logger.warning("No file contents provided")
                return [dmc.Alert("No file contents provided", color="red")], []

            logger.debug(f"File data decoded successfully, size: {len(file_data)} bytes")
            temp_file_path = Path(tempfile.gettempdir()) / filename

            with open(temp_file_path, "wb") as f:
                f.write(file_data)

            # Get file size with appropriate units
            file_size = len(file_data)
            if file_size < 1024 * 1024:  # Less than 1MB, show in KB
                file_size_display = f"{file_size / 1024:.2f} KB"
            else:
                file_size_display = f"{file_size / (1024 * 1024):.2f} MB"

            logger.debug(f"File size display: {file_size} bytes = {file_size_display}")

            file_info = dmc.Alert(
                f"File uploaded: {filename} ({file_size_display})",
                color="blue",
                icon=DashIconify(icon="mdi:file-check"),
                variant="light",
            )

            # Get existing data collection schema using the specs endpoint
            try:
                import httpx

                # Get current token from local storage
                token = local_data.get("access_token") if local_data else None
                if not token:
                    return [file_info], [dmc.Alert("Authentication token not found", color="red")]

                # Call the specs endpoint to get data collection metadata
                specs_url = f"{settings.fastapi.url}/depictio/api/v1/datacollections/specs/{dc_id}"
                headers = {"Authorization": f"Bearer {token}"}

                response = httpx.get(specs_url, headers=headers, timeout=30.0)
                response.raise_for_status()

                existing_dc = response.json()

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return [file_info], [dmc.Alert("Data collection not found", color="red")]
                else:
                    return [file_info], [
                        dmc.Alert(
                            f"Failed to retrieve data collection info: {e.response.status_code}",
                            color="red",
                        )
                    ]
            except Exception as e:
                return [file_info], [
                    dmc.Alert(f"Failed to retrieve data collection info: {str(e)}", color="red")
                ]

            # Get existing schema from delta table metadata or try to read from Delta table
            existing_schema = existing_dc.get("delta_table_schema")
            if not existing_schema:
                try:
                    # Construct S3 path for the Delta table
                    s3_path = f"s3://{settings.minio.bucket}/{dc_id}"

                    # Configure S3 storage options for reading Delta table
                    storage_options = {
                        "AWS_ENDPOINT_URL": settings.minio.endpoint_url,
                        "AWS_ACCESS_KEY_ID": settings.minio.aws_access_key_id,
                        "AWS_SECRET_ACCESS_KEY": settings.minio.aws_secret_access_key,
                        "AWS_REGION": "us-east-1",
                        "AWS_ALLOW_HTTP": "true",
                        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
                    }

                    # Read a small sample to get schema
                    df_sample = pl.read_delta(s3_path, storage_options=storage_options).limit(1)

                    # Build schema dictionary from DataFrame
                    existing_schema = {}
                    for col_name in df_sample.columns:
                        col_type = str(df_sample[col_name].dtype)
                        existing_schema[col_name] = {"type": col_type}

                except Exception as e:
                    return [file_info], [
                        dmc.Alert(
                            f"Cannot validate schema: unable to retrieve existing data collection schema ({str(e)})",
                            color="yellow",
                        )
                    ]

            # Try to read the new file
            try:
                # Determine file format from extension
                file_ext = Path(filename).suffix.lower()
                if file_ext == ".csv":
                    df = pl.read_csv(temp_file_path)
                elif file_ext == ".tsv":
                    df = pl.read_csv(temp_file_path, separator="\t")
                elif file_ext == ".parquet":
                    df = pl.read_parquet(temp_file_path)
                elif file_ext == ".feather":
                    df = pl.read_ipc(temp_file_path)
                elif file_ext in [".xls", ".xlsx"]:
                    df = pl.read_excel(temp_file_path)
                else:
                    return [file_info], [
                        dmc.Alert(f"Unsupported file format: {file_ext}", color="red")
                    ]

                # Validate schema - exclude system-generated columns
                system_columns = {"depictio_run_id", "aggregation_time"}
                new_columns = set(df.columns)
                existing_columns = (
                    set(existing_schema.keys()) if isinstance(existing_schema, dict) else set()
                )

                # Remove system columns from existing schema for comparison
                existing_user_columns = existing_columns - system_columns

                if new_columns == existing_user_columns:
                    success_message = f"✓ Schema validation passed! File contains {df.shape[0]} rows and {df.shape[1]} columns with matching schema."
                    logger.debug(f"Schema validation SUCCESS: {success_message}")
                    validation_result = [
                        dmc.Alert(
                            success_message,
                            color="green",
                            icon=DashIconify(icon="mdi:check-circle"),
                            variant="light",
                        )
                    ]
                else:
                    missing_cols = existing_user_columns - new_columns
                    extra_cols = new_columns - existing_user_columns
                    error_msg = "Schema mismatch: "
                    if missing_cols:
                        error_msg += f"Missing columns: {list(missing_cols)}. "
                    if extra_cols:
                        error_msg += f"Extra columns: {list(extra_cols)}. "

                    validation_result = [
                        dmc.Alert(
                            error_msg,
                            color="red",
                            icon=DashIconify(icon="mdi:alert-circle"),
                            variant="light",
                        )
                    ]

            except Exception as e:
                validation_result = [
                    dmc.Alert(
                        f"Failed to read file: {str(e)}",
                        color="red",
                        icon=DashIconify(icon="mdi:alert"),
                    )
                ]

            # Cleanup temp file
            temp_file_path.unlink(missing_ok=True)

            return [file_info], validation_result

        except Exception as e:
            return [
                dmc.Alert(
                    f"File processing error: {str(e)}",
                    color="red",
                    icon=DashIconify(icon="mdi:alert"),
                )
            ], []

    @app.callback(
        [
            Output("data-collection-overwrite-modal", "opened", allow_duplicate=True),
            Output("project-data-store", "data", allow_duplicate=True),
            Output("data-collection-overwrite-error-alert", "children", allow_duplicate=True),
            Output("data-collection-overwrite-error-alert", "style", allow_duplicate=True),
        ],
        [Input("confirm-data-collection-overwrite-submit", "n_clicks")],
        [
            dash.State("data-collection-overwrite-file-upload", "contents"),
            dash.State("data-collection-overwrite-file-upload", "filename"),
            dash.State("data-collection-overwrite-dc-id", "data"),
            dash.State("project-data-store", "data"),
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_overwrite_submit(
        submit_clicks, file_contents, filename, dc_id, project_data, local_data
    ):
        """Handle overwrite modal submission."""
        if not submit_clicks or not file_contents or not filename or not dc_id:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        try:
            from datetime import datetime

            from depictio.dash.api_calls import api_call_overwrite_data_collection

            logger.info(f"Overwriting data collection: {dc_id} with file: {filename}")

            if not local_data or not local_data.get("access_token"):
                return (
                    dash.no_update,
                    dash.no_update,
                    "Authentication required",
                    {"display": "block"},
                )

            # Determine file format and parameters from filename
            from pathlib import Path

            file_ext = Path(filename).suffix.lower()
            file_format = "csv"
            separator = ","
            if file_ext == ".tsv":
                file_format = "tsv"
                separator = "\t"
            elif file_ext == ".parquet":
                file_format = "parquet"
            elif file_ext == ".feather":
                file_format = "feather"
            elif file_ext in [".xls", ".xlsx"]:
                file_format = file_ext[1:]  # Remove the dot

            result = api_call_overwrite_data_collection(
                data_collection_id=dc_id,
                file_contents=file_contents,
                filename=filename,
                token=local_data["access_token"],
                file_format=file_format,
                separator=separator,
                compression="none",
                has_header=True,
            )

            if result and result.get("success"):
                logger.info(f"Data collection overwritten successfully: {result.get('message')}")
                # Update project data store to trigger refresh
                updated_project_data = project_data.copy()
                updated_project_data["refresh_timestamp"] = datetime.now().isoformat()
                # Close modal and refresh project data (hide error alert)
                return False, updated_project_data, "", {"display": "none"}
            else:
                error_msg = result.get("message", "Unknown error") if result else "API call failed"
                logger.error(f"Failed to overwrite data collection: {error_msg}")
                return (
                    dash.no_update,
                    dash.no_update,
                    f"Failed to overwrite: {error_msg}",
                    {"display": "block"},
                )

        except Exception as e:
            logger.error(f"Error overwriting data collection: {str(e)}")
            return (
                dash.no_update,
                dash.no_update,
                f"Unexpected error: {str(e)}",
                {"display": "block"},
            )

    # Storage size display callback
    @app.callback(
        Output("storage-size-display", "children"),
        [Input("project-data-store", "data")],
        prevent_initial_call=False,  # Allow initial call to show default state
    )
    def update_storage_size_display(project_data):
        """Update the storage size display card with cumulative size of all data collections."""
        if not project_data:
            return [
                dmc.Text("0", size="lg", fw="bold", c="gray", ta="center"),
                dmc.Text("bytes", size="xs", c="gray", ta="center"),
            ]

        try:
            # Extract data collections from project data
            workflows = project_data.get("workflows", [])
            all_data_collections = []

            for workflow in workflows:
                data_collections = workflow.get("data_collections", [])
                all_data_collections.extend(data_collections)

            # Calculate total storage size
            total_size_bytes = calculate_total_storage_size(all_data_collections)
            formatted_size, unit = format_storage_size(total_size_bytes)

            # Determine color based on size
            if total_size_bytes == 0:
                color = "gray"
                formatted_size = "0"
                unit = "bytes"
            elif total_size_bytes < 1024**3:  # Less than 1GB
                color = colors["orange"]
            else:  # 1GB or more
                color = colors["red"]

            return [
                dmc.Text(formatted_size, size="lg", fw="bold", c=color, ta="center"),
                dmc.Text(unit, size="xs", c="gray", ta="center"),
            ]

        except Exception as e:
            logger.error(f"Error calculating storage size: {e}")
            return [
                dmc.Text("Error", size="lg", fw="bold", c="red", ta="center"),
                dmc.Text("calc failed", size="xs", c="gray", ta="center"),
            ]


def generate_cytoscape_elements_from_project_data(data_collections):
    """Convert project data collections to cytoscape elements."""
    elements = []

    # First, collect all available columns from each data collection
    dc_columns = {}
    dc_info = {}

    for dc in data_collections:
        dc_tag = dc.get("data_collection_tag", f"DC_{dc.get('id', 'unknown')}")
        dc_info[dc_tag] = dc

        # Try to get columns from the data collection
        columns = []

        # Priority order for finding columns:
        # 1. delta_table_schema if available
        if "delta_table_schema" in dc and dc["delta_table_schema"]:
            schema = dc["delta_table_schema"]
            if isinstance(schema, dict):
                columns = list(schema.keys())
            elif isinstance(schema, list):
                # Schema might be a list of field dictionaries
                columns = [
                    field.get("name", field.get("column", str(field)))
                    for field in schema
                    if isinstance(field, dict)
                ]

        # 2. Check config.dc_specific_properties.columns_description (from YAML)
        elif dc.get("config", {}).get("dc_specific_properties", {}).get("columns_description"):
            columns_desc = dc["config"]["dc_specific_properties"]["columns_description"]
            if isinstance(columns_desc, dict):
                columns = list(columns_desc.keys())

        # 3. Check config.columns
        elif dc.get("config", {}).get("columns"):
            columns = dc["config"]["columns"]

        # 4. Check direct columns field
        elif "columns" in dc:
            columns = dc["columns"]

        # 5. Try to infer from join config + add defaults
        else:
            join_config = dc.get("config", {}).get("join")
            if join_config and "on_columns" in join_config:
                columns.extend(join_config["on_columns"])
            # Add some common default columns for visualization
            defaults = ["id", "name", "created_at", "updated_at"]
            for default in defaults:
                if default not in columns:
                    columns.append(default)

        # Remove duplicates while preserving order and ensure we have at least some columns
        seen = set()
        dc_columns[dc_tag] = [col for col in columns if col and not (col in seen or seen.add(col))]

        # Ensure we have at least one column for visualization
        if not dc_columns[dc_tag]:
            dc_columns[dc_tag] = ["id", "name"]

    # First, collect all join columns from all DCs to mark them properly
    all_join_columns = {}  # dc_tag -> set of join column names

    # Initialize empty sets for all DCs
    for dc in data_collections:
        dc_tag = dc.get("data_collection_tag", f"DC_{dc.get('id', 'unknown')}")
        all_join_columns[dc_tag] = set()

    # Now find all join relationships and mark both source and target columns
    for dc in data_collections:
        dc_tag = dc.get("data_collection_tag", f"DC_{dc.get('id', 'unknown')}")
        join_config = dc.get("config", {}).get("join")

        if join_config and "on_columns" in join_config and "with_dc" in join_config:
            on_columns = join_config["on_columns"]
            target_dc_tags = join_config["with_dc"]

            # Mark source columns as join columns
            all_join_columns[dc_tag].update(on_columns)

            # Mark target columns as join columns (same column names)
            for target_dc_tag in target_dc_tags:
                if target_dc_tag in all_join_columns:
                    all_join_columns[target_dc_tag].update(on_columns)

    logger.debug(f"All join columns mapping: {all_join_columns}")

    # Positioning approach matching the reference file prototype

    # Create data collection groups and column nodes
    for i, dc in enumerate(data_collections):
        dc_id = dc.get("id", f"dc_{i}")
        dc_tag = dc.get("data_collection_tag", f"DC_{i}")
        dc_type = dc.get("config", {}).get("type", "table")
        dc_metatype = dc.get("config", {}).get("metatype", "unknown")

        if dc_type.lower() != "table":
            continue  # Skip non-table collections

        # Get columns for this DC
        columns = dc_columns.get(dc_tag, ["id", "name"])
        num_columns = len(columns)

        # Calculate positions exactly like reference file (lines 510, 515, 518-520)
        x_offset = 300 + i * 350  # More space between data collections horizontally
        box_height = max(
            320, num_columns * 45 + 100
        )  # Min 320px, or 45px per column + more padding

        # Center the background box on the column range (exact copy from reference)
        first_column_y = 140
        last_column_y = 140 + ((num_columns - 1) * 50)
        center_y = (first_column_y + last_column_y) / 2

        # Create data collection background
        elements.append(
            {
                "data": {
                    "id": f"dc_bg_{dc_id}",
                    "label": f"{dc_tag}\n[{dc_metatype}]",
                    "type": "dc_background",
                    "column_count": num_columns,
                    "box_height": box_height,
                },
                "position": {
                    "x": x_offset + 100,
                    "y": center_y,
                },  # Simple positioning like reference
                "classes": f"data-collection-background dc-columns-{min(num_columns, 10)}",
            }
        )

        # Create column nodes
        for j, column in enumerate(columns):
            column_id = f"{dc_tag}/{column}"
            y_offset = 140 + (j * 50)  # Start lower and tighter spacing

            # Check if this column is part of a join (from comprehensive list)
            is_join_column = column in all_join_columns.get(dc_tag, set())

            elements.append(
                {
                    "data": {
                        "id": column_id,
                        "label": column,
                        "type": "column",
                        "dc_tag": dc_tag,
                        "dc_id": dc_id,
                        "is_join_column": is_join_column,
                    },
                    "position": {"x": x_offset + 100, "y": y_offset},
                    "classes": "column-node join-column" if is_join_column else "column-node",
                }
            )

    # Create a mapping from DC tags to their data for easier lookup
    dc_tags_to_data = {}
    for dc in data_collections:
        dc_tag = dc.get("data_collection_tag", f"DC_{dc.get('id', f'dc_{i}')}")
        dc_tags_to_data[dc_tag] = dc

    # Create join edges in a second pass to ensure all nodes exist
    edges_created = set()  # Track edges to avoid duplicates

    for i, dc in enumerate(data_collections):
        dc_tag = dc.get("data_collection_tag", f"DC_{dc.get('id', f'dc_{i}')}")
        join_config = dc.get("config", {}).get("join")

        if not join_config:
            continue

        on_columns = join_config.get("on_columns", [])
        join_type = join_config.get("how", "inner")
        target_dc_tags = join_config.get("with_dc", [])

        logger.debug(f"Processing joins for DC '{dc_tag}': {join_config}")

        for target_dc_tag in target_dc_tags:
            # Check if target DC exists in our data
            target_dc_exists = any(
                d.get("data_collection_tag") == target_dc_tag for d in data_collections
            )

            if not target_dc_exists:
                logger.warning(f"Target DC '{target_dc_tag}' not found in current data collections")
                continue

            for col in on_columns:
                # Check if source node was created
                source_columns = dc_columns.get(dc_tag, [])
                if col not in source_columns:
                    logger.warning(
                        f"Source column '{col}' not found in DC '{dc_tag}' columns: {source_columns}"
                    )
                    # Try to add the column if it's a join column
                    if col not in dc_columns[dc_tag]:
                        dc_columns[dc_tag].append(col)
                        logger.info(f"Added missing join column '{col}' to DC '{dc_tag}'")

                        # Create the missing column node
                        num_existing_columns = len(
                            [
                                e
                                for e in elements
                                if e["data"].get("dc_tag") == dc_tag
                                and e["data"].get("type") == "column"
                            ]
                        )
                        elements.append(
                            {
                                "data": {
                                    "id": f"{dc_tag}/{col}",
                                    "label": col,
                                    "type": "column",
                                    "dc_tag": dc_tag,
                                    "dc_id": dc.get("id", f"dc_{i}"),
                                    "is_join_column": True,
                                },
                                "position": {
                                    "x": x_offset + 100,
                                    "y": 140
                                    + (num_existing_columns * 50),  # Using 50 like reference
                                },
                                "classes": "column-node join-column",
                            }
                        )

                source_node = f"{dc_tag}/{col}"

                # For target, try the same column name first, then look for similar
                target_columns = dc_columns.get(target_dc_tag, [])
                target_col = col

                if col not in target_columns:
                    # If the exact column name doesn't exist in target, skip this edge
                    # In real joins, column names should match or be explicitly mapped
                    logger.warning(
                        f"Join column '{col}' not found in target DC '{target_dc_tag}' columns: {target_columns}"
                    )

                    # Still create the target column node for visualization purposes
                    target_col = col
                    if target_col not in dc_columns[target_dc_tag]:
                        dc_columns[target_dc_tag].append(
                            target_col
                        )  # Add missing column to visualization

                        # Create the missing column node
                        target_column_id = f"{target_dc_tag}/{target_col}"
                        target_y = 140 + (
                            len(target_columns) * 50
                        )  # Position after existing columns, using 50 like reference
                        target_dc_index = next(
                            idx
                            for idx, tdc in enumerate(data_collections)
                            if tdc.get("data_collection_tag") == target_dc_tag
                        )
                        target_x_offset = (
                            target_dc_index * 350
                        )  # Simple offset calculation like reference

                        elements.append(
                            {
                                "data": {
                                    "id": target_column_id,
                                    "label": f"{target_col} (join)",
                                    "type": "column",
                                    "dc_tag": target_dc_tag,
                                    "dc_id": dc_tags_to_data[target_dc_tag].get(
                                        "id", f"dc_{target_dc_index}"
                                    ),
                                    "is_join_column": True,
                                },
                                "position": {
                                    "x": target_x_offset + 100,  # Simple positioning like reference
                                    "y": target_y,
                                },
                                "classes": "column-node join-column",
                            }
                        )

                target_node = f"{target_dc_tag}/{target_col}"

                # Create unique edge identifier to avoid duplicates
                edge_key = tuple(sorted([source_node, target_node]))
                if edge_key in edges_created:
                    continue
                edges_created.add(edge_key)

                # Determine adjacency for edge styling
                source_dc_index = i
                target_dc_index = next(
                    (
                        idx
                        for idx, d in enumerate(data_collections)
                        if d.get("data_collection_tag") == target_dc_tag
                    ),
                    0,
                )
                is_adjacent = abs(source_dc_index - target_dc_index) == 1
                adjacency_class = "edge-adjacent" if is_adjacent else "edge-distant"

                elements.append(
                    {
                        "data": {
                            "id": f"join_{dc_tag}_{target_dc_tag}_{col}",
                            "source": source_node,
                            "target": target_node,
                            "label": join_type,
                            "join_type": join_type,
                            "is_adjacent": is_adjacent,
                        },
                        "classes": f"join-edge join-{join_type} {adjacency_class}",
                    }
                )

                logger.debug(f"Created edge: {source_node} -> {target_node} ({join_type})")

    return elements


def load_data_collection_dataframe(
    workflow_id: str | None,
    data_collection_id: str,
    token: str | None = None,
    limit_rows: int = 1000,
) -> tuple[pl.DataFrame | None, str]:
    """
    Generic function to load dataframe from Delta table location.

    Args:
        workflow_id: Workflow ID (optional for basic projects)
        data_collection_id: Data collection ID
        token: Authorization token
        limit_rows: Maximum number of rows to load

    Returns:
        Tuple of (dataframe, error_message)
    """
    try:
        if workflow_id:
            # Advanced project with workflow
            df = load_deltatable_lite(
                workflow_id=ObjectId(workflow_id),
                data_collection_id=ObjectId(data_collection_id),
                metadata=None,
                TOKEN=token,
                limit_rows=limit_rows,
            )
        else:
            # Basic project - load directly using data collection ID
            df = load_deltatable_lite(
                workflow_id=ObjectId(
                    data_collection_id
                ),  # Use DC ID as workflow ID for basic projects
                data_collection_id=ObjectId(data_collection_id),
                metadata=None,
                TOKEN=token,
                limit_rows=limit_rows,
            )
        return df, ""
    except Exception as e:
        logger.error(f"Error loading data collection {data_collection_id}: {e}")
        return None, str(e)
