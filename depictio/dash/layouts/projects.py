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

# from depictio.api.v1.endpoints.user_endpoints.models import UserBase
from depictio.dash.api_calls import (
    api_call_create_project,
    api_call_delete_project,
    api_call_fetch_user_from_token,
    api_call_update_project,
)
from depictio.dash.colors import colors  # Import Depictio color palette
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.projects import Project
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import Workflow

# =========================
# Module Level Components (defined after functions)
# =========================

# =========================
# Data Fetching Functions
# =========================


@validate_call
def fetch_projects(token: str) -> list[Project]:
    """
    Fetch all projects for the current user.
    """
    url = f"{API_BASE_URL}/depictio/api/v1/projects/get/all"

    headers = {"Authorization": f"Bearer {token}"}
    response = httpx.get(url, headers=headers)

    # Handle error responses
    if response.status_code != 200:
        logger.warning(f"Failed to fetch projects: HTTP {response.status_code}")
        return []

    try:
        projects_data = response.json()
        if not isinstance(projects_data, list):
            logger.error(f"Expected list of projects, got {type(projects_data)}")
            return []

        logger.debug(f"Fetched {len(projects_data)} projects from API.")
        projects = [Project.from_mongo(project) for project in projects_data]
        return projects
    except Exception as e:
        logger.error(f"Error processing projects data: {e}")
        return []


# =====================
# Helper Functions
# =====================


# def categorize_projects(projects: List[Project], current_user):
#     """Categorize projects into owned and shared/accessed."""
#     owned = []
#     shared = []

#     for project in projects:
#         # Get owner IDs from the Project model
#         owners_ids = [str(o.id) for o in project.permissions.owners]
#         if str(current_user.id) in owners_ids:
#             owned.append(project)
#         elif (
#             str(current_user.id) in project.permissions.viewers
#             or "*" in project.permissions.viewers
#         ):
#             shared.append(project)

#     return owned, shared


# def categorize_workflows(workflows, current_user):
#     """Categorize workflows into owned and shared/accessed."""
#     owned = []
#     shared = []

#     for wf in workflows:
#         owners_ids = [str(o["_id"]) for o in wf["permissions"]["owners"]]
#         if str(current_user.id) in owners_ids:
#             owned.append(wf)
#         elif (
#             str(current_user.id) in wf["permissions"]["viewers"]
#             or "*" in wf["permissions"]["viewers"]
#         ):
#             shared.append(wf)

#     return owned, shared


# =====================
# Modal Components
# =====================


def create_project_modal(opened=False):
    """
    Creates a stylish modal for project creation with DMC Stepper.

    Returns:
    - modal: The project creation modal
    - modal_id: The ID of the modal for callbacks
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
logger.info("Creating project modal with opened=False")
project_modal, project_modal_id = create_project_modal(opened=False)
logger.info(f"Project modal created with ID: {project_modal_id}")

# Create the main layout with modal included
layout = html.Div(
    [
        project_modal,
        html.Div(id="projects-content"),  # Content populated by callback
    ]
)


def create_step_1_content():
    """Create Step 1: Project Type Selection."""
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


def create_step_2_content(project_type=None):
    """Create Step 2: Project Details."""
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


def create_step_3_content():
    """Create Step 3: Data Collections (Basic projects only)."""
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


# =====================
# Rendering Components
# =====================


def return_deltatable_for_view(workflow_id: str, dc: DataCollection, token: str):
    """
    Return a DeltaTable component for viewing data collections.
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


def render_data_collection(dc: DataCollection, workflow_id: str, token: str):
    """
    Render a single data collection item.

    Args:
        dc: DataCollection model
        workflow_id: ID of the workflow
        token: Authentication token for the API

    Returns:
        Dash Mantine Paper component
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


def render_workflow_item(wf: Workflow, token: str):
    """
    Render a single workflow item.

    Args:
        wf: Workflow object
        token: Authentication token for the API

    Returns:
        Dash Mantine AccordionItem component
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
    """
    Create the project management panel with edit and delete buttons and their modals.

    Args:
        project: Project object
        current_user: Current user object for permission checking

    Returns:
        List of components for the management panel including modals
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


def render_project_item(
    project: Project, current_user: UserBase, admin_UI: bool = False, token: str = ""
):
    """
    Render a single project item containing multiple workflows.

    Args:
        project: Project object
        current_user: Current user object
        token: Authentication token for the API

    Returns:
        Dash Mantine AccordionItem component
    """
    # logger.info(f"Rendering project item: {project}")
    project_details = dmc.Paper(
        children=[
            html.Div(
                children=[
                    dmc.Group(
                        children=[
                            dmc.Text("Name:", fw="bold", className="label-text"),
                            dmc.Text(project.name, fw="normal"),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Database ID:", fw="bold", className="label-text"),
                            dmc.Text(str(project.id), fw="normal"),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Description:", fw="bold", className="label-text"),
                            dmc.Text(
                                (project.description if project.description else "Not defined"),
                                fw="normal",
                            ),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text(
                                "Data Management Platform URL:",
                                fw="bold",
                                className="label-text",
                            ),
                            (
                                dmc.Anchor(
                                    project.data_management_platform_project_url,
                                    href=project.data_management_platform_project_url,
                                    target="_blank",
                                    fw="normal",
                                )
                                if project.data_management_platform_project_url
                                else dmc.Text(
                                    "Not defined",
                                    fw="normal",
                                )
                            ),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Created at:", fw="bold", className="label-text"),
                            dmc.Text(project.registration_time, fw="normal"),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Owners:", fw="bold", className="label-text"),
                            dmc.Text(
                                str(
                                    " ; ".join(
                                        [f"{o.email} - {o.id}" for o in project.permissions.owners]
                                    )
                                ),
                                fw="normal",
                            ),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Editors:", fw="bold", className="label-text"),
                            dmc.Text(
                                (
                                    str(
                                        " ; ".join(
                                            [
                                                f"{o.email} - {o.id}"
                                                for o in project.permissions.editors
                                            ]
                                        )
                                    )
                                    if project.permissions.editors
                                    else "None"
                                ),
                                fw="normal",
                            ),
                        ],
                        gap="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Viewers:", fw="bold", className="label-text"),
                            dmc.Text(
                                (
                                    str(
                                        " ; ".join(
                                            [
                                                f"{o.email} - {o.id}"
                                                for o in project.permissions.viewers
                                            ]
                                        )
                                    )
                                    if project.permissions.viewers
                                    else "None"
                                ),
                                fw="normal",
                            ),
                        ],
                        gap="xs",
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
                                getattr(project, "project_type", "basic").title(),
                                color="orange"
                                if getattr(project, "project_type", "basic") == "advanced"
                                else "cyan",
                                variant="light",
                                radius="xl",
                                size="xs",
                                style={"width": "100px", "justifyContent": "center"},
                            ),
                        ],
                        gap="xs",
                    ),
                ],
                className="project-details p-3",
            ),
        ],
        radius="md",
        withBorder=True,
        shadow="sm",
        p="md",
    )

    def create_workflow_section(title, workflows: list[Workflow]):
        if not workflows:
            return None
        workflow_items = [render_workflow_item(wf=wf, token=token) for wf in workflows]
        return [
            dmc.Title(title, order=4, style={"marginTop": "10px"}),
            dmc.Accordion(
                children=workflow_items,
                chevronPosition="right",
                className="mb-3",
            ),
        ]

    def create_data_collections_section(title, data_collections: list[DataCollection]):
        if not data_collections:
            return None
        dc_items = [
            render_data_collection(dc=dc, workflow_id="", token=token) for dc in data_collections
        ]
        return [
            dmc.Title(title, order=4, style={"marginTop": "10px"}),
            dmc.Stack(dc_items, gap="sm"),
        ]

    # For basic projects, show data collections directly; for advanced projects, show workflows
    project_type = getattr(project, "project_type", "advanced")
    if project_type == "basic":
        # For basic projects, show data collections directly; for advanced projects, show workflows
        # Note: sections are now handled by the new data collections route
        pass

    # Determine user's role in the project
    role = "Viewer"  # Default role
    color = "gray"  # Default color

    if str(current_user.id) in [str(o.id) for o in project.permissions.owners]:
        role = "Owner"
        color = "blue"
    elif hasattr(project.permissions, "editors") and str(current_user.id) in [
        str(e.id) for e in project.permissions.editors
    ]:
        role = "Editor"
        color = "teal"
    elif str(current_user.id) in [
        str(v.id) for v in project.permissions.viewers if hasattr(v, "id")
    ]:
        role = "Viewer"
        color = "gray"

    badge_ownership = dmc.Badge(
        children=role,
        color=color,
        style={"width": "100px", "justifyContent": "center"},
    )

    # Create project type badge
    project_type = getattr(
        project, "project_type", "basic"
    )  # Default to 'basic' for backward compatibility
    badge_project_type = dmc.Badge(
        children=project_type.title(),
        color="orange" if project_type == "advanced" else "cyan",
        variant="light",
        style={"width": "100px", "justifyContent": "center"},
    )

    # Create visibility badge
    is_public = getattr(project, "is_public", False)  # Default to private if not set
    badge_visibility = dmc.Badge(
        children="Public" if is_public else "Private",
        color="green" if is_public else "violet",
        variant="filled",
        style={"width": "100px", "justifyContent": "center"},
    )

    return dmc.AccordionItem(
        children=[
            dmc.AccordionControl(
                dmc.Group(
                    [
                        badge_project_type,
                        badge_visibility,
                        badge_ownership,
                        dmc.Text(f"{project.name}", fw="bold", style={"flex": "1"}),
                        # dmc.Text(f" ({str(project.id)})", fw="medium"),
                    ],
                    gap="md",
                    style={"width": "100%", "alignItems": "center"},
                ),
            ),
            dmc.AccordionPanel(
                children=[
                    dmc.Accordion(
                        children=[
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
                                            "Data Collections"
                                            if project_type == "basic"
                                            else "Workflows",
                                            icon=DashIconify(
                                                icon="mdi:database"
                                                if project_type == "basic"
                                                else "mdi:workflow",
                                                width=20,
                                            ),
                                        ),
                                        href=f"/project/{str(project.id)}/data",
                                        style={"textDecoration": "none", "color": "inherit"},
                                    ),
                                    # dmc.AccordionPanel(
                                    #     children=(
                                    #         sections
                                    #         if sections
                                    #         else [
                                    #             html.P(
                                    #                 "No data collections available."
                                    #                 if project_type == "basic"
                                    #                 else "No workflows available."
                                    #             )
                                    #         ]
                                    #     )
                                    # ),
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
                                    # dmc.AccordionPanel(
                                    #     children=[
                                    #         dmc.Accordion(
                                    #             children=[
                                    #                 dag.AgGrid(
                                    #                     columnDefs=[
                                    #                         # set types
                                    #                         {"field": "id"},
                                    #                         {"field": "email"},
                                    #                         {
                                    #                             "field": "Owner",
                                    #                             "cellRenderer": "agCheckboxCellRenderer",
                                    #                         },
                                    #                         {"field": "Editor"},
                                    #                         {"field": "Viewer"},
                                    #                     ],
                                    #                     rowData=[
                                    #                         {
                                    #                             "id": str(user.id),
                                    #                             "email": user.email,
                                    #                             "Owner": True,
                                    #                             "Editor": False,
                                    #                             "Viewer": False,
                                    #                         }
                                    #                         for user in project.permissions.viewers
                                    #                         + project.permissions.owners
                                    #                     ],
                                    #                     defaultColDef={
                                    #                         "resizable": True,
                                    #                         "sortable": True,
                                    #                         "filter": True,
                                    #                     },
                                    #                 )
                                    #             ]
                                    #         )
                                    #     ]
                                    # ),
                                ],
                            ),
                            dmc.AccordionItem(
                                value="project-management",
                                children=[
                                    dmc.AccordionControl(
                                        "Project Management",
                                        icon=DashIconify(icon="mdi:cog", width=20),
                                    ),
                                    dmc.AccordionPanel(
                                        # children=html.Div()
                                        children=create_project_management_panel(
                                            project, current_user
                                        )
                                    ),
                                ],
                            ),
                        ],
                    ),
                ]
            ),
        ],
        value=f"{project.name}",
    )


def render_projects_list(projects: list[Project], admin_UI: bool = False, token: str | None = None):
    """Render the full projects list, categorized into owned and shared."""

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


# =====================
# Callback Registrations
# =====================


def register_projects_callbacks(app):
    """
    Register callbacks related to projects and data collections.

    Args:
        app: Dash application instance
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
                logger.info(f"Project created successfully: {result.get('message')}")
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


def register_workflows_callbacks(app):
    """
    Register callbacks related to projects and workflows.

    Args:
        app: Dash application instance
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
                logger.info(f"Project {project_id} updated successfully with name: {new_name}")
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
