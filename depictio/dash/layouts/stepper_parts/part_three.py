"""Stepper Part Three - Component design configuration step.

This module provides callbacks for the third step of the dashboard component
creation stepper. Users configure the selected component type with specific
settings and data mappings.
"""

import dash
import dash_mantine_components as dmc
import httpx
from dash import ALL, MATCH, Input, Output, State, html

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.deltatables_utils import load_deltatable_lite
from depictio.dash.modules.card_component.frontend import design_card
from depictio.dash.modules.figure_component.utils import design_figure
from depictio.dash.modules.image_component.design_ui import design_image
from depictio.dash.modules.interactive_component.frontend import design_interactive
from depictio.dash.modules.multiqc_component.frontend import design_multiqc
from depictio.dash.modules.table_component.frontend import design_table


def _check_multiqc_routing(dc_id: str | None, local_data: dict | None) -> bool:
    """Check if a Figure component should be routed to MultiQC.

    MultiQC data collections should use the standalone MultiQC component
    instead of the generic Figure component.

    Args:
        dc_id: The data collection ID.
        local_data: Local storage data containing the access token.

    Returns:
        True if the component should be routed to MultiQC, False otherwise.
    """
    if not dc_id or not local_data:
        return False

    try:
        token = local_data.get("access_token")
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/{dc_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 200:
            dc_type = response.json().get("config", {}).get("type", "").lower()
            return dc_type == "multiqc"
    except Exception as e:
        logger.warning(f"Failed to detect DC type for routing: {e}")

    return False


def _load_component_data(component_type: str, wf_id: str | None, dc_id: str | None, token: str):
    """Load delta table data for a component if needed.

    Args:
        component_type: The type of component being rendered.
        wf_id: Workflow ID.
        dc_id: Data collection ID.
        token: Authorization token.

    Returns:
        DataFrame if data is loaded, None otherwise.
    """
    # Text and MultiQC components don't need delta table data
    if component_type in ["Text", "MultiQC"]:
        return None

    # Guard: require valid dc_id
    if not dc_id:
        return None

    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/datacollections/specs/{dc_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code == 200:
            dc_type = response.json().get("config", {}).get("type", "").lower()
            if dc_type == "multiqc":
                logger.debug(f"Skipping data preview for MultiQC data collection: {dc_id}")
                return None
            return load_deltatable_lite(wf_id, dc_id, TOKEN=token)

        logger.warning(f"Failed to get data collection info: {response.status_code}")
    except Exception as e:
        logger.warning(f"Error checking data collection type: {e}")

    # Fallback: try to load data directly
    try:
        return load_deltatable_lite(wf_id, dc_id, TOKEN=token)
    except Exception as load_error:
        logger.warning(f"Failed to load delta table (possibly MultiQC): {load_error}")
        return None


def _determine_component_to_render(
    btn_component: list | None,
    store_btn_component: list | None,
    ids: list,
    last_button: str,
    components_list: list[str],
) -> tuple[str | None, dict | None]:
    """Determine which component should be rendered based on button clicks.

    Args:
        btn_component: Current click counts for buttons.
        store_btn_component: Stored click counts for buttons.
        ids: Button IDs.
        last_button: Previously selected button.
        components_list: List of available component types.

    Returns:
        Tuple of (component_type, component_id) or (None, None).
    """
    supported_components = ["Figure", "Card", "Interactive", "Table", "Text", "MultiQC", "Image"]

    if btn_component is None or store_btn_component is None:
        return None, None

    # Check if any button was clicked (current count > stored count)
    btn_index = [i for i, (x, y) in enumerate(zip(btn_component, store_btn_component)) if x > y]

    if btn_index:
        component_selected = components_list[btn_index[0]]
        if component_selected in supported_components:
            return component_selected, ids[btn_index[0]]
        return "unsupported", None

    # No button clicked, use last_button
    if last_button != "None" and last_button in supported_components:
        last_button_index = components_list.index(last_button)
        logger.debug(f"Using last button: {last_button}")
        return last_button, ids[last_button_index]

    if last_button != "None":
        return "unsupported", None

    return None, None


def _build_text_component_layout(component_content) -> dmc.Paper:
    """Build the two-panel layout for text component design.

    Args:
        component_content: The content from design_text().

    Returns:
        A DMC Paper with left instructions and right preview sections.
    """
    left_content = component_content.children[:-1]
    preview_content = component_content.children[-1]

    return dmc.Paper(
        [
            dmc.Paper(
                dmc.Stack(left_content),
                w="45%",
                p="xl",
                style={"borderRight": "1px solid var(--mantine-color-gray-4)"},
            ),
            dmc.Paper(preview_content, w="45%", p="xl"),
        ],
        w="100%",
        mih=300,
        withBorder=True,
        radius="md",
        p="xs",
        style={"display": "flex", "flexDirection": "row", "gap": "10px"},
    )


def return_design_component(
    component_selected, id, df, btn_component, wf_id=None, dc_id=None, local_data=None
):
    """Return the appropriate design component based on selection.

    Args:
        component_selected: The type of component selected (Figure, Card, etc.).
        id: The component identifier.
        df: DataFrame for data-driven components.
        btn_component: Button component state for return.
        wf_id: Workflow ID.
        dc_id: Data collection ID.
        local_data: Local storage data containing auth info.

    Returns:
        Tuple of (component layout, button component state).
    """
    # Check if DC is MultiQC type and override component selection
    if component_selected == "Figure" and _check_multiqc_routing(dc_id, local_data):
        logger.debug("Routing to MultiQC component")
        component_selected = "MultiQC"

    if component_selected == "Figure":
        component_content = design_figure(
            id, workflow_id=wf_id, data_collection_id=dc_id, local_data=local_data
        )
        return html.Div(
            component_content, style={"width": "100%", "maxWidth": "none"}
        ), btn_component
    elif component_selected == "Card":
        component_content = design_card(id, df)
        return html.Div(component_content, style={"width": "100%"}), btn_component
    elif component_selected == "Interactive":
        component_content = design_interactive(id, df)
        return html.Div(component_content, style={"width": "100%"}), btn_component
    elif component_selected == "Table":
        component_content = design_table(id)
        return html.Div(component_content, style={"width": "100%"}), btn_component
    elif component_selected == "Text":
        from depictio.dash.modules.text_component.frontend import design_text

        component_content = design_text(id)
        text_layout = _build_text_component_layout(component_content)
        return text_layout, btn_component
    elif component_selected == "MultiQC":
        component_content = design_multiqc(
            id, workflow_id=wf_id, data_collection_id=dc_id, local_data=local_data
        )
        return html.Div(component_content, style={"width": "100%"}), btn_component
    elif component_selected == "Image":
        component_content = design_image(
            id, df, workflow_id=wf_id, data_collection_id=dc_id, local_data=local_data
        )
        return html.Div(component_content, style={"width": "100%"}), btn_component
    elif component_selected == "JBrowse2":
        return dash.no_update, btn_component
        # return design_jbrowse(id), btn_component
    # TODO: implement the following components
    elif component_selected == "Graph":
        return dash.no_update, btn_component
    elif component_selected == "Map":
        return dash.no_update, btn_component
    else:
        return html.Div("Not implemented yet", style={"width": "100%"}), btn_component


def register_callbacks_stepper_part_three(app):
    """Register Dash callbacks for stepper part three.

    Args:
        app: The Dash application instance.
    """

    @app.callback(
        Output({"type": "output-stepper-step-3", "index": MATCH}, "children"),
        Output({"type": "store-btn-option", "index": MATCH, "value": ALL}, "data"),
        Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
        Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        Input({"type": "store-btn-option", "index": MATCH, "value": ALL}, "data"),
        State({"type": "btn-option", "index": MATCH, "value": ALL}, "id"),
        State({"type": "last-button", "index": MATCH}, "data"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def update_step_3(
        workflow_selection,
        data_collection_selection,
        btn_component,
        store_btn_component,
        ids,
        last_button,
        local_data,
    ):
        """Handle step 3 updates based on component selection and data.

        Args:
            workflow_selection: Selected workflow ID.
            data_collection_selection: Selected data collection ID.
            btn_component: Current button click counts.
            store_btn_component: Stored button click counts.
            ids: Button IDs.
            last_button: Previously selected button type.
            local_data: Local storage data with auth info.

        Returns:
            Tuple of (component design UI, updated button component state).
        """
        if not local_data:
            raise dash.exceptions.PreventUpdate

        token = local_data["access_token"]
        wf_id = workflow_selection
        dc_id = data_collection_selection

        logger.debug(f"Step 3 - workflow: {workflow_selection}, dc: {data_collection_selection}")

        components_list = [
            "Figure",  # 0 - matches part_two index 0
            "Card",  # 1 - matches part_two index 1
            "Interactive",  # 2 - matches part_two index 2
            "Table",  # 3 - matches part_two index 3
            "MultiQC",  # 4 - matches part_two index 4
            "Image",  # 5 - matches part_two index 5
            # Text component handled separately (doesn't need DC selection)
            "JBrowse2",
            "Graph",
            "Map",
        ]

        # Text and MultiQC can proceed without workflow/data collection selection
        if last_button not in ["Text", "MultiQC"] and (
            workflow_selection is None or data_collection_selection is None
        ):
            raise dash.exceptions.PreventUpdate

        # Determine which component to render
        component_to_render, component_id = _determine_component_to_render(
            btn_component, store_btn_component, ids, last_button, components_list
        )

        if component_to_render == "unsupported":
            return html.Div("Not implemented yet"), btn_component

        if component_to_render and component_id:
            df = _load_component_data(component_to_render, wf_id, dc_id, token)
            if df is not None:
                logger.debug(
                    f"Stepper: Loaded delta table for {wf_id}:{dc_id} "
                    f"(shape: {df.shape}) for {component_to_render}"
                )
            else:
                logger.debug(f"Stepper: No data required for {component_to_render} component")

            return return_design_component(
                component_to_render, component_id, df, btn_component, wf_id, dc_id, local_data
            )

        return dash.no_update, btn_component if btn_component else dash.no_update
