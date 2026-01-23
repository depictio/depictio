"""
JBrowse component frontend module.

This module provides the frontend interface and callbacks for the JBrowse2 genome
browser component. It handles workflow/data collection selection, JBrowse rendering,
and the stepper button for adding JBrowse components.

Functions:
    register_callbacks_jbrowse_component: Register JBrowse-related Dash callbacks.
    design_jbrowse: Create the JBrowse design UI for the stepper.
    create_stepper_jbrowse_button: Create the button for adding JBrowse components.
"""

import dash_mantine_components as dmc
import httpx
from dash import MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import (
    get_component_color,
    get_dmc_button_color,
    is_enabled,
)
from depictio.dash.modules.jbrowse_component.utils import build_jbrowse, build_jbrowse_frame
from depictio.dash.utils import UNSELECTED_STYLE, list_workflows, return_mongoid


def _find_workflow_id(workflows: list[dict], wf_tag: str) -> str | None:
    """Find workflow ID by workflow tag.

    Args:
        workflows: List of workflow dictionaries.
        wf_tag: Workflow tag to search for.

    Returns:
        Workflow ID string, or None if not found.
    """
    for workflow in workflows:
        if workflow["workflow_tag"] == wf_tag:
            return workflow["_id"]
    return None


def _find_data_collection_id(workflows: list[dict], workflow_id: str, dc_tag: str) -> str | None:
    """Find data collection ID by workflow ID and data collection tag.

    Args:
        workflows: List of workflow dictionaries.
        workflow_id: Workflow ID to search within.
        dc_tag: Data collection tag to search for.

    Returns:
        Data collection ID string, or None if not found.
    """
    for workflow in workflows:
        if workflow["_id"] != workflow_id:
            continue
        for dc in workflow["data_collections"]:
            if dc["data_collection_tag"] == dc_tag:
                return dc["_id"]
    return None


def _fetch_dc_specs(dc_id: str, token: str) -> dict:
    """Fetch data collection specifications from the API.

    Args:
        dc_id: Data collection ID.
        token: Authentication token.

    Returns:
        Data collection specs dictionary.
    """
    response = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{dc_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    return response.json()


def _add_joined_dc_ids(dc_specs: dict, workflow_id: str, token: str) -> None:
    """Add joined data collection IDs to the specs configuration.

    Modifies dc_specs in place to add the 'with_dc_id' list.

    Args:
        dc_specs: Data collection specifications dictionary.
        workflow_id: Workflow ID.
        token: Authentication token.
    """
    if "join" not in dc_specs.get("config", {}):
        return

    dc_specs["config"]["join"]["with_dc_id"] = []
    for dc_tag in dc_specs["config"]["join"]["with_dc"]:
        _, dc_id = return_mongoid(workflow_id=workflow_id, data_collection_tag=dc_tag, TOKEN=token)
        dc_specs["config"]["join"]["with_dc_id"].append(dc_id)


def register_callbacks_jbrowse_component(app):
    """Register JBrowse component callbacks with the Dash application.

    This function registers the callback that handles JBrowse component updates
    when workflow/data collection selection changes or the display button is clicked.

    Args:
        app: The Dash application instance.
    """

    @app.callback(
        Output({"type": "jbrowse-body", "index": MATCH}, "children"),
        [
            Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
            Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
            Input({"type": "btn-jbrowse", "index": MATCH}, "n_clicks"),
            Input({"type": "btn-jbrowse", "index": MATCH}, "id"),
            State("local-store", "data"),
            State("url", "pathname"),
            State("user-cache-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def update_jbrowse(wf_id, dc_id, n_clicks, id, data, pathname, user_cache):
        """Update JBrowse component when selection changes or button is clicked.

        Args:
            wf_id: Selected workflow tag.
            dc_id: Selected data collection tag.
            n_clicks: Number of button clicks.
            id: Component ID dictionary.
            data: Local store data containing access token.
            pathname: Current URL pathname.
            user_cache: User cache data.

        Returns:
            JBrowse component body, or None if data is not available.
        """
        if not data:
            return None

        token = data["access_token"]
        logger.info(f"update_jbrowse TOKEN: {token}")

        dashboard_id = pathname.split("/")[-1]
        workflows = list_workflows(token)

        workflow_id = _find_workflow_id(workflows, wf_id)
        data_collection_id = _find_data_collection_id(workflows, workflow_id, dc_id)

        dc_specs = _fetch_dc_specs(data_collection_id, token)
        _add_joined_dc_ids(dc_specs, workflow_id, token)

        jbrowse_kwargs = {
            "index": id["index"],
            "wf_id": workflow_id,
            "dc_id": data_collection_id,
            "dc_config": dc_specs["config"],
            "access_token": token,
            "dashboard_id": dashboard_id,
            "user_cache": user_cache,
        }

        return build_jbrowse(**jbrowse_kwargs)


def design_jbrowse(id: dict) -> list:
    """Create the JBrowse design UI for the stepper interface.

    Creates the display button and container for the JBrowse component
    preview in the design/stepper flow.

    Args:
        id: Component ID dictionary containing the 'index' key.

    Returns:
        List containing the button and component container elements.
    """
    return [
        dmc.Center(
            dmc.Button(
                "Display JBrowse",
                id={"type": "btn-jbrowse", "index": id["index"]},
                n_clicks=0,
                style=UNSELECTED_STYLE,
                size="xl",
                color="yellow",
                leftSection=DashIconify(
                    icon="material-symbols:table-rows-narrow-rounded", color="white"
                ),
            ),
        ),
        html.Div(
            html.Div(
                build_jbrowse_frame(index=id["index"]),
                id={"type": "component-container", "index": id["index"]},
            ),
        ),
    ]


def create_stepper_jbrowse_button(n: int, disabled: bool | None = None) -> tuple:
    """Create the stepper JBrowse button and associated store.

    Creates the button used in the component type selection step of the stepper
    to add a JBrowse genome browser component.

    Args:
        n: Button index for unique identification.
        disabled: Override enabled state. If None, uses component metadata.

    Returns:
        Tuple containing (button, store) components.
    """
    if disabled is None:
        disabled = not is_enabled("jbrowse")

    color = get_dmc_button_color("jbrowse")
    hex_color = get_component_color("jbrowse")

    button = dmc.Button(
        "JBrowse (Beta)",
        id={
            "type": "btn-option",
            "index": n,
            "value": "JBrowse2",
        },
        n_clicks=0,
        style={**UNSELECTED_STYLE, "fontSize": "26px"},
        size="xl",
        variant="outline",
        color=color,
        leftSection=DashIconify(icon="material-symbols:table-rows-narrow-rounded", color=hex_color),
        disabled=disabled,
    )

    store = dcc.Store(
        id={
            "type": "store-btn-option",
            "index": n,
            "value": "JBrowse2",
        },
        data=0,
        storage_type="memory",
    )

    return button, store
