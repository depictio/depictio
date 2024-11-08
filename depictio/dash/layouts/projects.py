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

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.api.v1.endpoints.user_endpoints.core_functions import fetch_user_from_token
from depictio.api.v1.configs.logging import logger
from depictio.api.v1.endpoints.user_endpoints.models import UserBase
from depictio.dash.utils import return_mongoid


# =========================
# Data Fetching Functions
# =========================


def fetch_projects(token):
    # """Fetch all projects for the current user."""
    # url = f"{API_BASE_URL}/depictio/api/v1/projects/get_all_projects"
    # headers = {"Authorization": f"Bearer {token}"}
    # try:
    #     response = httpx.get(url, headers=headers)
    #     response.raise_for_status()
    #     logger.info("Successfully fetched projects.")
    #     return response.json()
    # except httpx.HTTPError as e:
    #     logger.error(f"Error fetching projects: {e}")
    #     return []

    current_user = fetch_user_from_token(token)
    current_user = UserBase(**current_user.dict()).mongo()

    projects = [
        {
            "_id": ObjectId(),
            "name": "Strand-Seq",
            "description": "Strand-Seq project",
            "created_at": "2021-10-01",
            "permissions": {
                "owners": [current_user],
                "viewers": ["*"],
            },
        }
    ]
    return projects


# def fetch_workflows(token, project_id):
#     """Fetch all workflows for a specific project."""
#     url = f"{API_BASE_URL}/depictio/api/v1/projects/{project_id}/workflows"
#     headers = {"Authorization": f"Bearer {token}"}
#     try:
#         response = httpx.get(url, headers=headers)
#         response.raise_for_status()
#         logger.info(f"Successfully fetched workflows for project {project_id}.")
#         return response.json()
#     except httpx.HTTPError as e:
#         logger.error(f"Error fetching workflows for project {project_id}: {e}")
#         return []


def fetch_workflows(token):
    # Fetch the workflows for the user
    response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/workflows/get_all_workflows", headers={"Authorization": f"Bearer {token}"})
    logger.info(f"Response status code: {response.status_code}")
    if response.status_code == 200:
        logger.info(f"Successfully fetched workflows for current user.")
        logger.debug(f"Response: {response.json()}")
        return response.json()
    else:
        logger.error(f"Failed to fetch workflows for current user.")
        return []


# =====================
# Helper Functions
# =====================


def categorize_projects(projects, current_user):
    """Categorize projects into owned and shared/accessed."""
    owned = []
    shared = []

    for project in projects:
        owners_ids = [str(o["_id"]) for o in project["permissions"]["owners"]]
        if str(current_user.id) in owners_ids:
            owned.append(project)
        elif str(current_user.id) in project["permissions"]["viewers"] or "*" in project["permissions"]["viewers"]:
            shared.append(project)

    return owned, shared


def categorize_workflows(workflows, current_user):
    """Categorize workflows into owned and shared/accessed."""
    owned = []
    shared = []

    for wf in workflows:
        owners_ids = [str(o["_id"]) for o in wf["permissions"]["owners"]]
        if str(current_user.id) in owners_ids:
            owned.append(wf)
        elif str(current_user.id) in wf["permissions"]["viewers"] or "*" in wf["permissions"]["viewers"]:
            shared.append(wf)

    return owned, shared


# =====================
# Rendering Components
# =====================


def render_data_collection(dc, workflow_id, token):
    """Render a single data collection item."""
    icon = "mdi:table" if dc["config"]["type"].lower() == "table" else "mdi:file-document"
    dc_config = yaml.dump(dc["config"], default_flow_style=False)
    dc_config_md = f"```yaml\n{dc_config}\n```"

    # Preview Section for Tables
    if dc["config"]["type"].lower() == "table":
        df = load_deltatable_lite(workflow_id=workflow_id, data_collection_id=dc["_id"], TOKEN=token)
        logger.info(f"df shape: {df.shape} for {workflow_id}/{dc['_id']} with name {dc['data_collection_tag']}")
        columnDefs = [{"field": c, "headerName": c} for c in df.columns]
        grid = dag.AgGrid(
            rowData=df.to_pandas().head(100).to_dict("records"),
            id={"type": "project-dc-table", "index": f"{workflow_id}/{dc['_id']}"},
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
    else:
        preview_panel = None
        preview_control = None

    return dmc.Paper(
        children=[
            dmc.AccordionMultiple(
                children=[
                    dmc.Accordion(
                        children=[
                            dmc.AccordionControl(dc["data_collection_tag"], icon=DashIconify(icon=icon, width=20)),
                            dmc.AccordionPanel(
                                children=[
                                    dmc.Accordion(
                                        children=[
                                            dmc.AccordionControl("Details", icon=DashIconify(icon="mdi:information-outline", width=20)),
                                            dmc.AccordionPanel(
                                                children=[
                                                    dmc.Group(
                                                        children=[
                                                            dmc.Text("Database ID:", weight=700, className="label-text"),
                                                            dmc.Text(dc["_id"], weight=500),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                    dmc.Group(
                                                        children=[
                                                            dmc.Text("Tag:", weight=700, className="label-text"),
                                                            dmc.Text(dc["data_collection_tag"], weight=500),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                    dmc.Group(
                                                        children=[
                                                            dmc.Text("Description:", weight=700, className="label-text"),
                                                            dmc.Text(dc["description"], weight=500),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                    dmc.Group(
                                                        children=[
                                                            dmc.Text("Type:", weight=700, className="label-text"),
                                                            dmc.Text(dc["config"]["type"], weight=500),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                ]
                                            ),
                                            dmc.Accordion(
                                                children=[
                                                    dmc.AccordionControl(
                                                        dmc.Text("Configuration", weight=700, className="label-text"),
                                                        icon=DashIconify(icon="ic:baseline-settings-applications", width=20),
                                                    ),
                                                    dmc.AccordionPanel(
                                                        children=[
                                                            dmc.Paper(
                                                                children=dcc.Markdown(children=dc_config_md),
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


def render_workflow_item(wf, token):
    """Render a single workflow item."""
    workflow_details = dmc.Paper(
        children=[
            html.Div(
                children=[
                    dmc.Group(
                        children=[
                            dmc.Text("Database ID:", weight=700, className="label-text"),
                            dmc.Text(wf["_id"], weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Name:", weight=700, className="label-text"),
                            dmc.Text(wf["name"], weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Engine:", weight=700, className="label-text"),
                            dmc.Text(wf["engine"], weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Repository URL:", weight=700, className="label-text"),
                            dmc.Anchor(
                                wf["repository_url"],
                                href=wf["repository_url"],
                                target="_blank",
                                weight=500,
                            ),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Description:", weight=700, className="label-text"),
                            dmc.Text(wf["description"], weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Created at:", weight=700, className="label-text"),
                            dmc.Text(wf["registration_time"], weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Owners:", weight=700, className="label-text"),
                            dmc.Text(str(wf["permissions"]["owners"]), weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Viewers:", weight=700, className="label-text"),
                            dmc.Text(str(wf["permissions"]["viewers"]), weight=500),
                        ],
                        spacing="xs",
                    ),
                ],
                className="dataset-details p-3",
            ),
        ],
        radius="md",
        withBorder=True,
        shadow="sm",
        className="p-3",
    )

    data_collections = [render_data_collection(dc, wf["_id"], token) for dc in wf["data_collections"]]
    data_collections_section = dmc.Paper(
        children=data_collections,
        className="p-3",
        radius="md",
        withBorder=True,
        shadow="sm",
    )

    return dmc.AccordionItem(
        children=[
            dmc.AccordionControl(
                f"{wf['engine']}/{wf['name']} ({wf['_id']})",
                icon=DashIconify(icon="vscode-icons:file-type-snakemake", width=20),
            ),
            dmc.AccordionPanel(
                children=[
                    dmc.Accordion(
                        children=[
                            dmc.AccordionControl("Details", icon=DashIconify(icon="mdi:information-outline", width=20)),
                            dmc.AccordionPanel(workflow_details),
                        ],
                    ),
                    dmc.Accordion(
                        children=[
                            dmc.AccordionControl("Data Collections", icon=DashIconify(icon="mdi:database", width=20)),
                            dmc.AccordionPanel(data_collections_section),
                        ],
                    ),
                ]
            ),
        ],
        value=f"{wf['engine']}/{wf['name']}",
    )


def render_project_item(project, token):
    logger.info(f"Rendering project item: {project}")
    """Render a single project item containing multiple workflows."""
    project_details = dmc.Paper(
        children=[
            html.Div(
                children=[
                    dmc.Group(
                        children=[
                            dmc.Text("Name:", weight=700, className="label-text"),
                            dmc.Text(project["name"], weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Description:", weight=700, className="label-text"),
                            dmc.Text(project["description"], weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Created at:", weight=700, className="label-text"),
                            dmc.Text(project["created_at"], weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Owners:", weight=700, className="label-text"),
                            dmc.Text(str(project["permissions"]["owners"]), weight=500),
                        ],
                        spacing="xs",
                    ),
                    dmc.Group(
                        children=[
                            dmc.Text("Viewers:", weight=700, className="label-text"),
                            dmc.Text(str(project["permissions"]["viewers"]), weight=500),
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

    # Fetch workflows for this project
    workflows = fetch_workflows(token)
    current_user = fetch_user_from_token(token)
    owned_workflows, shared_workflows = categorize_workflows(workflows, current_user)

    def create_workflow_section(title, workflows):
        if not workflows:
            return None
        workflow_items = [render_workflow_item(wf, token) for wf in workflows]
        return [
            dmc.Title(title, order=4, style={"marginTop": "10px"}),
            dmc.Accordion(
                children=workflow_items,
                chevronPosition="right",
                className="mb-3",
            ),
        ]

    sections = []
    owned_section = create_workflow_section("Workflows Owned:", owned_workflows)
    shared_section = create_workflow_section("Workflows Shared/Accessible:", shared_workflows)

    if owned_section:
        sections.extend(owned_section)
    if shared_section:
        sections.extend(shared_section)

    return dmc.AccordionItem(
        children=[
            dmc.AccordionControl(
                f"{project['name']} ({project['_id']})",
                icon=DashIconify(icon="mdi:folder-open", width=20),
            ),
            dmc.AccordionPanel(
                children=[
                    dmc.Accordion(
                        children=[
                            dmc.AccordionControl("Project Details", icon=DashIconify(icon="mdi:information-outline", width=20)),
                            dmc.AccordionPanel(project_details),
                        ],
                    ),
                    dmc.Accordion(
                        children=[
                            dmc.AccordionControl("Workflows", icon=DashIconify(icon="mdi:workflow", width=20)),
                            dmc.AccordionPanel(
                                children=[
                                    dmc.AccordionMultiple(
                                        children=[
                                            html.Div(sections) if sections else html.P("No workflows available."),
                                        ]
                                    )
                                ]
                            ),
                        ],
                    ),
                ]
            ),
        ],
        value=f"{project['name']}",
    )


def render_projects_list(projects, token):
    """Render the full projects list, categorized into owned and shared."""
    if not projects:
        return html.P("No projects available.")

    current_user = fetch_user_from_token(token)
    logger.info(f"Current user: {current_user}")

    owned_projects, shared_projects = categorize_projects(projects, current_user)
    logger.info(f"Owned Projects: {owned_projects}")
    logger.info(f"Shared Projects: {shared_projects}")

    def create_project_section(title, projects):
        if not projects:
            return None
        project_items = [render_project_item(project, token) for project in projects]
        return [
            dmc.Title(title, order=2, style={"marginTop": "20px"}),
            dmc.Accordion(
                children=project_items,
                chevronPosition="right",
                className="mb-4",
            ),
        ]

    sections = []
    owned_section = create_project_section("Projects Owned:", owned_projects)
    shared_section = create_project_section("Projects Shared/Accessible:", shared_projects)

    if owned_section:
        sections.extend(owned_section)
    if shared_section:
        sections.extend(shared_section)

    return dmc.Container(
        children=sections,
        fluid=True,
    )


# =====================
# Callback Registrations
# =====================


def register_projects_callbacks(app):
    """Register callbacks related to projects and data collections."""

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

        # Fetch data collection specs
        try:
            response = httpx.get(
                f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{workflow_id}/{data_collection_id}",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            response.raise_for_status()
            dc_specs = response.json()
        except httpx.HTTPError as e:
            logger.error(f"Error fetching data collection specs: {e}")
            return dash.no_update

        if dc_specs["config"]["type"].lower() == "table":
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
    """Register callbacks related to projects and workflows."""

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
        projects = [project for project in projects if project.get("name") == "Strand-Seq"]

        if not projects:
            logger.info("No projects matched the hardcoded filter.")
            return html.P("No projects available.")

        return html.Div(
            children=[
                render_projects_list(projects, token),
            ]
        )
