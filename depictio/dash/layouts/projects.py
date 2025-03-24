from typing import List
from bson import ObjectId
import dash_mantine_components as dmc
import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State, MATCH, ALL
import httpx
from dash_iconify import DashIconify
import yaml
import dash_ag_grid as dag
import polars as pl
from pydantic import validate_call

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.api.v1.endpoints.user_endpoints.core_functions import (
    fetch_user_from_token,
)
from depictio.api.v1.configs.logging import logger

# from depictio.api.v1.endpoints.user_endpoints.models import UserBase
from depictio.dash.utils import return_mongoid

from depictio_models.models.users import UserBase
from depictio_models.models.projects import Project
from depictio_models.models.workflows import Workflow
from depictio_models.models.data_collections import DataCollection


# =========================
# Data Fetching Functions
# =========================


@validate_call
def fetch_projects(token: str) -> List[Project]:
    """
    Fetch all projects for the current user.
    """
    url = f"{API_BASE_URL}/depictio/api/v1/projects/get/all"

    headers = {"Authorization": f"Bearer {token}"}
    projects = httpx.get(url, headers=headers)
    logger.info("Successfully fetched projects.")
    logger.info(f"Projects: {projects.json()}")

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
        workflow_id=workflow_id,
        data_collection_id=str(dc.id),
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
    )
    preview_panel = dmc.AccordionPanel(dmc.Paper(grid))
    preview_control = dmc.AccordionControl(
        dmc.Text("Preview", weight=700, className="label-text"),
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

    badge_type_metatype = dmc.Badge(
        children="Metadata"
        if dc.config.metatype.lower() == "metadata"
        else "Aggregate",
        color="blue" if dc.config.metatype.lower() == "metadata" else "black",
        className="ml-2",
        style={"display": "inline-block"}
        if dc.config.metatype.lower() == "metadata"
        else {"display": "none"},
    )

    return dmc.Paper(
        children=[
            dmc.AccordionMultiple(
                children=[
                    dmc.Accordion(
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
                                                                weight=700,
                                                                className="label-text",
                                                            ),
                                                            dmc.Text(
                                                                str(dc.id), weight=500
                                                            ),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                    dmc.Group(
                                                        children=[
                                                            dmc.Text(
                                                                "Tag:",
                                                                weight=700,
                                                                className="label-text",
                                                            ),
                                                            dmc.Text(
                                                                dc.data_collection_tag,
                                                                weight=500,
                                                            ),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                    dmc.Group(
                                                        children=[
                                                            dmc.Text(
                                                                "Description:",
                                                                weight=700,
                                                                className="label-text",
                                                            ),
                                                            dmc.Text(
                                                                dc.description
                                                                if hasattr(
                                                                    dc, "description"
                                                                )
                                                                else "",
                                                                weight=500,
                                                            ),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                    dmc.Group(
                                                        children=[
                                                            dmc.Text(
                                                                "Type:",
                                                                weight=700,
                                                                className="label-text",
                                                            ),
                                                            dmc.Text(
                                                                dc.config.type,
                                                                weight=500,
                                                            ),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                    dmc.Group(
                                                        children=[
                                                            dmc.Text(
                                                                "MetaType:",
                                                                weight=700,
                                                                className="label-text",
                                                            ),
                                                            dmc.Text(
                                                                dc.config.metatype,
                                                                weight=500,
                                                            ),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                ]
                                            ),
                                            dmc.Accordion(
                                                children=[
                                                    dmc.AccordionControl(
                                                        dmc.Text(
                                                            "depictio-CLI configuration",
                                                            weight=700,
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
                                                chevronPosition="right",
                                                variant="contained",
                                            ),
                                            dmc.Accordion(
                                                children=[
                                                    preview_control,
                                                    preview_panel,
                                                ],
                                                chevronPosition="right",
                                                variant="contained",
                                            ),
                                        ]
                                    )
                                ]
                            ),
                        ]
                    ),
                ],
            )
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
                            dmc.Text(
                                "Database ID:", weight=700, className="label-text"
                            ),
                            dmc.Text(str(wf.id), weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Name:", weight=700, className="label-text"),
                            dmc.Text(wf.name, weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Engine:", weight=700, className="label-text"),
                            dmc.Text(
                                f"{wf.engine.name}"
                                + (
                                    f" (version {wf.engine.version})"
                                    if wf.engine.version
                                    else ""
                                ),
                                weight=500,
                            ),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text(
                                "Repository URL:", weight=700, className="label-text"
                            ),
                            dmc.Anchor(
                                wf.repository_url,
                                href=wf.repository_url,
                                target="_blank",
                                weight=500,
                            ),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text(
                                "Description:", weight=700, className="label-text"
                            ),
                            dmc.Text(wf.description, weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Created at:", weight=700, className="label-text"),
                            dmc.Text(wf.registration_time, weight=500),
                        ],
                        spacing="xs",
                    ),
                    # dmc.Group(
                    #     children=[
                    #         dmc.Text("Owners:", weight=700, className="label-text"),
                    #         dmc.Text(str([o.id for o in wf.permissions.owners]), weight=500),
                    #     ],
                    #     spacing="xs",
                    # ),
                    # dmc.Group(
                    #     children=[
                    #         dmc.Text("Viewers:", weight=700, className="label-text"),
                    #         dmc.Text(str(wf.permissions.viewers), weight=500),
                    #     ],
                    #     spacing="xs",
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

    return dmc.AccordionItem(
        children=[
            dmc.AccordionControl(
                f"{wf.workflow_tag} ({str(wf.id)})",
                icon=DashIconify(icon="vscode-icons:file-type-snakemake", width=20),
            ),
            dmc.AccordionPanel(
                children=[
                    dmc.Accordion(
                        children=[
                            dmc.AccordionControl(
                                "Details",
                                icon=DashIconify(
                                    icon="mdi:information-outline", width=20
                                ),
                            ),
                            dmc.AccordionPanel(workflow_details),
                        ],
                    ),
                    dmc.Accordion(
                        children=[
                            dmc.AccordionControl(
                                "Data Collections",
                                icon=DashIconify(icon="mdi:database", width=20),
                            ),
                            dmc.AccordionPanel(
                                children=[
                                    data_collections_section
                                    if data_collections_section
                                    else html.P("No data collections available.")
                                ]
                            ),
                        ],
                    ),
                ]
            ),
        ],
        value=f"{wf.workflow_tag} ({str(wf.id)})",
    )


def render_project_item(
    project: Project, current_user: UserBase, admin_UI: False, token: str
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
                            dmc.Text("Name:", weight=700, className="label-text"),
                            dmc.Text(project.name, weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text(
                                "Description:", weight=700, className="label-text"
                            ),
                            dmc.Text(project.description, weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Created at:", weight=700, className="label-text"),
                            dmc.Text(project.registration_time, weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Owners:", weight=700, className="label-text"),
                            dmc.Text(
                                str(
                                    " ; ".join(
                                        [
                                            f"{o.email} - {o.id}"
                                            for o in project.permissions.owners
                                        ]
                                    )
                                ),
                                weight=500,
                            ),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Viewers:", weight=700, className="label-text"),
                            dmc.Text(
                                str(
                                    " ; ".join(
                                        [
                                            f"{o.email} - {o.id}"
                                            for o in project.permissions.viewers
                                        ]
                                    )
                                ),
                                weight=500,
                            ),
                        ],
                        spacing="xs",
                    ),
                ],
                className="project-details p-3",
            ),
        ],
        radius="md",
        withBorder=True,
        shadow="sm",
        className="p-3",
    )

    def create_workflow_section(title, workflows: List[Workflow]):
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

    project_owned = (
        True
        if str(current_user.id) in [str(o.id) for o in project.permissions.owners]
        else False
    )

    if not admin_UI:
        badge_ownership = dmc.Badge(
            children="Owned" if project_owned else "Shared",
            color="teal" if project_owned else "gray",
            className="ml-2",
        )
    else:
        badge_ownership = dmc.Badge(
            children=project.permissions.owners[0].email,
            color="blue",
            className="ml-2",
        )

    return dmc.AccordionItem(
        children=[
            dmc.AccordionControl(
                dmc.Group(
                    [
                        badge_ownership,
                        dmc.Text(f"{project.name}", weight=700),
                        dmc.Text(f" ({str(project.id)})", weight=500),
                    ],
                ),
            ),
            dmc.AccordionPanel(
                children=[
                    dmc.Accordion(
                        children=[
                            dmc.AccordionControl(
                                "Project Details",
                                icon=DashIconify(
                                    icon="mdi:information-outline", width=20
                                ),
                            ),
                            dmc.AccordionPanel(project_details),
                        ],
                    ),
                    dmc.Accordion(
                        children=[
                            dmc.AccordionControl(
                                "Workflows",
                                icon=DashIconify(icon="mdi:workflow", width=20),
                            ),
                            dmc.AccordionPanel(
                                children=[
                                    dmc.AccordionMultiple(
                                        children=[
                                            html.Div(sections)
                                            if sections
                                            else html.P("No workflows available."),
                                        ]
                                    )
                                ]
                            ),
                        ],
                    ),
                    dmc.Accordion(
                        children=[
                            dmc.Anchor(
                                dmc.AccordionControl(
                                    "Roles and permissions",
                                    icon=DashIconify(
                                        icon="mdi:shield-account", width=20
                                    ),
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
                ]
            ),
        ],
        value=f"{project.name}",
    )


def render_projects_list(
    projects: List[Project], admin_UI: bool = False, token: str = None
):
    """Render the full projects list, categorized into owned and shared."""
    if not projects:
        return html.P("No projects available.")

    current_user = fetch_user_from_token(token)
    logger.info(f"Current user: {current_user}")

    def create_project_section(title, projects, current_user):
        if not projects:
            return None
        project_items = [
            render_project_item(
                project=project,
                current_user=current_user,
                admin_UI=admin_UI,
                token=token,
            )
            for project in projects
        ]
        return [
            # dmc.Title(title, order=2, style={"marginTop": "20px"}),
            dmc.Accordion(
                children=project_items,
                chevronPosition="right",
                className="mb-4",
            ),
        ]

    sections = create_project_section("Projects:", projects, current_user)

    return dmc.Container(
        children=sections,
        fluid=True,
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

        logger.info(
            f"Workflow ID: {workflow_id}, Data Collection ID: {data_collection_id}"
        )

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
            from depictio_models.models.data_collections import DataCollection

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
            return html.P("No projects available.")

        return html.Div(
            children=[
                render_projects_list(projects=projects, admin_UI=False, token=token),
            ]
        )
