import collections

import httpx

from depictio.api.v1.configs.config import API_BASE_URL, settings
from depictio.api.v1.configs.logging_init import logger
from depictio.dash.api_calls import api_call_fetch_user_from_token, api_call_get_dashboard
from depictio.dash.layouts.draggable_scenarios.interactive_component_update import (
    update_interactive_component,
)
from depictio.dash.layouts.edit import enable_box_edit_mode
from depictio.dash.modules.card_component.utils import build_card
from depictio.dash.modules.figure_component.utils import build_figure
from depictio.dash.modules.interactive_component.utils import build_interactive
from depictio.dash.modules.jbrowse_component.utils import build_jbrowse
from depictio.dash.modules.table_component.utils import build_table
from depictio.models.models.dashboards import DashboardData
from depictio.models.utils import convert_model_to_dict

build_functions = {
    "card": build_card,
    "figure": build_figure,
    "interactive": build_interactive,
    "table": build_table,
    "jbrowse": build_jbrowse,
}


def return_interactive_components_dict(dashboard_data):
    # logger.info(f"Dashboard data: {dashboard_data}")

    # logger.debug(f"Dashboard data: {dashboard_data}")
    # logger.debug(f"Dashboard data type: {type(dashboard_data)}")

    interactive_components_dict = collections.defaultdict(dict)

    for e in dashboard_data:
        # logger.debug(f"e: {e}")

        if "component_type" not in e:
            logger.debug(f"Component type not found in e: {e}")
            continue

        if e["component_type"] == "interactive":
            # logger.debug(f"e: {e}")
            # logger.debug(f"e['value']: {e['value']}")
            # logger.debug(f"e['component_type']: {e['component_type']}")
            interactive_components_dict[e["index"]] = {
                "value": e["value"],
                "metadata": e,
            }

    # interactive_components_dict = {e["index"]: {"value": e["value"], "metadata": e} for e in dashboard_data if e["component_type"] == "interactive"}
    # logger.debug(f"Interactive components dict: {interactive_components_dict}")
    return interactive_components_dict


def render_dashboard(stored_metadata, edit_components_button, dashboard_id, TOKEN):
    logger.info(f"Rendering dashboard with ID: {dashboard_id}")
    from depictio.dash.layouts.draggable import clean_stored_metadata

    stored_metadata = clean_stored_metadata(stored_metadata)
    # logger.info(f"Stored metadata: {stored_metadata}")

    children = list()

    for child_metadata in stored_metadata:
        child_metadata["build_frame"] = True
        child_metadata["access_token"] = TOKEN
        # logger.info(child_metadata)
        # logger.info(f"type of child_metadata : {type(child_metadata)}")

        # Extract the type of the child (assuming there is a type key in the metadata)
        component_type = child_metadata.get("component_type", None)
        # logger.info(f"component_type : {component_type}")
        if component_type not in build_functions:
            logger.warning(f"Unsupported child type: {component_type}")
            raise ValueError(f"Unsupported child type: {component_type}")

        # Get the build function based on the type
        build_function = build_functions[component_type]
        # logger.info(f"build_function : {build_function.__name__}")

        # Build the child using the appropriate function and kwargs
        child = build_function(**child_metadata)
        # logger.debug(f"child : ")
        children.append(child)
    # logger.info(f"Children: {children}")

    interactive_components_dict = return_interactive_components_dict(stored_metadata)

    children = [
        enable_box_edit_mode(
            child.to_plotly_json(),
            switch_state=edit_components_button,
            dashboard_id=dashboard_id,
            TOKEN=TOKEN,
        )
        for child in children
    ]
    # logger.info(f"Children: {children}")

    children = update_interactive_component(
        stored_metadata,
        interactive_components_dict,
        children,
        switch_state=edit_components_button,
        TOKEN=TOKEN,
        dashboard_id=dashboard_id,
    )
    # logger.info(f"Children: {children}")
    return children


def load_depictio_data(dashboard_id, local_data):
    logger.info(f"Loading Depictio data for dashboard ID: {dashboard_id}")
    if not local_data["access_token"]:
        logger.warning("Access token not found.")
        return None

    dashboard_data_dict = api_call_get_dashboard(dashboard_id, local_data["access_token"])
    if not dashboard_data_dict:
        logger.error(f"Failed to fetch dashboard data for {dashboard_id}")
        raise ValueError(f"Failed to fetch dashboard data: {dashboard_id}")

    dashboard_data = DashboardData.from_mongo(dashboard_data_dict)

    # logger.info(f"load_depictio_data : {dashboard_data}")

    if dashboard_data:
        if not hasattr(dashboard_data, "buttons_data"):
            dashboard_data.buttons_data = {
                "edit_components_button": True,
                "edit_dashboard_mode_button": True,
                "add_button": {"count": 0},
            }

        # buttons = ["edit_components_button", "edit_dashboard_mode_button", "add_button"]
        # for button in buttons:
        #     if button not in dashboard_data["buttons_data"]:
        #         if button == "add_button":
        #             dashboard_data["buttons_data"][button] = {"count": 0}
        #         else:
        #             dashboard_data["buttons_data"][button] = True

        if hasattr(dashboard_data, "stored_metadata"):
            current_user = api_call_fetch_user_from_token(local_data["access_token"])

            # Check if data is available, if not set the buttons to disabled
            owner = (
                True
                if str(current_user.id) in [str(e.id) for e in dashboard_data.permissions.owners]
                else False
            )

            # logger.info(f"Owner: {owner}")
            # logger.info(f"Current user: {current_user.id}")
            # logger.info(
            #     f"Dashboard owners: {[str(e.id) for e in dashboard_data.permissions.owners]}"
            # )

            viewer_ids = [str(e.id) for e in dashboard_data.permissions.viewers]
            is_viewer = str(current_user.id) in viewer_ids
            has_wildcard = "*" in dashboard_data.permissions.viewers
            viewer = is_viewer or has_wildcard

            if not owner and viewer:
                # disabled = True
                # edit_dashboard_mode_button_checked = True
                edit_components_button_checked = False
            else:
                # disabled = False
                # edit_dashboard_mode_button_checked = dashboard_data.buttons_data[
                #     "edit_dashboard_mode_button"
                # ]
                edit_components_button_checked = dashboard_data.buttons_data[
                    "edit_components_button"
                ]

            # Disable edit_components_button for anonymous users and temporary users on public dashboards in unauthenticated mode
            if settings.auth.unauthenticated_mode:
                # Disable for anonymous users (non-temporary)
                if (
                    hasattr(current_user, "is_anonymous")
                    and current_user.is_anonymous
                    and not getattr(current_user, "is_temporary", False)
                ):
                    edit_components_button_checked = False
                # Also disable for temporary users viewing public dashboards they don't own
                elif getattr(current_user, "is_temporary", False) and not owner:
                    edit_components_button_checked = False
            else:
                # If not in unauthenticated mode, check if the user is owner or has edit permissions
                if not owner and not viewer:
                    edit_components_button_checked = False

            children = render_dashboard(
                dashboard_data.stored_metadata,
                edit_components_button_checked,
                dashboard_id,
                local_data["access_token"],
            )
            # logger.info(f"Render Children: {children}")

            dashboard_data.stored_children_data = children
        # logger.info(f"Dashboard data RETURN: {dashboard_data}")
        dashboard_data = convert_model_to_dict(dashboard_data)
        # logger.info(f"Dashboard data RETURN to dict: {dashboard_data}")
        return dashboard_data
    else:
        return None
