"""Projects layout module for the Depictio dashboard.

This module provides the UI components and callbacks for project management,
including:
- Project listing and categorization (owned vs shared)
- Project creation modal with stepper wizard
- Project editing and deletion
- Workflow and data collection rendering within projects

The module uses DMC 2.0+ (Dash Mantine Components) for consistent UI and
supports both light and dark themes.
"""

import dash
import dash_ag_grid as dag
import dash_mantine_components as dmc
import httpx
import yaml
from bson import ObjectId
from dash import ALL, MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify
from pydantic import validate_call

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.api_calls import (
    api_call_create_project,
    api_call_delete_project,
    api_call_fetch_user_from_token,
    api_call_update_project,
)
from depictio.dash.colors import colors
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.projects import Project
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import Workflow

# =============================================================================
# Data Fetching Functions
# =============================================================================


@validate_call
def fetch_projects(token: str) -> list[Project]:
    """Fetch all projects accessible to the current user.

    Args:
        token: JWT authentication token for API authorization.

    Returns:
        List of Project objects. Returns empty list on error.
    """
    url = f"{API_BASE_URL}/depictio/api/v1/projects/get/all"
    headers = {"Authorization": f"Bearer {token}"}
    response = httpx.get(url, headers=headers)

    if response.status_code != 200:
        logger.warning(f"Failed to fetch projects: HTTP {response.status_code}")
        return []

    try:
        projects_data = response.json()
        if not isinstance(projects_data, list):
            logger.error(f"Expected list of projects, got {type(projects_data)}")
            return []

        logger.debug(f"Fetched {len(projects_data)} projects from API.")
        return [Project.from_mongo(project) for project in projects_data]
    except Exception as e:
        logger.error(f"Error processing projects data: {e}")
        return []


# =============================================================================
# Modal Components
# =============================================================================


def create_project_modal(opened: bool = False) -> tuple[dmc.Modal, str]:
    """Create the project creation modal with stepper wizard.

    The modal guides users through a two-step process:
    1. Project Type Selection (Basic vs Advanced)
    2. Project Details Configuration

    Args:
        opened: Initial open state of the modal. Defaults to False.

    Returns:
        Tuple of (modal component, modal ID string).
    """
    modal_id = "project-creation-modal"

    modal = dmc.Modal(
        opened=False,  # Always start closed to prevent flashing
        id=modal_id,
        centered=True,
        withCloseButton=True,
        closeOnClickOutside=False,
        closeOnEscape=False,
        overlayProps={
            "overlayBlur": 3,
            "overlayOpacity": 0.55,
        },
        shadow="xl",
        radius="md",
        size="xl",
        zIndex=10000,
        styles={
            "modal": {
                "padding": "28px",
            },
        },
        children=[
            html.Div(id="dummy-hover-output", style={"display": "none"}),
            dcc.Store(
                id="project-creation-store",
                data={
                    "current_step": 0,
                    "project_type": None,
                    "project_name": "",
                    "is_public": False,
                    "data_collections": [],
                },
            ),
            dcc.Store(
                id="project-card-click-memory",
                data={"basic_clicks": 0},
                storage_type="memory",
            ),
            dmc.Stack(
                gap="xl",
                children=[
                    # Header with icon and title
                    dmc.Group(
                        justify="center",
                        gap="sm",
                        children=[
                            DashIconify(
                                icon="mdi:folder-plus-outline",
                                width=40,
                                height=40,
                                color=colors["teal"],
                            ),
                            dmc.Title(
                                "Create New Project",
                                order=1,
                                c=colors["teal"],
                                style={"margin": 0},
                            ),
                        ],
                    ),
                    # Divider
                    dmc.Divider(style={"marginTop": 5, "marginBottom": 5}),
                    # Stepper
                    dmc.Stepper(
                        id="project-creation-stepper",
                        active=0,
                        color=colors["teal"],
                        children=[
                            dmc.StepperStep(
                                label="Project Type",
                                description="Choose basic or advanced",
                                children=[html.Div(id="step-1-content")],
                            ),
                            dmc.StepperStep(
                                label="Project Details",
                                description="Configure your project",
                                children=[html.Div(id="step-2-content")],
                            ),
                            dmc.StepperCompleted(
                                children=[
                                    dmc.Center(
                                        [
                                            dmc.Stack(
                                                [
                                                    DashIconify(
                                                        icon="mdi:check-circle",
                                                        width=64,
                                                        color=colors["teal"],
                                                    ),
                                                    dmc.Text(
                                                        "Project created successfully!",
                                                        ta="center",
                                                        fw="bold",
                                                    ),
                                                ],
                                                align="center",
                                            )
                                        ]
                                    )
                                ]
                            ),
                        ],
                    ),
                    # Navigation buttons
                    dmc.Group(
                        justify="space-between",
                        mt="xl",
                        children=[
                            dmc.Button(
                                "Previous",
                                id="project-stepper-prev",
                                variant="outline",
                                disabled=True,
                            ),
                            dmc.Group(
                                [
                                    dmc.Button(
                                        "Next",
                                        id="project-stepper-next",
                                        color=colors["teal"],
                                    ),
                                ],
                                justify="flex-end",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )

    return modal, modal_id


# Create project modal and layout at module level (similar to dashboards_management.py)
project_modal, project_modal_id = create_project_modal(opened=False)

# Create the main layout with modal included
layout = html.Div(
    [
        project_modal,
        html.Div(id="projects-content"),  # Content populated by callback
    ]
)


def create_step_1_content() -> dmc.Stack:
    """Create Step 1 content: Project Type Selection.

    Displays two card options:
    - Basic Project: UI-based data collection upload
    - Advanced Project: CLI-based workflow management (disabled in UI)

    Returns:
        Stack component containing the project type selection cards.
    """
    return dmc.Stack(
        [
            dmc.Space(h="xl"),  # Add extra space above the title
            dmc.Text("Choose your project type:", fw="bold", size="lg", ta="center"),
            dmc.Space(h="lg"),  # Increased space below the title
            dmc.Grid(
                [
                    dmc.GridCol(
                        [
                            html.Div(
                                [
                                    dmc.Card(
                                        [
                                            dmc.Stack(
                                                [
                                                    dmc.Center(
                                                        [
                                                            DashIconify(
                                                                icon="mdi:view-dashboard-outline",
                                                                width=48,
                                                                color=colors["teal"],
                                                            )
                                                        ]
                                                    ),
                                                    dmc.Text(
                                                        "Basic Project",
                                                        fw="bold",
                                                        size="lg",
                                                        ta="center",
                                                    ),
                                                    dmc.Text(
                                                        "Perfect for simple data visualization and exploration. "
                                                        "No workflows required - upload data collections directly through the UI. "
                                                        "Best for individual datasets and quick analysis.",
                                                        size="sm",
                                                        ta="center",
                                                        c="gray",
                                                    ),
                                                    # Spacer to push badge to bottom
                                                    dmc.Space(style={"flex": "1"}),
                                                    dmc.Center(
                                                        [
                                                            dmc.Badge(
                                                                "UI Creation Only",
                                                                color="cyan",
                                                                variant="light",
                                                            )
                                                        ]
                                                    ),
                                                ],
                                                gap="sm",
                                                style={"height": "100%"},
                                            )
                                        ],
                                        withBorder=True,
                                        shadow="sm",
                                        radius="md",
                                        p="lg",
                                        style={
                                            "height": "280px",
                                            "transition": "all 0.2s ease",
                                        },
                                        className="project-type-card",
                                    )
                                ],
                                id="basic-project-card",
                                n_clicks=0,
                                style={
                                    "cursor": "pointer",
                                    "transition": "all 0.2s ease",
                                },
                                className="project-type-card-wrapper",
                            )
                        ],
                        span=6,
                    ),
                    dmc.GridCol(
                        [
                            html.Div(
                                [
                                    dmc.Card(
                                        [
                                            dmc.Stack(
                                                [
                                                    dmc.Center(
                                                        [
                                                            DashIconify(
                                                                icon="mdi:workflow",
                                                                width=48,
                                                                color="orange",
                                                            )
                                                        ]
                                                    ),
                                                    dmc.Text(
                                                        "Advanced Project",
                                                        fw="bold",
                                                        size="lg",
                                                        ta="center",
                                                    ),
                                                    dmc.Text(
                                                        "Designed for complex sequencing runs, processing workflows, and data ingestion pipelines. "
                                                        "Requires depictio-CLI for project design and workflow management. "
                                                        "Best for bioinformatics and computational analysis.",
                                                        size="sm",
                                                        ta="center",
                                                        c="gray",
                                                    ),
                                                    # Spacer to push badge to bottom
                                                    dmc.Space(style={"flex": "1"}),
                                                    dmc.Center(
                                                        [
                                                            dmc.Badge(
                                                                "depictio-CLI only",
                                                                color="orange",
                                                                variant="light",
                                                            )
                                                        ]
                                                    ),
                                                ],
                                                gap="sm",
                                                style={"height": "100%"},
                                            )
                                        ],
                                        withBorder=True,
                                        shadow="sm",
                                        radius="md",
                                        p="lg",
                                        style={
                                            "height": "280px",
                                            "transition": "all 0.2s ease",
                                        },
                                        className="project-type-card",
                                    )
                                ],
                                id="advanced-project-card",
                                style={
                                    "cursor": "not-allowed",
                                    "opacity": "0.6",
                                },
                                className="project-type-card-wrapper-disabled",
                            )
                        ],
                        span=6,
                    ),
                ]
            ),
        ]
    )


def create_step_2_content(project_type: str | None = None) -> dmc.Stack:
    """Create Step 2 content: Project Details configuration.

    For basic projects: Shows name, description, and visibility inputs.
    For advanced projects: Shows CLI setup instructions.

    Args:
        project_type: Either 'basic' or 'advanced'. None returns basic form.

    Returns:
        Stack component containing the project details form.
    """
    if project_type == "advanced":
        return dmc.Stack(
            [
                dmc.Center([DashIconify(icon="mdi:console", width=64, color="orange")]),
                dmc.Text("Advanced Project Setup", fw="bold", size="xl", ta="center"),
                dmc.Text(
                    "Advanced projects require the depictio-CLI for proper setup and configuration.",
                    size="lg",
                    ta="center",
                    c="gray",
                ),
                dmc.Divider(),
                dmc.Stack(
                    [
                        dmc.Text("To create an advanced project:", fw="bold"),
                        dmc.List(
                            [
                                dmc.ListItem("Install depictio-CLI: pip install depictio"),
                                dmc.ListItem("Initialize your project: depictio init"),
                                dmc.ListItem("Configure workflows and data collections"),
                                dmc.ListItem("Register your project: depictio register"),
                            ]
                        ),
                        dmc.Alert(
                            "Advanced projects cannot be created through the web interface. "
                            "Please use the CLI for the full workflow management capabilities.",
                            color="orange",
                            icon=DashIconify(icon="mdi:information"),
                        ),
                    ]
                ),
            ]
        )

    # Basic project form
    return dmc.Stack(
        [
            dmc.TextInput(
                label="Project Name",
                description="Give your project a descriptive name",
                placeholder="Enter project name",
                id="project-name-input",
                required=True,
                leftSection=DashIconify(icon="mdi:folder-outline"),
            ),
            dmc.Textarea(
                label="Project Description (Optional)",
                description="Describe what this project is about",
                placeholder="Enter project description...",
                id="project-description-input",
                autosize=True,
                minRows=2,
                maxRows=4,
            ),
            dmc.Switch(
                id="project-public-switch",
                label="Make this project public",
                description="Public projects are visible to all users",
                color=colors["teal"],
            ),
        ]
    )


def create_step_3_content() -> dmc.Stack:
    """Create Step 3 content: Data Collections upload (Basic projects only).

    Note: This step is currently unused in the two-step wizard but kept
    for potential future expansion.

    Returns:
        Stack component with data collection upload interface.
    """
    return dmc.Stack(
        [
            dmc.Text("Add Data Collections", fw="bold", size="lg"),
            dmc.Text(
                "Upload tabular data files (CSV, TSV, Excel) to create data collections.", c="gray"
            ),
            dmc.Divider(),
            html.Div(id="data-collections-list"),
            dmc.Button(
                "+ Add Data Collection",
                id="add-data-collection-button",
                variant="outline",
                leftSection=DashIconify(icon="mdi:plus"),
            ),
            html.Div(id="data-collection-form", style={"display": "none"}),
        ]
    )


# =============================================================================
# Rendering Components
# =============================================================================


def return_deltatable_for_view(
    workflow_id: str, dc: DataCollection, token: str
) -> tuple[dmc.AccordionPanel, dmc.AccordionControl]:
    """Create an AG Grid table preview for a data collection.

    Loads data from the Delta table and displays up to 100 rows
    in a paginated AG Grid component.

    Args:
        workflow_id: ID of the parent workflow.
        dc: DataCollection model instance.
        token: JWT authentication token.

    Returns:
        Tuple of (AccordionPanel with grid, AccordionControl for toggle).
    """
    df = load_deltatable_lite(
        workflow_id=ObjectId(workflow_id),
        data_collection_id=ObjectId(str(dc.id)),
        TOKEN=token,
        limit_rows=1000,
        load_for_preview=True,
    )
    logger.info(
        f"df shape: {df.shape} for {workflow_id}/{dc.id} with name {dc.data_collection_tag}"
    )
    columnDefs = [{"field": c, "headerName": c} for c in df.columns]

    # # if description in col sub dict, update headerTooltip
    # for col in columnDefs:
    #     if "description" in cols[col["field"]] and cols[col["field"]]["description"] is not None:
    #         col["headerTooltip"] = f"{col['headerTooltip']} | Description: {cols[col['field']]['description']}"

    grid = dag.AgGrid(
        rowData=df.to_pandas().head(100).to_dict("records"),
        id={"type": "project-dc-table", "index": f"{workflow_id}/{dc.id}"},
        # Uncomment the following lines to enable infinite scrolling
        # rowModelType="infinite",
        columnDefs=columnDefs,
        dashGridOptions={
            "tooltipShowDelay": 500,
            "pagination": True,
            "paginationAutoPageSize": False,
            "animateRows": False,
            # Uncomment and adjust the following settings for infinite scroll
            # "rowBuffer": 0,
            # "maxBlocksInCache": 2,
            # "cacheBlockSize": 100,
            # "cacheOverflowSize": 2,
            # "maxConcurrentDatasourceRequests": 2,
            # "infiniteInitialRowCount": 1,
            # "rowSelection": "multiple",
        },
        columnSize="sizeToFit",
        defaultColDef={"resizable": True, "sortable": True, "filter": True},
        className="ag-theme-alpine",  # Default theme, will be updated by callback
    )
    preview_panel = dmc.AccordionPanel(dmc.Paper(grid, p="md"))
    preview_control = dmc.AccordionControl(
        dmc.Text("Preview", fw="bold", className="label-text"),
        icon=DashIconify(icon="material-symbols:preview", width=20),
    )
    return preview_panel, preview_control


def render_data_collection(dc: DataCollection, workflow_id: str, token: str) -> dmc.Paper:
    """Render a single data collection as an expandable accordion item.

    Displays the data collection with nested accordions for:
    - Details (ID, tag, description, type, metatype)
    - CLI configuration (YAML dump)
    - Preview (table data, if applicable)

    Args:
        dc: DataCollection model instance.
        workflow_id: ID of the parent workflow (empty string for basic projects).
        token: JWT authentication token for loading previews.

    Returns:
        Paper component containing the data collection accordion.
    """
    # Set icon based on data collection type
    if dc.config.type.lower() == "table":
        icon = "mdi:table"
    elif dc.config.type.lower() == "multiqc":
        icon = "/assets/images/logos/multiqc.png"  # Use MultiQC logo
    else:
        icon = "mdi:file-document"
    dc_config = yaml.dump(dc.config.model_dump(), default_flow_style=False)
    dc_config_md = f"```yaml\n{dc_config}\n```"

    # Preview Section for Tables (but not for MultiQC)
    # MultiQC data is stored in S3 as processed reports, not suitable for table preview
    if dc.config.type.lower() == "table":
        # preview_panel, preview_control = return_deltatable_for_view(
        #     workflow_id, dc, token
        # )
        preview_panel = None
        preview_control = None
    else:
        # Disable preview for non-table types (including MultiQC)
        preview_panel = None
        preview_control = None

    # Hide metatype badge for MultiQC type (since it doesn't use traditional metatypes)
    show_metatype_badge = dc.config.type.lower() != "multiqc"

    if show_metatype_badge:
        metatype_lower = dc.config.metatype.lower() if dc.config.metatype else "unknown"
        # TODO: DMC 2.0+ - 'black' is not a valid color for Badge, using 'dark' instead
        badge_type_metatype = dmc.Badge(
            children=("Metadata" if metatype_lower == "metadata" else "Aggregate"),
            color="blue" if metatype_lower == "metadata" else "dark",
            className="ml-2",
            style=(
                {"display": "inline-block"} if metatype_lower == "metadata" else {"display": "none"}
            ),
        )
    else:
        badge_type_metatype = html.Div()  # Empty placeholder for MultiQC

    # DMC 2.0+ - Using regular Accordion with AccordionItem structure
    return dmc.Paper(
        children=[
            dmc.Accordion(
                multiple=True,  # Allow multiple panels to be open simultaneously
                children=[
                    dmc.AccordionItem(
                        value="data-collection-details",
                        children=[
                            dmc.AccordionControl(
                                dmc.Group(
                                    [
                                        dmc.Text(dc.data_collection_tag),
                                        badge_type_metatype,
                                    ]
                                ),
                                icon=(
                                    html.Img(src=icon, style={"width": "20px", "height": "20px"})
                                    if icon.startswith("/assets/")
                                    else DashIconify(icon=icon, width=20)
                                ),
                            ),
                            dmc.AccordionPanel(
                                children=[
                                    dmc.Accordion(
                                        children=[
                                            dmc.AccordionItem(
                                                value="details",
                                                children=[
                                                    dmc.AccordionControl(
                                                        "Details",
                                                        icon=DashIconify(
                                                            icon="mdi:information-outline",
                                                            width=20,
                                                        ),
                                                    ),
                                                    dmc.AccordionPanel(
                                                        children=[
                                                            dmc.Group(
                                                                children=[
                                                                    dmc.Text(
                                                                        "Database ID:",
                                                                        fw="bold",
                                                                        className="label-text",
                                                                    ),
                                                                    dmc.Text(
                                                                        str(dc.id), fw="normal"
                                                                    ),
                                                                ],
                                                                gap="xs",
                                                            ),
                                                            dmc.Group(
                                                                children=[
                                                                    dmc.Text(
                                                                        "Tag:",
                                                                        fw="bold",
                                                                        className="label-text",
                                                                    ),
                                                                    dmc.Text(
                                                                        dc.data_collection_tag,
                                                                        fw="normal",
                                                                    ),
                                                                ],
                                                                gap="xs",
                                                            ),
                                                            dmc.Group(
                                                                children=[
                                                                    dmc.Text(
                                                                        "Description:",
                                                                        fw="bold",
                                                                        className="label-text",
                                                                    ),
                                                                    dmc.Text(
                                                                        (
                                                                            dc.description
                                                                            if hasattr(
                                                                                dc,
                                                                                "description",
                                                                            )
                                                                            else ""
                                                                        ),
                                                                        fw="normal",
                                                                    ),
                                                                ],
                                                                gap="xs",
                                                            ),
                                                            dmc.Group(
                                                                children=[
                                                                    dmc.Text(
                                                                        "Type:",
                                                                        fw="bold",
                                                                        className="label-text",
                                                                    ),
                                                                    dmc.Text(
                                                                        dc.config.type,
                                                                        fw="normal",
                                                                    ),
                                                                ],
                                                                gap="xs",
                                                            ),
                                                            dmc.Group(
                                                                children=[
                                                                    dmc.Text(
                                                                        "MetaType:",
                                                                        fw="bold",
                                                                        className="label-text",
                                                                    ),
                                                                    dmc.Text(
                                                                        dc.config.metatype,
                                                                        fw="normal",
                                                                    ),
                                                                ],
                                                                gap="xs",
                                                            ),
                                                        ]
                                                    ),
                                                ],
                                            ),
                                            dmc.AccordionItem(
                                                value="config",
                                                children=[
                                                    dmc.AccordionControl(
                                                        dmc.Text(
                                                            "depictio-CLI configuration",
                                                            fw="bold",
                                                            className="label-text",
                                                        ),
                                                        icon=DashIconify(
                                                            icon="ic:baseline-settings-applications",
                                                            width=20,
                                                        ),
                                                    ),
                                                    dmc.AccordionPanel(
                                                        children=[
                                                            dmc.Paper(
                                                                children=dcc.Markdown(
                                                                    children=dc_config_md
                                                                ),
                                                                p="md",
                                                                radius="sm",
                                                                withBorder=True,
                                                                shadow="xs",
                                                            )
                                                        ]
                                                    ),
                                                ],
                                            ),
                                        ]
                                        + (
                                            [
                                                dmc.AccordionItem(
                                                    value="preview",
                                                    children=[
                                                        preview_control,
                                                        preview_panel,
                                                    ],
                                                )
                                            ]
                                            if preview_control and preview_panel
                                            else []
                                        ),
                                        multiple=True,
                                        chevronPosition="right",
                                        variant="contained",
                                    ),
                                ]
                            ),
                        ],
                    ),
                ],
            ),
        ],
        p="md",
        radius="sm",
        withBorder=True,
        shadow="xs",
        style={"marginBottom": "10px"},
    )


def render_workflow_item(wf: Workflow, token: str) -> dmc.AccordionItem:
    """Render a single workflow as an expandable accordion item.

    Displays workflow details and nested data collections with
    engine-specific icons (Snakemake, Nextflow, etc.).

    Args:
        wf: Workflow model instance.
        token: JWT authentication token for loading data collections.

    Returns:
        AccordionItem component containing workflow details and data collections.
    """
    workflow_details = dmc.Paper(
        children=[
            html.Div(
                children=[
                    dmc.Group(
                        children=[
                            dmc.Text("Database ID:", fw="bold", className="label-text"),
                            dmc.Text(str(wf.id), fw="normal"),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Name:", fw="bold", className="label-text"),
                            dmc.Text(wf.name, fw="normal"),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Engine:", fw="bold", className="label-text"),
                            dmc.Text(
                                f"{wf.engine.name}"
                                + (f" (version {wf.engine.version})" if wf.engine.version else ""),
                                fw="normal",
                            ),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Repository URL:", fw="bold", className="label-text"),
                            dmc.Anchor(
                                wf.repository_url,
                                href=wf.repository_url,
                                target="_blank",
                                fw="normal",
                            ),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Description:", fw="bold", className="label-text"),
                            dmc.Text(wf.description, fw="normal"),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Created at:", fw="bold", className="label-text"),
                            dmc.Text(wf.registration_time, fw="normal"),
                        ],
                        gap="xs",
                    ),
                    # dmc.Group(
                    #     children=[
                    #         dmc.Text("Owners:", fw="bold", className="label-text"),
                    #         dmc.Text(str([o.id for o in wf.permissions.owners]), fw="medium"),
                    #     ],
                    #     gap="xs",
                    # ),
                    # dmc.Group(
                    #     children=[
                    #         dmc.Text("Viewers:", fw="bold", className="label-text"),
                    #         dmc.Text(str(wf.permissions.viewers), fw="medium"),
                    #     ],
                    #     gap="xs",
                    # ),
                ],
                className="dataset-details p-3",
            ),
        ],
        radius="md",
        withBorder=True,
        shadow="sm",
        p="md",
    )

    # Render data collections if they exist
    if hasattr(wf, "data_collections") and wf.data_collections:
        data_collections = [
            render_data_collection(dc, str(wf.id), token) for dc in wf.data_collections
        ]
        data_collections_section = dmc.Paper(
            children=data_collections,
            p="md",
            radius="md",
            withBorder=True,
            shadow="sm",
        )
    else:
        data_collections_section = None

    wf_icon_map = {
        "snakemake": "vscode-icons:file-type-snakemake",
        "nextflow": "vscode-icons:file-type-nextflow",
        "python": "vscode-icons:file-type-python",
        "r": "vscode-icons:file-type-r",
        "bash": "vscode-icons:file-type-bash",
        "galaxy": "vscode-icons:file-type-galaxy",
        "cwl": "vscode-icons:file-type-cwl",
        "rust": "vscode-icons:file-type-rust",
        # default icon for unknown or unsupported engines -
        "none": "hugeicons:workflow-square-01",
    }
    wf_icon = wf_icon_map.get(wf.engine.name.lower(), "hugeicons:workflow-square-01")

    return dmc.AccordionItem(
        children=[
            dmc.AccordionControl(
                f"{wf.engine.name} / {wf.name} ({str(wf.id)})",
                icon=DashIconify(icon=wf_icon, width=20),
            ),
            dmc.AccordionPanel(
                children=[
                    dmc.Accordion(
                        children=[
                            dmc.AccordionItem(
                                value="workflow-details",
                                children=[
                                    dmc.AccordionControl(
                                        "Details",
                                        icon=DashIconify(icon="mdi:information-outline", width=20),
                                    ),
                                    dmc.AccordionPanel(workflow_details),
                                ],
                            ),
                            dmc.AccordionItem(
                                value="workflow-data-collections",
                                children=[
                                    dmc.AccordionControl(
                                        "Data Collections",
                                        icon=DashIconify(icon="mdi:database", width=20),
                                    ),
                                    dmc.AccordionPanel(
                                        children=[
                                            (
                                                data_collections_section
                                                if data_collections_section
                                                else html.P("No data collections available.")
                                            )
                                        ]
                                    ),
                                ],
                            ),
                        ],
                        multiple=True,
                    ),
                ]
            ),
        ],
        value=f"{wf.workflow_tag} ({str(wf.id)})",
    )


def create_project_management_panel(project: Project, current_user: UserBase) -> list:
    """Create the project management panel with edit and delete controls.

    Includes edit name button, delete button, and their respective modals.
    Buttons are disabled if the user lacks management permissions.

    Args:
        project: Project model instance.
        current_user: Current user for permission checking.

    Returns:
        List containing the button group and modal components.
    """
    from depictio.dash.layouts.layouts_toolbox import (
        create_add_with_input_modal,
        create_delete_confirmation_modal,
    )

    # Check if current user can manage this project (is owner or admin)
    user_can_manage = current_user.is_admin or current_user.id in [
        owner.id for owner in project.permissions.owners
    ]

    # Create input field for the edit modal
    edit_input_field = dmc.TextInput(
        id={"type": "edit-project-name-input", "index": str(project.id)},
        label="Project Name",
        placeholder="Enter new project name",
        value=project.name,
        required=True,
    )

    # Create edit modal with unique prefix per project
    edit_modal, edit_modal_id = create_add_with_input_modal(
        id_prefix="edit-project-name",
        item_id=str(project.id),
        input_field=edit_input_field,
        title="Edit Project Name",
        title_color="blue",
        message="Enter a new name for this project.",
        confirm_button_text="Save Changes",
        confirm_button_color="blue",
        icon="mdi:pencil",
        opened=False,
    )

    # Create delete modal
    delete_modal, delete_modal_id = create_delete_confirmation_modal(
        id_prefix="delete-project",
        item_id=str(project.id),
        title="Delete Project",
        message=f"Are you sure you want to delete the project '{project.name}'? This action cannot be undone and will permanently remove all associated data.",
        delete_button_text="Delete Project",
        cancel_button_text="Cancel",
        icon="mdi:alert-circle",
        opened=False,
    )

    return [
        dmc.Group(
            [
                dmc.Button(
                    "Edit Project Name",
                    id={"type": "edit-project-name-button", "index": str(project.id)},
                    variant="outline",
                    color="blue",
                    leftSection=DashIconify(icon="mdi:pencil", width=16),
                    size="sm",
                    disabled=not user_can_manage,
                ),
                dmc.Button(
                    "Delete Project",
                    id={"type": "delete-project-button", "index": str(project.id)},
                    variant="outline",
                    color="red",
                    leftSection=DashIconify(icon="mdi:delete", width=16),
                    size="sm",
                    disabled=not user_can_manage,
                ),
            ],
            gap="md",
        ),
        # Add the modals
        edit_modal,
        delete_modal,
    ]


# =============================================================================
# PROJECT ITEM HELPER FUNCTIONS
# =============================================================================


def _create_project_detail_row(label: str, value) -> dmc.Group:
    """Create a single detail row for project information.

    Args:
        label: Label text for the row.
        value: Value component or text.

    Returns:
        Group component with label and value.
    """
    return dmc.Group(
        children=[
            dmc.Text(f"{label}:", fw="bold", className="label-text"),
            value if not isinstance(value, str) else dmc.Text(value, fw="normal"),
        ],
        gap="xs",
    )


def _format_users_list(users: list) -> str:
    """Format a list of users for display.

    Args:
        users: List of user objects with email and id.

    Returns:
        Formatted string of users.
    """
    if not users:
        return "None"
    return " ; ".join([f"{u.email} - {u.id}" for u in users])


def _create_project_details_paper(project: Project) -> dmc.Paper:
    """Create the project details paper component.

    Args:
        project: Project model instance.

    Returns:
        Paper component with project details.
    """
    project_type = getattr(project, "project_type", "basic")

    # Create URL row - either as anchor or text
    url_value = (
        dmc.Anchor(
            project.data_management_platform_project_url,
            href=project.data_management_platform_project_url,
            target="_blank",
            fw="normal",
        )
        if project.data_management_platform_project_url
        else dmc.Text("Not defined", fw="normal")
    )

    rows = [
        _create_project_detail_row("Name", project.name),
        _create_project_detail_row("Database ID", str(project.id)),
        _create_project_detail_row(
            "Description", project.description if project.description else "Not defined"
        ),
        dmc.Group(
            children=[
                dmc.Text("Data Management Platform URL:", fw="bold", className="label-text"),
                url_value,
            ],
            gap="xs",
        ),
        _create_project_detail_row("Created at", project.registration_time),
        _create_project_detail_row("Owners", _format_users_list(project.permissions.owners)),
        _create_project_detail_row(
            "Editors",
            _format_users_list(project.permissions.editors)
            if project.permissions.editors
            else "None",
        ),
        _create_project_detail_row(
            "Viewers",
            _format_users_list(project.permissions.viewers)
            if project.permissions.viewers
            else "None",
        ),
        dmc.Group(
            children=[
                dmc.Text("Is public:", fw="bold", className="label-text"),
                dmc.Badge(
                    "Public" if project.is_public else "Private",
                    color="green" if project.is_public else "violet",
                    variant="filled",
                    radius="xl",
                    size="xs",
                    style={"width": "100px", "justifyContent": "center"},
                ),
            ],
            gap="xs",
        ),
        dmc.Group(
            children=[
                dmc.Text("Project type:", fw="bold", className="label-text"),
                dmc.Badge(
                    project_type.title(),
                    color="orange" if project_type == "advanced" else "cyan",
                    variant="light",
                    radius="xl",
                    size="xs",
                    style={"width": "100px", "justifyContent": "center"},
                ),
            ],
            gap="xs",
        ),
    ]

    return dmc.Paper(
        children=[html.Div(children=rows, className="project-details p-3")],
        radius="md",
        withBorder=True,
        shadow="sm",
        p="md",
    )


def _determine_user_role(project: Project, current_user: UserBase) -> tuple[str, str]:
    """Determine user's role and badge color for the project.

    Args:
        project: Project model instance.
        current_user: Current user.

    Returns:
        Tuple of (role_name, badge_color).
    """
    owner_ids = [str(o.id) for o in project.permissions.owners]
    if str(current_user.id) in owner_ids:
        return "Owner", "blue"

    if hasattr(project.permissions, "editors") and project.permissions.editors:
        editor_ids = [str(e.id) for e in project.permissions.editors]
        if str(current_user.id) in editor_ids:
            return "Editor", "teal"

    viewer_ids = [str(v.id) for v in project.permissions.viewers if hasattr(v, "id")]
    if str(current_user.id) in viewer_ids:
        return "Viewer", "gray"

    return "Viewer", "gray"


def _create_project_badges(
    project: Project, current_user: UserBase
) -> tuple[dmc.Badge, dmc.Badge, dmc.Badge]:
    """Create badges for project type, visibility, and user role.

    Args:
        project: Project model instance.
        current_user: Current user for role determination.

    Returns:
        Tuple of (project_type_badge, visibility_badge, role_badge).
    """
    project_type = getattr(project, "project_type", "basic")
    is_public = getattr(project, "is_public", False)
    role, role_color = _determine_user_role(project, current_user)

    badge_project_type = dmc.Badge(
        children=project_type.title(),
        color="orange" if project_type == "advanced" else "cyan",
        variant="light",
        style={"width": "100px", "justifyContent": "center"},
    )

    badge_visibility = dmc.Badge(
        children="Public" if is_public else "Private",
        color="green" if is_public else "violet",
        variant="filled",
        style={"width": "100px", "justifyContent": "center"},
    )

    badge_ownership = dmc.Badge(
        children=role,
        color=role_color,
        style={"width": "100px", "justifyContent": "center"},
    )

    return badge_project_type, badge_visibility, badge_ownership


def _create_project_accordion_items(
    project: Project, project_details: dmc.Paper, current_user: UserBase
) -> list[dmc.AccordionItem]:
    """Create accordion items for project sections.

    Args:
        project: Project model instance.
        project_details: Project details paper component.
        current_user: Current user.

    Returns:
        List of AccordionItem components.
    """
    project_type = getattr(project, "project_type", "basic")
    content_label = "Data Collections" if project_type == "basic" else "Workflows"
    content_icon = "mdi:database" if project_type == "basic" else "mdi:workflow"

    return [
        dmc.AccordionItem(
            value="project-details",
            children=[
                dmc.AccordionControl(
                    "Project Details",
                    icon=DashIconify(icon="mdi:information-outline", width=20),
                ),
                dmc.AccordionPanel(project_details),
            ],
        ),
        dmc.AccordionItem(
            value="project-content",
            children=[
                dmc.Anchor(
                    dmc.AccordionControl(
                        content_label,
                        icon=DashIconify(icon=content_icon, width=20),
                    ),
                    href=f"/project/{str(project.id)}/data",
                    style={"textDecoration": "none", "color": "inherit"},
                ),
            ],
        ),
        dmc.AccordionItem(
            value="roles-permissions",
            children=[
                dmc.Anchor(
                    dmc.AccordionControl(
                        "Roles and permissions",
                        icon=DashIconify(icon="mdi:shield-account", width=20),
                    ),
                    href=f"/project/{str(project.id)}/permissions",
                    style={"textDecoration": "none", "color": "inherit"},
                ),
            ],
        ),
        dmc.AccordionItem(
            value="project-management",
            children=[
                dmc.AccordionControl(
                    "Project Management",
                    icon=DashIconify(icon="mdi:cog", width=20),
                ),
                dmc.AccordionPanel(children=create_project_management_panel(project, current_user)),
            ],
        ),
    ]


def render_project_item(
    project: Project, current_user: UserBase, admin_UI: bool = False, token: str = ""
) -> dmc.AccordionItem:
    """Render a single project as an expandable accordion item.

    Displays project details, workflows/data collections, permissions link,
    and management controls. Shows badges for project type, visibility,
    and user's permission role.

    Args:
        project: Project model instance.
        current_user: Current user for permission display.
        admin_UI: Whether rendering in admin context (currently unused).
        token: JWT authentication token.

    Returns:
        AccordionItem component containing the full project view.
    """
    # Create project details
    project_details = _create_project_details_paper(project)

    # Create badges
    badge_project_type, badge_visibility, badge_ownership = _create_project_badges(
        project, current_user
    )

    # Create accordion items
    accordion_items = _create_project_accordion_items(project, project_details, current_user)

    return dmc.AccordionItem(
        children=[
            dmc.AccordionControl(
                dmc.Group(
                    [
                        badge_project_type,
                        badge_visibility,
                        badge_ownership,
                        dmc.Text(f"{project.name}", fw="bold", style={"flex": "1"}),
                    ],
                    gap="md",
                    style={"width": "100%", "alignItems": "center"},
                ),
            ),
            dmc.AccordionPanel(children=[dmc.Accordion(children=accordion_items)]),
        ],
        value=f"{project.name}",
    )


def render_projects_list(
    projects: list[Project], admin_UI: bool = False, token: str | None = None
) -> dmc.Container:
    """Render the complete projects list with column headers.

    Displays projects in an accordion with column headers for:
    Project Type, Visibility, Permission, and Project Name.
    Shows an empty state message if no projects exist.

    Args:
        projects: List of Project model instances.
        admin_UI: Whether rendering in admin context.
        token: JWT authentication token for fetching user info.

    Returns:
        Container component with projects accordion or empty state.
    """

    if not projects:
        content = dmc.Container(
            [
                dmc.Center(
                    dmc.Paper(
                        children=[
                            dmc.Stack(
                                children=[
                                    dmc.Center(
                                        DashIconify(
                                            icon="material-symbols:folder-off-outline",
                                            width=64,
                                            height=64,
                                            color="#6c757d",
                                        )
                                    ),
                                    dmc.Text(
                                        "No projects available",
                                        ta="center",
                                        fw="bold",
                                        size="xl",
                                    ),
                                    dmc.Text(
                                        "Create your first project to get started.",
                                        ta="center",
                                        c="gray",
                                        size="sm",
                                    ),
                                ],
                                align="center",
                                gap="sm",
                            )
                        ],
                        shadow="sm",
                        radius="md",
                        p="xl",
                        withBorder=True,
                        style={"width": "100%", "maxWidth": "500px"},
                    ),
                    style={"minHeight": "300px", "height": "auto"},
                ),
            ]
        )
        return content

    current_user = api_call_fetch_user_from_token(token)
    logger.info(f"Current user: {current_user}")

    def create_project_section(title, projects, current_user):
        if not projects:
            return None
        project_items = [
            render_project_item(
                project=project,
                current_user=current_user,
                admin_UI=admin_UI,
                token=token or "",
            )
            for project in projects
        ]
        return [
            # dmc.Title(title, order=2, style={"marginTop": "20px"}),
            dmc.Accordion(
                children=project_items,
                chevronPosition="right",
                className="mb-4",
                multiple=True,
                style={"height": "auto", "overflow": "visible"},
            ),
        ]

    sections = create_project_section("Projects:", projects, current_user)

    # Create column headers with fixed widths
    column_headers = dmc.Group(
        [
            dmc.Text(
                "Project Type",
                fw="bold",
                size="sm",
                c="gray",
                style={"width": "100px", "textAlign": "left"},
            ),
            dmc.Text(
                "Visibility",
                fw="bold",
                size="sm",
                c="gray",
                style={"width": "100px", "textAlign": "left"},
            ),
            dmc.Text(
                "Permission",
                fw="bold",
                size="sm",
                c="gray",
                style={"width": "100px", "textAlign": "left"},
            ),
            dmc.Text(
                "Project Name",
                fw="bold",
                size="sm",
                c="gray",
                style={"flex": "1", "textAlign": "left"},
            ),
        ],
        gap="md",
        style={
            "paddingLeft": "12px",
            "paddingRight": "12px",
            "paddingTop": "8px",
            "marginBottom": "10px",
        },
    )

    return dmc.Container(
        [
            column_headers,
        ]
        + (sections if sections else []),
        fluid=True,
        style={"height": "auto", "minHeight": "400px"},
    )


# =============================================================================
# Callback Registrations
# =============================================================================


def register_projects_callbacks(app) -> None:
    """Register callbacks for project creation modal and data collection tables.

    Callbacks registered:
    - toggle_project_modal: Open/close project creation modal
    - initialize_step_content: Load step 1 content when modal opens
    - manage_stepper_content: Handle stepper navigation
    - handle_project_card_click: Process project type selection
    - handle_project_creation: Create project via API
    - AG Grid theme switching and infinite scroll

    Args:
        app: Dash application instance.
    """

    # Project creation modal callbacks
    @app.callback(
        [
            Output("project-creation-modal", "opened"),
            Output("project-card-click-memory", "data", allow_duplicate=True),
            Output("project-creation-store", "data", allow_duplicate=True),
            Output("project-creation-stepper", "active", allow_duplicate=True),
            Output("url", "pathname", allow_duplicate=True),
        ],
        [
            Input("create-project-button", "n_clicks"),
        ],
        [
            dash.State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def toggle_project_modal(create_clicks, local_data):
        """Toggle the project creation modal and reset states."""
        if not create_clicks:
            return False, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        from depictio.models.models.users import UserContext

        ctx = dash.callback_context
        default_store = {
            "current_step": 0,
            "project_type": None,
            "project_name": "",
            "is_public": False,
            "data_collections": [],
        }
        default_memory = {"basic_clicks": 0}

        if not ctx.triggered:
            return False, default_memory, default_store, 0, dash.no_update

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if trigger_id == "create-project-button":
            # Check if user is anonymous and redirect to profile instead of opening modal
            if not local_data or not local_data.get("access_token"):
                logger.warning("No valid user data in project creation.")
                return False, default_memory, default_store, 0, "/profile"

            # Fetch user data using cached API call
            current_user_api = api_call_fetch_user_from_token(local_data["access_token"])
            if not current_user_api:
                logger.warning("User not found in project creation.")
                return False, default_memory, default_store, 0, "/profile"

            # Create UserContext from API response
            current_user = UserContext(
                id=str(current_user_api.id),
                email=current_user_api.email,
                is_admin=current_user_api.is_admin,
                is_anonymous=getattr(current_user_api, "is_anonymous", False),
            )
            # Also set temporary user status
            current_user.is_temporary = getattr(current_user_api, "is_temporary", False)

            if hasattr(current_user, "is_anonymous") and current_user.is_anonymous:
                logger.info(
                    "Anonymous user clicked 'Login to Create Projects' - redirecting to profile"
                )
                return (
                    False,  # Keep modal closed
                    default_memory,
                    default_store,
                    0,
                    "/profile",  # Redirect to profile page
                )

            # Reset memory, store, and stepper when opening modal (for authenticated users)
            return True, default_memory, default_store, 0, dash.no_update

        return False, default_memory, default_store, 0, dash.no_update

    # Initialize step content when modal opens
    @app.callback(
        Output("step-1-content", "children", allow_duplicate=True),
        Input("project-creation-modal", "opened"),
        prevent_initial_call=True,
    )
    def initialize_step_content(modal_opened):
        """Initialize step content when modal opens."""
        if modal_opened:
            return create_step_1_content()
        return ""

    # Step content management
    @app.callback(
        [
            Output("step-2-content", "children"),
            Output("project-creation-stepper", "active"),
            Output("project-stepper-prev", "disabled"),
            Output("project-stepper-next", "children"),
            Output("project-stepper-next", "disabled"),
            Output("project-creation-store", "data"),
            Output("project-card-click-memory", "data"),
        ],
        [
            Input("project-creation-store", "data"),
            Input("project-stepper-next", "n_clicks"),
            Input("project-stepper-prev", "n_clicks"),
        ],
        [
            State("project-creation-stepper", "active"),
            State("project-card-click-memory", "data"),
        ],
        prevent_initial_call=True,
    )
    def manage_stepper_content(
        store_data,
        next_clicks,
        prev_clicks,
        current_step,
        click_memory,
    ):
        """Manage stepper content and navigation."""
        ctx = dash.callback_context

        if not ctx.triggered:
            return "", 0, True, "Next", False, store_data, click_memory

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        # Initialize click memory if needed
        click_memory = click_memory or {"basic_clicks": 0}

        # Handle navigation
        project_type = store_data.get("project_type") if store_data else None
        max_steps = 1  # Only 2 steps total: Project Type (0) + Project Details (1)

        if trigger_id == "project-stepper-next":
            new_step = min(current_step + 1, max_steps)
        elif trigger_id == "project-stepper-prev":
            new_step = max(current_step - 1, 0)
        elif trigger_id == "project-creation-store":
            # Store data changed (e.g., project type selected), keep current step
            new_step = current_step
        else:
            new_step = current_step

        # Check if project is completed (stepper has moved beyond max_steps)
        project_completed = new_step > max_steps

        # Determine next button text
        next_text = "Create Project" if new_step == max_steps else "Next"
        next_disabled = project_completed  # Disable when project is completed

        # Always provide step 2 content when project type is available
        step_2_content = create_step_2_content(project_type) if project_type else ""

        return (
            step_2_content,
            new_step,
            new_step == 0 or project_completed,  # Previous disabled on first step OR when completed
            next_text,
            next_disabled,
            store_data,
            click_memory,
        )

    # Handle project type card clicks
    @app.callback(
        [
            Output("project-creation-store", "data", allow_duplicate=True),
            Output("project-creation-stepper", "active", allow_duplicate=True),
            Output("project-card-click-memory", "data", allow_duplicate=True),
            Output("step-2-content", "children", allow_duplicate=True),
        ],
        Input("basic-project-card", "n_clicks"),
        [
            State("project-creation-store", "data"),
            State("project-card-click-memory", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_project_card_click(basic_clicks, store_data, click_memory):
        """Handle project type card clicks."""
        if not basic_clicks:
            raise dash.exceptions.PreventUpdate

        click_memory = click_memory or {"basic_clicks": 0}

        # Check if this is a NEW click by comparing with stored click count
        if basic_clicks > click_memory.get("basic_clicks", 0):
            project_type = "basic"
            store_data = store_data or {}
            store_data["project_type"] = project_type

            # Update click memory to current click count
            click_memory["basic_clicks"] = basic_clicks

            # Create step 2 content immediately
            step_2_content = create_step_2_content(project_type)

            # Automatically advance to step 2 (step 1 in 0-indexed)
            return store_data, 1, click_memory, step_2_content

        raise dash.exceptions.PreventUpdate

    # Handle project creation
    @app.callback(
        [
            Output("project-creation-stepper", "active", allow_duplicate=True),
            Output("project-creation-store", "data", allow_duplicate=True),
        ],
        [
            Input("project-stepper-next", "n_clicks"),
        ],
        [
            State("project-creation-stepper", "active"),
            State("project-creation-store", "data"),
            State("project-name-input", "value"),
            State("project-description-input", "value"),
            State("project-public-switch", "checked"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_project_creation(
        next_clicks,
        current_step,
        store_data,
        project_name,
        project_description,
        is_public,
        local_data,
    ):
        """Handle project creation when Create Project button is clicked."""
        if not next_clicks or not store_data:
            raise dash.exceptions.PreventUpdate

        # Only create project when on the final step (step 1) and button says "Create Project"
        if current_step != 1:
            raise dash.exceptions.PreventUpdate

        try:
            # Validate inputs
            if not project_name or not project_name.strip():
                logger.error("Project name is required")
                # TODO: Add user feedback for validation errors
                raise dash.exceptions.PreventUpdate

            # Get current user info
            token = local_data.get("access_token") if local_data else None
            if not token:
                logger.error("No authentication token available")
                raise dash.exceptions.PreventUpdate

            # Get user information to set as owner
            current_user_info = api_call_fetch_user_from_token(token)
            if not current_user_info:
                logger.error("Could not fetch current user information")
                raise dash.exceptions.PreventUpdate

            # Create user object for permissions - include all user attributes
            current_user = UserBase(
                id=current_user_info.id,
                email=current_user_info.email,
                is_admin=getattr(current_user_info, "is_admin", False),
                is_anonymous=getattr(current_user_info, "is_anonymous", False),
                is_temporary=getattr(current_user_info, "is_temporary", False),
                expiration_time=getattr(current_user_info, "expiration_time", None),
            )

            # Create permissions with current user as owner
            permissions = Permission(
                owners=[current_user],
                editors=[],
                viewers=[],  # Public projects visible to all
            )

            # Create project data
            project_data = {
                "name": project_name.strip(),
                "description": project_description.strip() if project_description else None,
                "project_type": store_data.get("project_type", "basic"),
                "is_public": bool(is_public),
                "permissions": permissions,
                "workflows": [],
                "data_collections": [],
                "data_management_platform_project_url": None,
                "yaml_config_path": None,
            }

            # Validate project data by creating Project object first
            try:
                project = Project(**project_data)  # type: ignore[misc]
                logger.debug(f"Project validation successful: {project.name}")
            except Exception as validation_error:
                logger.error(f"Project validation failed: {validation_error}")
                store_data["creation_error"] = f"Invalid project data: {validation_error}"
                raise dash.exceptions.PreventUpdate

            # Call API to create project using validated data
            result = api_call_create_project(project.model_dump(), token)

            if result and result.get("success"):
                logger.debug(f"Project created successfully: {result.get('message')}")
                # Move to completion step
                store_data["project_created"] = True
                store_data["creation_message"] = result.get(
                    "message", "Project created successfully!"
                )
                return current_step + 1, store_data
            else:
                error_msg = (
                    result.get("message", "Unknown error") if result else "Failed to create project"
                )
                logger.error(f"Project creation failed: {error_msg}")
                # TODO: Add user feedback for creation errors
                store_data["creation_error"] = error_msg
                raise dash.exceptions.PreventUpdate

        except Exception as e:
            logger.error(f"Error in project creation: {e}")
            # TODO: Add user feedback for errors
            raise dash.exceptions.PreventUpdate

    # PHASE 2C: Converted to clientside callback for better performance
    app.clientside_callback(
        """
        function(themeData) {
            const theme = themeData || 'light';
            return theme === 'dark' ? 'ag-theme-alpine-dark' : 'ag-theme-alpine';
        }
        """,
        Output({"type": "project-dc-table", "index": MATCH}, "className"),
        Input("theme-store", "data"),
        prevent_initial_call=False,
    )

    @app.callback(
        Output({"type": "project-dc-table", "index": MATCH}, "getRowsResponse"),
        Input({"type": "project-dc-table", "index": MATCH}, "getRowsRequest"),
        State({"type": "project-dc-table", "index": MATCH}, "id"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def infinite_scroll_project_dc_table(request, id, local_store):
        """Handle infinite scrolling for data collection tables."""
        # Split the index to get workflow_id and data_collection_id
        try:
            workflow_id, data_collection_id = id["index"].split("/")
        except ValueError:
            logger.error(f"Invalid ID format: {id['index']}")
            return dash.no_update

        logger.info(f"Workflow ID: {workflow_id}, Data Collection ID: {data_collection_id}")

        if request is None:
            return dash.no_update

        if local_store is None:
            logger.error("Local store is None.")
            raise dash.exceptions.PreventUpdate

        TOKEN = local_store.get("access_token")
        if not TOKEN:
            logger.error("No access token found in local store.")
            return dash.no_update

        # Fetch data collection specs and convert to DataCollection model
        try:
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{data_collection_id}",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            response.raise_for_status()
            dc_specs_dict = response.json()

            # Create DataCollection model from the response
            from depictio.models.models.data_collections import DataCollection

            dc_specs = DataCollection.from_mongo(dc_specs_dict)

        except httpx.HTTPError as e:
            logger.error(f"Error fetching data collection specs: {e}")
            return dash.no_update
        except Exception as e:
            logger.error(f"Error converting data collection specs to model: {e}")
            return dash.no_update

        if dc_specs.config.type.lower() == "table":
            df = load_deltatable_lite(workflow_id, data_collection_id, TOKEN=TOKEN)
            logger.info(f"df shape: {df.shape} for {workflow_id}/{data_collection_id}")

            # Handle row slicing for pagination
            start_row = request.get("startRow", 0)
            end_row = request.get("endRow", df.shape[0])
            partial = df[start_row:end_row]

            return {"rowData": partial.to_dicts(), "rowCount": df.shape[0]}
        else:
            return dash.no_update


def register_workflows_callbacks(app) -> None:
    """Register callbacks for project list display and management.

    Callbacks registered:
    - update_projects_content: Render projects list on page load
    - refresh_projects_after_creation: Refresh list after new project
    - open_edit_project_name_modal: Show edit modal
    - open_delete_project_modal: Show delete confirmation modal
    - handle_delete_project_confirm: Process project deletion
    - handle_edit_project_name_confirm: Process project rename
    - refresh_projects_after_deletion/edit: Update list after changes

    Args:
        app: Dash application instance.
    """

    @app.callback(
        Output("projects-content", "children"),
        [
            Input("url", "pathname"),
            Input("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_projects_content(pathname, local_store):
        """Update the projects list based on the current path and user token."""
        token = local_store.get("access_token") if local_store else None
        if not token:
            logger.error("No access token found in local store.")
            return html.P("Authentication required.")

        # Fetch projects from the API
        projects = fetch_projects(token)
        logger.info(f"Fetched projects: {len(projects)}")

        return render_projects_list(projects=projects, admin_UI=False, token=token)

    # Auto-refresh projects list after project creation only
    @app.callback(
        Output("projects-content", "children", allow_duplicate=True),
        Input("project-creation-modal", "opened"),
        [
            State("local-store", "data"),
            State("project-creation-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def refresh_projects_after_creation(creation_modal_opened, local_store, project_store):
        """Refresh projects list after successful project creation."""
        # Handle project creation (modal closing after creation)
        if not creation_modal_opened and project_store and project_store.get("project_created"):
            token = local_store.get("access_token") if local_store else None
            if not token:
                return dash.no_update
            projects = fetch_projects(token)
            logger.info(f"Refreshed {len(projects)} projects after creation")
            return render_projects_list(projects=projects, admin_UI=False, token=token)
        return dash.no_update

    # Removed URL-based modal close callback to prevent flashing during page navigation
    # The modal should only open/close based on user actions, not URL changes

    # Project management callbacks
    @app.callback(
        Output({"type": "edit-project-name-add-confirmation-modal", "index": MATCH}, "opened"),
        Input({"type": "edit-project-name-button", "index": MATCH}, "n_clicks"),
        prevent_initial_call=True,
    )
    def open_edit_project_name_modal(n_clicks):
        """Open the edit project name modal when button is clicked."""
        if n_clicks:
            return True
        return dash.no_update

    @app.callback(
        Output({"type": "delete-project-delete-confirmation-modal", "index": MATCH}, "opened"),
        Input({"type": "delete-project-button", "index": MATCH}, "n_clicks"),
        prevent_initial_call=True,
    )
    def open_delete_project_modal(n_clicks):
        """Open the delete project confirmation modal when button is clicked."""
        if n_clicks:
            return True
        return dash.no_update

    # Handle edit project name with API integration - using dynamic callback registration
    # This needs to be handled differently due to unique button IDs per project

    # Handle delete project - close modal only
    @app.callback(
        Output(
            {"type": "delete-project-delete-confirmation-modal", "index": MATCH},
            "opened",
            allow_duplicate=True,
        ),
        Input({"type": "confirm-delete-project-delete-button", "index": MATCH}, "n_clicks"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def handle_delete_project_confirm(confirm_clicks, local_store):
        """Handle project deletion confirmation with API call."""
        ctx = dash.callback_context
        if not ctx.triggered:
            return dash.no_update

        button_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if "confirm" in button_id:
            # Get the project index from the button ID
            import json

            button_dict = json.loads(button_id)
            project_id = button_dict["index"]

            token = local_store.get("access_token") if local_store else None
            if not token:
                return False

            # Call API to delete project
            result = api_call_delete_project(project_id, token)

            if result and result.get("success"):
                logger.info(f"Project {project_id} deleted successfully")
                return False
            else:
                logger.error(f"Failed to delete project: {result}")

            return False

        return dash.no_update

    # Refresh projects list after successful deletion - delayed trigger
    @app.callback(
        Output("projects-content", "children", allow_duplicate=True),
        Input({"type": "delete-project-delete-confirmation-modal", "index": ALL}, "opened"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def refresh_projects_after_deletion(modal_states, local_store):
        """Refresh projects list when delete modal closes after successful deletion."""
        import time

        ctx = dash.callback_context
        if not ctx.triggered:
            return dash.no_update

        # Check if any modal is closing (going from True to False)
        if modal_states and not any(modal_states):
            token = local_store.get("access_token") if local_store else None
            if not token:
                return dash.no_update
            # Small delay to ensure API call completed
            time.sleep(0.1)
            # Fetch updated projects from the API
            projects = fetch_projects(token)
            logger.info(f"Refreshed {len(projects)} projects after deletion")
            return render_projects_list(projects=projects, admin_UI=False, token=token)
        return dash.no_update

    # Handle edit project name confirmation with API integration - close modal only
    @app.callback(
        Output(
            {"type": "edit-project-name-add-confirmation-modal", "index": MATCH},
            "opened",
            allow_duplicate=True,
        ),
        Input({"type": "confirm-edit-project-name-add-button", "index": MATCH}, "n_clicks"),
        [
            State({"type": "edit-project-name-input", "index": MATCH}, "value"),
            State("local-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_edit_project_name_confirm(confirm_clicks, new_name, local_store):
        """Handle project name edit confirmation with API call."""
        ctx = dash.callback_context
        if not ctx.triggered:
            return dash.no_update

        button_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if "confirm" in button_id:
            # Get the project index from the button ID
            import json

            button_dict = json.loads(button_id)
            project_id = button_dict["index"]

            token = local_store.get("access_token") if local_store else None
            if not token or not new_name:
                return False

            # First fetch the complete project data
            from depictio.dash.api_calls import api_call_fetch_project_by_id

            current_project_data = api_call_fetch_project_by_id(project_id, token)

            if not current_project_data:
                logger.error(f"Could not fetch project data for {project_id}")
                return False

            # Update only the name field in the complete project data
            current_project_data["name"] = new_name.strip()

            # Call API to update project with complete data
            result = api_call_update_project(current_project_data, token)

            if result and result.get("success"):
                logger.debug(f"Project {project_id} updated successfully with name: {new_name}")
                return False
            else:
                logger.error(f"Failed to update project: {result}")

            return False

        return dash.no_update

    # Refresh projects list after successful edit - separate callback
    @app.callback(
        Output("projects-content", "children", allow_duplicate=True),
        Input({"type": "edit-project-name-add-confirmation-modal", "index": ALL}, "opened"),
        [
            State("local-store", "data"),
            State({"type": "confirm-edit-project-name-add-button", "index": ALL}, "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def refresh_projects_after_edit(modal_states, local_store, button_clicks):
        """Refresh projects list when edit modal closes after successful edit."""
        ctx = dash.callback_context
        if not ctx.triggered:
            return dash.no_update

        # Check if any modal is closing (going from True to False) and has actual button clicks (not None)
        has_real_clicks = button_clicks and any(
            click is not None and click > 0 for click in button_clicks
        )
        if modal_states and not any(modal_states) and has_real_clicks:
            token = local_store.get("access_token") if local_store else None
            if not token:
                return dash.no_update
            # Fetch updated projects from the API
            projects = fetch_projects(token)
            logger.info(f"Refreshed {len(projects)} projects after edit")
            return render_projects_list(projects=projects, admin_UI=False, token=token)
        return dash.no_update

    # Add hover effects using clientside callback
    # app.clientside_callback(
    #     """
    #     function() {
    #         setTimeout(function() {
    #             // Only add hover effects to enabled cards (not disabled ones)
    #             const cards = document.querySelectorAll('.project-type-card-wrapper');
    #             cards.forEach(function(card) {
    #                 // Skip disabled cards
    #                 if (card.classList.contains('project-type-card-wrapper-disabled')) {
    #                     return;
    #                 }

    #                 card.addEventListener('mouseenter', function() {
    #                     const cardElement = this.querySelector('.project-type-card');
    #                     if (cardElement) {
    #                         cardElement.style.boxShadow = '0 0 0 2px var(--mantine-color-blue-5, #339af0)';
    #                     }
    #                 });
    #                 card.addEventListener('mouseleave', function() {
    #                     const cardElement = this.querySelector('.project-type-card');
    #                     if (cardElement) {
    #                         cardElement.style.boxShadow = '';
    #                     }
    #                 });
    #             });
    #         }, 500);
    #         return window.dash_clientside.no_update;
    #     }
    #     """,
    #     Output("dummy-hover-output", "children"),
    #     Input("project-creation-modal", "opened"),
    # )

    # # Refresh projects list when modal closes after successful project creation
    # app.clientside_callback(
    #     """
    #     function(modal_opened, store_data) {
    #         // If modal is closing and a project was created, refresh the page
    #         if (!modal_opened && store_data && store_data.project_created) {
    #             // Small delay to ensure modal close animation completes
    #             setTimeout(function() {
    #                 if (window.location.pathname === '/projects') {
    #                     window.location.reload();
    #                 }
    #             }, 300);
    #         }
    #         return window.dash_clientside.no_update;
    #     }
    #     """,
    #     Output("dummy-hover-output", "children", allow_duplicate=True),
    #     [Input("project-creation-modal", "opened"), Input("project-creation-store", "data")],
    #     prevent_initial_call=True,
    # )
