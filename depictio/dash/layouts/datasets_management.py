import dash_mantine_components as dmc
import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State, ctx
import httpx
from dash_iconify import DashIconify
import yaml

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.endpoints.user_endpoints.core_functions import fetch_user_from_token
from depictio.api.v1.configs.logging import logger


def fetch_workflows(token):
    # Fetch the datasets for the user
    response = httpx.get(f"{API_BASE_URL}/depictio/api/v1/workflows/get_all_workflows", headers={"Authorization": f"Bearer {token}"})
    logger.info(f"Response status code: {response.status_code}")
    if response.status_code == 200:
        return response.json()
    else:
        logger.error(f"Failed to fetch datasets for current user.")
        return []


def render_workflows_list(workflows):
    if not workflows:
        return html.P("No datasets available.")

    workflow_items = []
    for wf in workflows:
        # Create data collection items
        data_collection_items = []

        for dc in wf["data_collections"]:
            icon = "mdi:table" if dc["config"]["type"].lower() == "table" else "mdi:file-document"
            dc_config = yaml.dump(dc["config"], default_flow_style=False)
            dc_config = f"""```yaml\n{dc_config}\n```"""

            data_collection_items.append(
                dmc.Paper(
                    dmc.AccordionMultiple(
                        [
                            dmc.AccordionControl(dc["data_collection_tag"], icon=DashIconify(icon=icon, width=20)),
                            dmc.AccordionPanel(
                                [
                                    dmc.Group(
                                        [
                                            dmc.Text("Tag:", weight=700, className="label-text"),
                                            dmc.Text(dc["data_collection_tag"], weight=500),
                                        ],
                                        spacing="xs",
                                    ),
                                    dmc.Group(
                                        [
                                            dmc.Text("Description:", weight=700, className="label-text"),
                                            dmc.Text(dc["description"], weight=500),
                                        ],
                                        spacing="xs",
                                    ),
                                    dmc.Group(
                                        [
                                            dmc.Text("Type:", weight=700, className="label-text"),
                                            dmc.Text(dc["config"]["type"], weight=500),
                                        ],
                                        spacing="xs",
                                    ),
                                    dmc.Accordion(
                                        [
                                            dmc.AccordionControl(
                                                dmc.Text(
                                                    "Configuration",
                                                    weight=700,
                                                    className="label-text",
                                                    # move to the left
                                                    # style={"marginLeft": "-10px"},
                                                ),
                                                # yaml icon
                                                icon=DashIconify(icon="ic:baseline-settings-applications", width=20),
                                            ),
                                            dmc.AccordionPanel(
                                                dmc.Paper(
                                                    dcc.Markdown(id="dc-config-md", children=dc_config),
                                                    className="p-3",
                                                    radius="sm",
                                                    withBorder=True,
                                                    shadow="xs",
                                                )
                                            ),
                                        ]
                                    ),
                                ]
                            ),
                        ],
                    ),
                    className="p-3",
                    radius="sm",
                    withBorder=True,
                    shadow="xs",
                    style={"marginBottom": "10px"},  # Space between data collection papers
                )
            )

        # Create the main workflow accordion item
        workflow_items.append(
            dmc.AccordionItem(
                [
                    dmc.AccordionControl(f"{wf['engine']}/{wf['name']}", icon=DashIconify(icon="vscode-icons:file-type-snakemake", width=20)),
                    dmc.AccordionPanel(
                        dmc.AccordionMultiple(
                            [
                                dmc.AccordionControl("Details", icon=DashIconify(icon="mdi:information-outline", width=20)),
                                dmc.AccordionPanel(
                                    dmc.Paper(
                                        [
                                            html.Div(
                                                [
                                                    dmc.Group(
                                                        [
                                                            dmc.Text("Name:", weight=700, className="label-text"),
                                                            dmc.Text(wf["name"], weight=500),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                    dmc.Group(
                                                        [
                                                            dmc.Text("Engine:", weight=700, className="label-text"),
                                                            dmc.Text(wf["engine"], weight=500),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                    dmc.Group(
                                                        [
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
                                                        [
                                                            dmc.Text("Description:", weight=700, className="label-text"),
                                                            dmc.Text(wf["description"], weight=500),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                    dmc.Group(
                                                        [
                                                            dmc.Text("Created at:", weight=700, className="label-text"),
                                                            dmc.Text(wf["registration_time"], weight=500),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                    dmc.Group(
                                                        [
                                                            dmc.Text("Owners:", weight=700, className="label-text"),
                                                            dmc.Text(str(wf["permissions"]["owners"]), weight=500),
                                                        ],
                                                        spacing="xs",
                                                    ),
                                                ],
                                                className="dataset-details p-3",
                                            ),
                                            # Add the nested Data Collections accordion
                                            # dmc.Accordion(
                                            #     [
                                            #     ],
                                            #     chevronPosition="right",
                                            #     className="mt-3",
                                            # ),
                                        ],
                                        radius="md",
                                        withBorder=True,
                                        shadow="sm",
                                        className="p-3",
                                    )
                                ),
                                dmc.AccordionItem(
                                    [
                                        dmc.AccordionControl("Data Collections", icon=DashIconify(icon="mdi:database", width=20)),
                                        dmc.AccordionPanel(
                                            dmc.Paper(
                                                data_collection_items,
                                                className="p-3",
                                                radius="md",
                                                withBorder=True,
                                                shadow="sm",
                                            )
                                        ),
                                    ],
                                    value="data-collections",
                                ),
                            ],
                        ),
                    ),
                ],
                value=f"{wf['engine']}/{wf['name']}",
            )
        )

    return dmc.Accordion(
        children=workflow_items,
        chevronPosition="right",
    )


def register_datasets_callbacks(app):
    @app.callback(
        Output("datasets-list", "children"),
        Input("url", "pathname"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def update_datasets_list(pathname, local_store):
        datasets = fetch_workflows(local_store["access_token"])
        return render_workflows_list(datasets)
