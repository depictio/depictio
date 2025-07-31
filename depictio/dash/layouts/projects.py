import dash
import dash_ag_grid as dag
import dash_mantine_components as dmc
import httpx
import yaml
from bson import ObjectId
from dash import MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify
from pydantic import validate_call

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite

# from depictio.api.v1.endpoints.user_endpoints.models import UserBase
from depictio.dash.api_calls import api_call_fetch_user_from_token
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.projects import Project
from depictio.models.models.users import UserBase
from depictio.models.models.workflows import Workflow

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
    projects = httpx.get(url, headers=headers)
    # logger.info(f"Response status code: {projects.status_code}")
    # logger.info(f"Response content: {projects.content}")
    # logger.info(f"Response headers: {projects.headers}")
    # logger.info(f"Response JSON: {projects.json()}")
    # logger.info("Successfully fetched projects.")
    # logger.info(f"Projects: {projects.json()}")

    projects = [Project.from_mongo(project) for project in projects.json()]
    return projects


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
        limit_rows=100,
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
    preview_panel = dmc.AccordionPanel(dmc.Paper(grid))
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
    icon = "mdi:table" if dc.config.type.lower() == "table" else "mdi:file-document"
    dc_config = yaml.dump(dc.config.model_dump(), default_flow_style=False)
    dc_config_md = f"```yaml\n{dc_config}\n```"

    # Preview Section for Tables
    # if dc.config.type.lower() == "table":
    #     # preview_panel, preview_control = return_deltatable_for_view(
    #     #     workflow_id, dc, token
    #     # )

    # else:
    preview_panel = None
    preview_control = None

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
                                icon=DashIconify(icon=icon, width=20),
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
                                                                className="p-3",
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
        className="p-3",
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
        className="p-3",
    )

    # Render data collections if they exist
    if hasattr(wf, "data_collections") and wf.data_collections:
        data_collections = [
            render_data_collection(dc, str(wf.id), token) for dc in wf.data_collections
        ]
        data_collections_section = dmc.Paper(
            children=data_collections,
            className="p-3",
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
    logger.info(f"Rendering project item: {project}")
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
        # className="p-3",
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

    sections = create_workflow_section("Workflows:", project.workflows)

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
        style={"width": "80px", "justifyContent": "center"},
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

    return dmc.AccordionItem(
        children=[
            dmc.AccordionControl(
                dmc.Group(
                    [
                        badge_ownership,
                        badge_project_type,
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
                                value="project-workflows",
                                children=[
                                    dmc.AccordionControl(
                                        "Workflows",
                                        icon=DashIconify(icon="mdi:workflow", width=20),
                                    ),
                                    dmc.AccordionPanel(
                                        children=(
                                            sections
                                            if sections
                                            else [html.P("No workflows available.")]
                                        )
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
                                        href=f"/project/{str(project.id)}",
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
                        ],
                        multiple=True,
                    ),
                ]
            ),
        ],
        value=f"{project.name}",
    )


def render_projects_list(projects: list[Project], admin_UI: bool = False, token: str | None = None):
    """Render the full projects list, categorized into owned and shared."""
    if not projects:
        content = dmc.Center(
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
                                "Projects created by users will appear here.",
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
                "Ownership",
                fw="bold",
                size="sm",
                c="gray",
                style={"width": "80px", "textAlign": "left"},
            ),
            dmc.Text(
                "Project Type",
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
        children=[column_headers] + (sections if sections else []),
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

    @app.callback(
        Output({"type": "project-dc-table", "index": MATCH}, "className"),
        Input("theme-store", "data"),
        prevent_initial_call=False,
    )
    def update_project_dc_table_theme(theme_data):
        """Update AG Grid theme class based on current theme."""
        theme = theme_data or "light"
        if theme == "dark":
            return "ag-theme-alpine-dark"
        else:
            return "ag-theme-alpine"

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
        Output("projects-list", "children"),
        Input("url", "pathname"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def update_projects_list(pathname, local_store):
        """Update the projects list based on the current path and user token."""
        token = local_store.get("access_token") if local_store else None
        if not token:
            logger.error("No access token found in local store.")
            return html.P("Authentication required.")

        # Fetch projects from the API
        projects = fetch_projects(token)
        logger.info(f"Fetched projects: {projects}")

        # Temporarily hardcode the current project to "Strand-Seq"
        # Remove or modify this filter when dynamic project selection is implemented
        # projects = [project for project in projects if project.get("name") == "Strand-Seq"]

        if not projects:
            logger.info("No projects matched the hardcoded filter.")
            content = dmc.Center(
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
                                    "Projects created by users will appear here.",
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
            )
            return content

        return html.Div(
            children=[
                render_projects_list(projects=projects, admin_UI=False, token=token),
            ]
        )
