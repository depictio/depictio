# Import necessary libraries
import dash
import dash_mantine_components as dmc
import httpx
from dash import MATCH, Input, Output, State, dcc, html
from dash_iconify import DashIconify

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.component_metadata import get_dmc_button_color, is_enabled
from depictio.dash.modules.jbrowse_component.utils import build_jbrowse, build_jbrowse_frame
from depictio.dash.utils import UNSELECTED_STYLE, list_workflows, return_mongoid

# Depictio imports


def register_callbacks_jbrowse_component(app):
    """Register all callbacks for the JBrowse component system."""

    # ============================================================================
    # INDIVIDUAL COMPONENT UPDATE - Modular Draggable System
    # ============================================================================
    @app.callback(
        Output({"type": "draggable-item", "index": MATCH}, "children", allow_duplicate=True),
        [
            Input("component-render-trigger", "data"),
            Input({"type": "jbrowse-update-trigger", "index": MATCH}, "data"),
        ],
        [
            State({"type": "component-meta", "index": MATCH}, "data"),
            State("local-store", "data"),
            State(
                {"type": "stored-metadata-component", "index": MATCH}, "data", allow_optional=True
            ),
            State("url", "pathname"),
        ],
        prevent_initial_call=True,
    )
    def update_jbrowse_component_direct(
        trigger, jbrowse_trigger, component_meta, local_data, metadata, pathname
    ):
        """Update JBrowse component directly - part of modular draggable system."""
        if not trigger or not trigger.get("needs_update"):
            return dash.no_update

        # Check if this trigger is relevant for this component
        trigger_id = trigger.get("trigger_id")
        trigger_prop = trigger.get("trigger_prop", "")

        # Interactive component changes should update ALL components (filters affect everything)
        is_interactive_change = "interactive-component-value" in trigger_prop

        # For non-interactive triggers, only update the specific component
        if not is_interactive_change and trigger_id and isinstance(trigger_id, dict):
            component_index = trigger_id.get("index")
            meta_index = component_meta.get("index") if component_meta else None

            # Only update if this is the triggered component (for direct operations like edit/duplicate)
            if component_index != meta_index:
                return dash.no_update

        if not local_data or not metadata:
            return dash.no_update

        # Extract dashboard info
        dashboard_id = pathname.split("/")[-1] if pathname else "default"
        TOKEN = local_data.get("access_token")

        logger.info(f"🔄 Updating JBrowse component {meta_index} directly")

        try:
            # Build the JBrowse component using existing build_jbrowse function
            updated_component = build_jbrowse(
                index=meta_index, stored_metadata=metadata, TOKEN=TOKEN, dashboard_id=dashboard_id
            )

            if updated_component:
                logger.info(f"✅ JBrowse component {meta_index} updated successfully")
                return updated_component
            else:
                logger.warning(f"⚠️ Failed to build JBrowse component {meta_index}")
                return dash.no_update

        except Exception as e:
            logger.error(f"❌ Error updating JBrowse component {meta_index}: {e}")
            return dash.no_update

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
        if not data:
            return None

        TOKEN = data["access_token"]
        logger.info(f"update_jbrowse TOKEN : {TOKEN}")

        dashboard_id = pathname.split("/")[-1]

        workflows = list_workflows(TOKEN)

        workflow_id = [e for e in workflows if e["workflow_tag"] == wf_id][0]["_id"]
        data_collection_id = [
            f
            for e in workflows
            if e["_id"] == workflow_id
            for f in e["data_collections"]
            if f["data_collection_tag"] == dc_id
        ][0]["_id"]

        dc_specs = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{data_collection_id}",
            headers={
                "Authorization": f"Bearer {TOKEN}",
            },
        ).json()

        # Get DC ID that are joined
        if "join" in dc_specs["config"]:
            dc_specs["config"]["join"]["with_dc_id"] = list()
            for dc_tag in dc_specs["config"]["join"]["with_dc"]:
                _, dc_id = return_mongoid(
                    workflow_id=workflow_id, data_collection_tag=dc_tag, TOKEN=TOKEN
                )
                dc_specs["config"]["join"]["with_dc_id"].append(dc_id)

        jbrowse_kwargs = {
            "index": id["index"],
            "wf_id": workflow_id,
            "dc_id": data_collection_id,
            "dc_config": dc_specs["config"],
            "access_token": TOKEN,
            "dashboard_id": dashboard_id,
            "user_cache": user_cache,
        }

        jbrowse_body = build_jbrowse(**jbrowse_kwargs)
        return jbrowse_body


def design_jbrowse(id):
    row = [
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
            # dbc.Card(
            #     dbc.CardBody(
            #         id={
            #             "type": "jbrowse-body",
            #             "index": id["index"],
            #         },
            #     ),
            #     id={
            #         "type": "component-container",
            #         "index": id["index"],
            #     },
            # )
        ),
    ]
    return row


def create_stepper_jbrowse_button(n, disabled=None):
    """
    Create the stepper JBrowse button

    Args:
        n (_type_): _description_
        disabled (bool, optional): Override enabled state. If None, uses metadata.
    """

    # Use metadata enabled field if disabled not explicitly provided
    if disabled is None:
        disabled = not is_enabled("jbrowse")

    button = dmc.Button(
        "JBrowse (Beta)",
        id={
            "type": "btn-option",
            "index": n,
            "value": "JBrowse2",
        },
        n_clicks=0,
        style=UNSELECTED_STYLE,
        size="xl",
        color=get_dmc_button_color("jbrowse"),
        leftSection=DashIconify(icon="material-symbols:table-rows-narrow-rounded", color="white"),
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
