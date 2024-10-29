import copy
import json
from dash import html, Input, Output, State, ALL, MATCH, ctx, dcc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import dash_draggable
import dash
import httpx
from depictio.dash.layouts.draggable_scenarios.add_component import add_new_component
from depictio.dash.layouts.edit import edit_component

from depictio.api.v1.configs.config import API_BASE_URL, logger

from depictio.dash.layouts.draggable_scenarios.interactive_component_update import update_interactive_component
from depictio.dash.layouts.draggable_scenarios.restore_dashboard import render_dashboard


# Depictio layout imports for stepper

# Depictio layout imports for header
from depictio.dash.layouts.edit import enable_box_edit_mode
from depictio.dash.utils import generate_unique_index, get_component_data, return_dc_tag_from_id, return_mongoid, return_wf_tag_from_id


# Mapping of component types to their respective dimensions (width and height)
component_dimensions = {"card-component": {"w": 3, "h": 4}, "interactive-component": {"w": 6, "h": 6}, "graph-component": {"w": 9, "h": 8}}
required_breakpoints = ["xl", "lg", "sm", "md", "xs", "xxs"]


def calculate_new_layout_position(child_type, existing_layouts, child_id, n):
    """Calculate position for new layout item based on existing ones and type."""
    # Get the default dimensions from the type
    dimensions = component_dimensions.get(child_type, {"w": 6, "h": 5})  # Default if type not found

    # Simple positioning logic: place items in rows based on their index
    columns_per_row = 12  # Assuming a 12-column layout grid
    row = n // (columns_per_row // dimensions["w"])  # Integer division to find row based on how many fit per row
    col_position = (n % (columns_per_row // dimensions["w"])) * dimensions["w"]  # Modulo for column position

    return {
        "x": col_position,
        "y": row * dimensions["h"],  # Stacking rows based on height of each component
        "w": dimensions["w"],
        "h": dimensions["h"],
        "i": child_id,
    }


def remove_duplicates_by_index(components):
    unique_components = {}
    for component in components:
        index = component["index"]
        if index not in unique_components:
            unique_components[index] = component
    return list(unique_components.values())


def register_callbacks_draggable(app):
    from dash import callback_context

    @app.callback(
        Output("local-store-components-metadata", "data"),
        [
            Input({"type": "workflow-selection-label", "index": ALL}, "value"),
            Input({"type": "datacollection-selection-label", "index": ALL}, "value"),
            Input("url", "pathname"),
        ],
        [
            State("local-store", "data"),  # Contains 'access_token'
            State("local-store-components-metadata", "data"),  # Existing components' data
            State({"type": "workflow-selection-label", "index": ALL}, "id"),
            State({"type": "datacollection-selection-label", "index": ALL}, "id"),
        ],
        prevent_initial_call=True,
    )
    def store_wf_dc_selection(wf_values, dc_values, pathname, local_store, components_store, wf_ids, dc_ids):
        """
        Callback to store all components' workflow and data collection data in a centralized store.
        Updates the store whenever any workflow or data collection dropdown changes.

        Args:
            wf_values (list): List of selected workflow values from all dropdowns.
            dc_values (list): List of selected data collection values from all dropdowns.
            pathname (str): Current URL pathname.
            local_store (dict): Data from 'local-store', expected to contain 'access_token'.
            components_store (dict): Existing components' wf/dc data.
            wf_ids (list): List of IDs for workflow dropdowns.
            dc_ids (list): List of IDs for datacollection dropdowns.

        Returns:
            dict: Updated components' wf/dc data.
        """
        logger.info("Entering store_wf_dc_selection callback")
        logger.debug(f"Workflow values: {wf_values}")
        logger.debug(f"Data collection values: {dc_values}")
        logger.debug(f"URL pathname: {pathname}")
        logger.debug(f"Local store data: {local_store}")
        logger.debug(f"Components store data before update: {components_store}")

        # Validate access token
        if not local_store or "access_token" not in local_store:
            logger.error("Local data or access_token is missing.")
            return components_store  # No update

        TOKEN = local_store["access_token"]

        # Initialize components_store if empty
        if not components_store:
            components_store = {}

        # Process workflow selections
        for wf_val, wf_id in zip(wf_values, wf_ids):
            # Parse the ID safely
            try:
                trigger_id = wf_id
            # except json.JSONDecodeError as e:
            #     logger.error(f"Error parsing workflow ID '{wf_id}': {e}")
            #     continue  # Skip this iteration
            except Exception as e:
                logger.error(f"Error parsing workflow ID '{wf_id}': {e}")
                continue

            trigger_index = str(trigger_id.get("index"))
            if not trigger_index:
                logger.error(f"Invalid workflow ID: {trigger_id}")
                continue  # Skip this iteration

            # Update workflow tag
            components_store.setdefault(trigger_index, {})
            components_store[trigger_index]["wf_tag"] = wf_val

            # Fetch corresponding wf_id and dc_id
            dc_tag = components_store[trigger_index].get("dc_tag", "")
            try:
                wf_id_fetched, dc_id_fetched = return_mongoid(workflow_tag=wf_val, data_collection_tag=dc_tag, TOKEN=TOKEN)
                components_store[trigger_index]["wf_id"] = wf_id_fetched
                components_store[trigger_index]["dc_id"] = dc_id_fetched
                logger.debug(f"Updated component '{trigger_index}' with wf_id: {wf_id_fetched}, dc_id: {dc_id_fetched}")
            except Exception as e:
                logger.error(f"Error retrieving IDs for component '{trigger_index}': {e}")
                components_store[trigger_index]["wf_id"] = ""
                components_store[trigger_index]["dc_id"] = ""

        # Process datacollection selections
        for dc_val, dc_id in zip(dc_values, dc_ids):
            # Parse the ID safely
            try:
                trigger_id = dc_id
            # except json.JSONDecodeError as e:
            #     logger.error(f"Error parsing datacollection ID '{dc_id}': {e}")
            #     continue  # Skip this iteration
            except Exception as e:
                logger.error(f"Error parsing datacollection ID '{dc_id}': {e}")
                continue  # Skip this iteration

            trigger_index = str(trigger_id.get("index"))
            if not trigger_index:
                logger.error(f"Invalid datacollection ID: {trigger_id}")
                continue  # Skip this iteration

            # Update datacollection tag
            components_store.setdefault(trigger_index, {})
            components_store[trigger_index]["dc_tag"] = dc_val

            # Fetch corresponding wf_id and dc_id
            wf_tag = components_store[trigger_index].get("wf_tag", "")
            try:
                wf_id_fetched, dc_id_fetched = return_mongoid(workflow_tag=wf_tag, data_collection_tag=dc_val, TOKEN=TOKEN)
                components_store[trigger_index]["wf_id"] = wf_id_fetched
                components_store[trigger_index]["dc_id"] = dc_id_fetched
                logger.debug(f"Updated component '{trigger_index}' with wf_id: {wf_id_fetched}, dc_id: {dc_id_fetched}")
            except Exception as e:
                logger.error(f"Error retrieving IDs for component '{trigger_index}': {e}")
                components_store[trigger_index]["wf_id"] = ""
                components_store[trigger_index]["dc_id"] = ""

        logger.debug(f"Components store data after update: {components_store}")
        return components_store

    @app.callback(
        Output("draggable", "children"),
        Output("draggable", "layouts"),
        Output("stored-draggable-children", "data"),
        Output("stored-draggable-layouts", "data"),
        # Output("stored-add-button", "data"),
        Input(
            {
                "type": "btn-done",
                "index": ALL,
            },
            "n_clicks",
        ),
        Input(
            {
                "type": "btn-done-edit",
                "index": ALL,
            },
            "n_clicks",
        ),
        State(
            {
                "type": "interactive-component-value",
                "index": ALL,
            },
            "id",
        ),
        Input(
            {
                "type": "interactive-component-value",
                "index": ALL,
            },
            "value",
        ),
        State("stored-add-button", "data"),
        State(
            {
                "type": "stored-metadata-component",
                "index": ALL,
            },
            "data",
        ),
        State(
            {
                "type": "component-container",
                "index": ALL,
            },
            "children",
        ),
        State("draggable", "children"),
        State("draggable", "layouts"),
        Input("draggable", "layouts"),
        State("stored-draggable-children", "data"),
        State("stored-draggable-layouts", "data"),
        Input("stored-draggable-children", "data"),
        Input("stored-draggable-layouts", "data"),
        Input(
            {"type": "remove-box-button", "index": ALL},
            "n_clicks",
        ),
        Input(
            {
                "type": "edit-box-button",
                "index": ALL,
            },
            "n_clicks",
        ),
        Input(
            {
                "type": "duplicate-box-button",
                "index": ALL,
            },
            "n_clicks",
        ),
        Input("remove-all-components-button", "n_clicks"),
        State("toggle-interactivity-button", "checked"),
        State("edit-dashboard-mode-button", "checked"),
        Input("edit-dashboard-mode-button", "checked"),
        State("url", "pathname"),
        State("local-store", "data"),
        prevent_initial_call=True,
    )
    def populate_draggable(
        btn_done_clicks,
        btn_done_edit_clicks,
        interactive_component_ids,
        interactive_component_values,
        stored_add_button,
        stored_metadata,
        test_container,
        draggable_children,
        draggable_layouts,
        input_draggable_layouts,
        state_stored_draggable_children,
        state_stored_draggable_layouts,
        input_stored_draggable_children,
        input_stored_draggable_layouts,
        remove_box_button_values,
        edit_box_button_values,
        duplicate_box_button_values,
        remove_all_components_button,
        toggle_interactivity_button,
        edit_dashboard_mode_button,
        input_edit_dashboard_mode_button,
        pathname,
        local_data,
    ):
        if not local_data:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        if not state_stored_draggable_layouts:
            state_stored_draggable_layouts = {}
        if not state_stored_draggable_children:
            state_stored_draggable_children = {}

        TOKEN = local_data["access_token"]

        logger.info("btn_done_clicks: {}".format(btn_done_clicks))
        logger.info("stored_add_button: {}".format(stored_add_button))

        ctx = dash.callback_context

        logger.debug("CTX: {}".format(ctx))
        # logger.debug("CTX triggered: {}".format(ctx.triggered))
        logger.debug("CTX triggered_id: {}".format(ctx.triggered_id))
        logger.info("TYPE CTX triggered_id: {}".format(type(ctx.triggered_id)))
        logger.debug("CTX triggered_props_id: {}".format(ctx.triggered_prop_ids))
        # logger.debug("CTX args_grouping: {}".format(ctx.args_grouping))
        # logger.debug("CTX inputs: {}".format(ctx.inputs))
        # logger.debug("CTX inputs_list: {}".format(ctx.inputs_list))
        # logger.debug("CTX states: {}".format(ctx.states))
        # logger.debug("CTX states_list: {}".format(ctx.states_list))

        if isinstance(ctx.triggered_id, dict):
            triggered_input = ctx.triggered_id["type"]
            triggered_input_dict = ctx.triggered_id
        elif isinstance(ctx.triggered_id, str):
            triggered_input = ctx.triggered_id
        logger.info("triggered_input : {}".format(triggered_input))
        logger.info("type of triggered_input: {}".format(type(triggered_input)))

        # Check if the value of the interactive component is not None
        check_value = False
        # remove duplicate of stored_metadata based on index
        index_list = []

        # FIXME: Remove duplicates from stored_metadata
        # Remove duplicates from stored_metadata
        logger.info("Stored metadata: {}".format(stored_metadata))
        logger.info(f"Length of stored metadata: {len(stored_metadata)}")
        stored_metadata = remove_duplicates_by_index(stored_metadata)
        logger.info("CLEANED Stored metadata: {}".format(stored_metadata))
        logger.info(f"Length of cleaned stored metadata: {len(stored_metadata)}")
        logger.info(f"URL PATHNAME: {pathname}")
        dashboard_id = pathname.split("/")[-1]
        stored_metadata_interactive = [e for e in stored_metadata if e["component_type"] == "interactive"]

        logger.info("Interactive component values: {}".format(interactive_component_values))
        logger.info("Interactive component ids: {}".format(interactive_component_ids))
        logger.info("Stored metadata interactive: {}".format(stored_metadata_interactive))

        interactive_components_dict = {
            id["index"]: {"value": value, "metadata": metadata}
            for (id, value, metadata) in zip(
                interactive_component_ids,
                interactive_component_values,
                stored_metadata_interactive,
            )
        }
        logger.info(f"Interactive components dict: {interactive_components_dict}")

        if triggered_input == "interactive-component":
            if interactive_components_dict:
                logger.info(f"Interactive component triggered input: {triggered_input}")
                logger.info(f"Interactive components dict: {interactive_components_dict}")
                triggered_input_eval_index = int(triggered_input_dict["index"])
                logger.info(f"Triggered input eval index: {triggered_input_eval_index}")
                if triggered_input_eval_index in interactive_components_dict:
                    value = interactive_components_dict[triggered_input_eval_index]["value"]
                    logger.info(f"Value: {value}")
                    # Handle the case of the TextInput component
                    if interactive_components_dict[triggered_input_eval_index]["metadata"]["interactive_component_type"] != "TextInput":
                        check_value = True if value is not None else False
                    else:
                        check_value = True if value is not "" else False
                    logger.info(f"Check value: {check_value}")

        # # if triggered_input["type"] == "btn-done":
        if triggered_input == "btn-done":
            # if btn_done_clicks:
            #     if btn_done_clicks[-1] > 0:
            logger.info("\n\n")
            logger.info("Populate draggable")

            logger.info("stored_metadata: {}".format(stored_metadata))
            # logger.info("stored_children: {}".format(test_container))
            # logger.info("draggable_children: {}".format(draggable_children))
            logger.info("draggable_layouts: {}".format(draggable_layouts))

            existing_ids = {child["props"]["id"] for child in draggable_children}
            n = len(draggable_children)

            logger.info(f"Existing ids: {existing_ids}")
            logger.info(f"n: {n}")

            # Ensure all necessary breakpoints are initialized
            for bp in required_breakpoints:
                if bp not in draggable_layouts:
                    draggable_layouts[bp] = []

            for child in test_container:
                # logger.info(f"Child: {child}")
                child_index = int(child["props"]["id"]["index"])

                child_type = child["props"]["id"]["type"]

                logger.info(f"Child type: {child_type}")

                if child_type == "interactive-component":
                    logger.info(f"Interactive component found: {child}")
                    # WARNING: This is a temporary fix to remove the '-tmp' suffix from the id
                    if child["props"]["children"]["props"]["children"]["props"]["children"][1]["props"]["id"]["type"].endswith("-tmp"):
                        child["props"]["children"]["props"]["children"]["props"]["children"][1]["props"]["id"]["type"] = child["props"]["children"]["props"]["children"]["props"][
                            "children"
                        ][1]["props"]["id"]["type"].replace("-tmp", "")

                logger.info(f"Child index: {child_index}")
                logger.info(f"Child type: {child_type}")
                # child types: card-component (w:3,h:4), interactive-component (w:6,h:6), graph-component (w:9,h:8)
                if child_index not in existing_ids:
                    child = enable_box_edit_mode(child, True, dashboard_id=dashboard_id, fresh=True, TOKEN=TOKEN)
                    draggable_children.append(child)
                    child_id = f"box-{str(child_index)}"

                    # Calculate layout item position and size based on type
                    new_layout_item = calculate_new_layout_position(child_type, draggable_layouts, child_id, n)

                    # Update necessary breakpoints, this example only updates 'lg' for simplicity
                    # draggable_layouts["lg"].append(new_layout_item)

                    # new_layout_item = {
                    #     "i": child_id,
                    #     "x": 10 * (n % 2),
                    #     "y": n * 10,
                    #     "w": 6,
                    #     "h": 5,
                    # }

                    for key in required_breakpoints:
                        draggable_layouts[key].append(new_layout_item)
                    n += 1

            # logger.info(f"Updated draggable children: {draggable_children}")
            logger.info(f"Updated draggable layouts: {draggable_layouts}")
            state_stored_draggable_children[dashboard_id] = draggable_children
            state_stored_draggable_layouts[dashboard_id] = draggable_layouts
            return draggable_children, draggable_layouts, dash.no_update, state_stored_draggable_layouts
            # return draggable_children, draggable_layouts, state_stored_draggable_children, state_stored_draggable_layouts
        #     else:
        #         return dash.no_update, dash.no_update, dash.no_update, dash.no_update
        # # elif triggered_input == "draggable":
        # #     return draggable_children, draggable_layouts

        elif triggered_input == "draggable":
            ctx_triggered_props_id = ctx.triggered_prop_ids
            if "draggable.layouts" in ctx_triggered_props_id:
                new_layouts = input_draggable_layouts
                # logger.info(f"state_stored_draggable_layouts: {state_stored_draggable_layouts}")
                # logger.info(f"state_stored_draggable_children: {state_stored_draggable_children}")
                logger.info(f"dashboard_id: {dashboard_id}")
                state_stored_draggable_children[dashboard_id] = draggable_children
                state_stored_draggable_layouts[dashboard_id] = new_layouts

                return draggable_children, new_layouts, dash.no_update, state_stored_draggable_layouts
                # return draggable_children, new_layouts, state_stored_draggable_children, state_stored_draggable_layouts
            else:
                return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        elif "interactive-component" in triggered_input:
            logger.info("Interactive component triggered")
            logger.info("Interactive component values: {}".format(interactive_component_values))

            new_children = update_interactive_component(
                stored_metadata, interactive_components_dict, draggable_children, switch_state=edit_dashboard_mode_button, TOKEN=TOKEN, dashboard_id=dashboard_id
            )
            state_stored_draggable_children[dashboard_id] = new_children

            return new_children, dash.no_update, dash.no_update, dash.no_update
            # return new_children, dash.no_update, state_stored_draggable_children, dash.no_update

        # elif "edit-dashboard-mode-button" in triggered_input:
        #     logger.info(f"Edit dashboard mode button triggered: {edit_dashboard_mode_button}")
        #     new_children = list()
        #     # logger.info("Current draggable children: {}".format(draggable_children))
        #     logger.info("Len Current draggable children: {}".format(len(draggable_children)))
        #     for child in draggable_children:
        #         child = enable_box_edit_mode(child["props"]["children"][-1], edit_dashboard_mode_button)
        #         new_children.append(child)
        #         state_stored_draggable_children[dashboard_id] = new_children

        #     return new_children, dash.no_update, dash.no_update, dash.no_update
        #     # return new_children, dash.no_update, state_stored_draggable_children, dash.no_update

        elif triggered_input == "stored-draggable-layouts":
            logger.info("Stored draggable layouts triggered")
            logger.info("Input draggable layouts: {}".format(input_draggable_layouts))
            logger.info("State stored draggable layouts: {}".format(state_stored_draggable_layouts))

            if state_stored_draggable_layouts:
                if dashboard_id in state_stored_draggable_layouts:
                    children = render_dashboard(stored_metadata, dashboard_id, TOKEN)

                    return (
                        children,
                        state_stored_draggable_layouts[dashboard_id],
                        dash.no_update,
                        state_stored_draggable_layouts,
                    )
                else:
                    return dash.no_update, dash.no_update, dash.no_update, dash.no_update

            else:
                return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        elif triggered_input == "remove-box-button":
            logger.info("Remove box button clicked")
            input_id = ctx.triggered_id["index"]
            logger.info("Input ID: {}".format(input_id))

            # Use list comprehension to filter
            # logger.info("Current draggable children: {}".format(draggable_children))
            updated_children = [child for child in draggable_children if child["props"]["id"] != f"box-{input_id}"]

            # state_stored_draggable_children[dashboard_id] = updated_children
            state_stored_draggable_layouts[dashboard_id] = draggable_layouts

            # logger.info("Updated draggable children: {}".format(updated_children))

            return updated_children, draggable_layouts, dash.no_update, state_stored_draggable_layouts
            # return updated_children, draggable_layouts, state_stored_draggable_children, state_stored_draggable_layouts

        elif triggered_input == "edit-box-button":
            logger.warning("Edit box button clicked")

            input_id = ctx.triggered_id["index"]
            logger.info("Input ID: {}".format(input_id))

            component_data = get_component_data(input_id=input_id, dashboard_id=dashboard_id, TOKEN=TOKEN)
            logger.info(f"Component data: {component_data}")

            # Create the modal for editing
            edited_modal = edit_component(str(input_id), active=1, component_data=component_data, TOKEN=TOKEN)

            updated_children = []
            for child in draggable_children:
                if child["props"]["id"] == f"box-{input_id}":
                    logger.info("Found child to edit")
                    # Ensure that children is a list. If not, convert it to a list.
                    # existing_children = child["props"]["children"]
                    # if not isinstance(existing_children, list):
                    #     existing_children = [existing_children]
                    # # Append the modal to the existing children
                    # child["props"]["children"] = existing_children + [edited_modal]
                    child["props"]["children"] = edited_modal

                    # child["props"]["id"] = f"box-{input_id}-tmp"
                updated_children.append(child)

            return updated_children, draggable_layouts, dash.no_update, dash.no_update

        elif triggered_input == "btn-done-edit":
            index = ctx.triggered_id["index"]
            logger.info(f"Btn done edit clicked for index: {index}")

            edited_child = None

            for child in test_container:
                logger.info(f"Child: {child}")
                logger.info(f"Child props: {child['props']}")
                logger.info(f"Child props id: {child['props']['id']}")
                logger.info(f"Child props id index: {child['props']['id']['index']}")
                child_index = str(child["props"]["id"]["index"])

                if str(child_index) == str(index):
                    # logger.info(f"Child: {child}")

                    child_type = child["props"]["id"]["type"]

                    logger.info(f"Child type: {child_type}")

                    if child_type == "interactive-component":
                        logger.info(f"Interactive component found: {child}")
                        # WARNING: This is a temporary fix to remove the '-tmp' suffix from the id
                        if child["props"]["children"]["props"]["children"]["props"]["children"][1]["props"]["id"]["type"].endswith("-tmp"):
                            child["props"]["children"]["props"]["children"]["props"]["children"][1]["props"]["id"]["type"] = child["props"]["children"]["props"]["children"][
                                "props"
                            ]["children"][1]["props"]["id"]["type"].replace("-tmp", "")

                    logger.info(f"Child index: {child_index}")
                    logger.info(f"Child type: {child_type}")
                    # child types: card-component (w:3,h:4), interactive-component (w:6,h:6), graph-component (w:9,h:8)
                    # if child_index not in existing_ids:
                    #     child = enable_box_edit_mode(child, True)
                    logger.info(f"Child: {child}")
                    edited_child = enable_box_edit_mode(child, True)
                    logger.info(f"Edited child: {edited_child}")

            updated_children = list()
            for child in draggable_children:
                if child["props"]["id"] == f"box-{index}":
                    logger.info("Found child to edit")
                    child["props"]["children"] = edited_child
                updated_children.append(child)

            return updated_children, draggable_layouts, dash.no_update, dash.no_update

        elif triggered_input == "duplicate-box-button":
            triggered_index = ctx.triggered_id["index"]

            logger.info(f"Duplicating component with index: {triggered_index}")
            # Duplicate the component
            component_to_duplicate = None
            for child in draggable_children:
                if child["props"]["id"] == f"box-{triggered_index}":
                    component_to_duplicate = child
                    break

            if component_to_duplicate is None:
                logger.error(f"No component found with id 'box-{triggered_index}' to duplicate.")
                return dash.no_update, dash.no_update, dash.no_update, dash.no_update

            # Generate a new unique ID for the duplicated component
            new_index = generate_unique_index()
            # new_index = "200"
            child_id = f"box-{new_index}"

            # Create a deep copy of the component to duplicate
            duplicated_component = copy.deepcopy(component_to_duplicate)

            # Update the duplicated component's ID to the new ID
            duplicated_component["props"]["id"] = child_id

            # extract the metadata from the parent component
            metadata = None
            for metadata_child in stored_metadata:
                if metadata_child["index"] == triggered_index:
                    metadata = metadata_child
                    logger.info(f"Metadata found: {metadata}")
                    break
            metadata["index"] = new_index
            new_store = dcc.Store(id={"type": "stored-metadata-component", "index": new_index}, data=metadata)

            duplicated_component["props"]["children"]["props"]["children"] += [new_store]

            # Update any nested component IDs within the duplicated component
            def update_nested_ids(component, old_index, new_index):
                if isinstance(component, dict):
                    for key, value in component.items():
                        if key == "id" and isinstance(value, dict):
                            if value.get("index") == old_index:
                                value["index"] = new_index
                        elif isinstance(value, dict):
                            update_nested_ids(value, old_index, new_index)
                        elif isinstance(value, list):
                            for item in value:
                                update_nested_ids(item, old_index, new_index)
                elif isinstance(component, list):
                    for item in component:
                        update_nested_ids(item, old_index, new_index)

            update_nested_ids(duplicated_component, triggered_index, new_index)

            # Append the duplicated component to the updated children
            updated_children = list(draggable_children)
            updated_children.append(duplicated_component)

            # Calculate the new layout position
            # 'child_type' corresponds to the 'type' in the component's ID
            existing_layouts = draggable_layouts  # Current layouts before adding the new one
            n = len(updated_children)  # Position based on the number of components

            new_layout = calculate_new_layout_position("", existing_layouts, child_id, n)

            for key in required_breakpoints:
                draggable_layouts[key].append(new_layout)

            logger.info(f"Duplicated component with new id 'box-{new_index}' and assigned layout {new_layout}")

            # state_stored_draggable_children[dashboard_id] = updated_children
            state_stored_draggable_layouts[dashboard_id] = draggable_layouts

            return updated_children, draggable_layouts, dash.no_update, state_stored_draggable_layouts

        elif triggered_input == "remove-all-components-button":
            logger.info("Remove all components button clicked")
            state_stored_draggable_layouts[dashboard_id] = {}
            return [], {}, dash.no_update, state_stored_draggable_layouts
            # return [], {}, {}, {}

        else:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    # @app.callback(
    #     Output({"type": "last-button", "index": MATCH}, "data", allow_duplicate=True),
    #     Input({"type": "edit-box-button", "index": MATCH}, "n_clicks"),
    #     State({"type": "last-button", "index": MATCH}, "data"),
    #     prevent_initial_call=True,
    # )
    # def update_last_button_using_edit_box_button_value(edit_button_nclicks, last_button):
    #     logger.info(f"Edit button id: {edit_button_nclicks}")
    #     logger.info(f"Last button: {last_button}")
    #     return "Figure"

    # Callback to handle Add Button clicks
    @app.callback(
        Output("test-output", "children"),
        Output("stored-add-button", "data"),
        Output("initialized-add-button", "data"),
        # Output("initialized-edit-button", "data"),
        Input("add-button", "n_clicks"),
        # Input({"type": "edit-box-button", "index": ALL}, "n_clicks"),
        State("stored-add-button", "data"),
        State("initialized-add-button", "data"),
        # State("initialized-edit-button", "data"),
        prevent_initial_call=True,
    )
    def trigger_modal(
        add_button_nclicks,
        #   edit_button_nclicks,
        stored_add_button,
        initialized_add_button,
        # initialized_edit_button,
    ):
        logger.info("\n\nTrigger modal")
        logger.info(f"n_clicks: {add_button_nclicks}")
        logger.info(f"stored_add_button: {stored_add_button}")
        logger.info(f"initialized_add_button: {initialized_add_button}")
        # logger.info(f"edit_button_nclicks: {edit_button_nclicks}")
        # logger.info(f"initialized_edit_button: {initialized_edit_button}")

        from dash import ctx

        if not initialized_add_button:
            logger.info("Initializing add button")
            return dash.no_update, dash.no_update, True
            # return dash.no_update, dash.no_update, True, dash.no_update

        # if not initialized_edit_button:
        #     logger.info("Initializing edit button")
        #     return dash.no_update, dash.no_update, dash.no_update, True

        if add_button_nclicks is None:
            logger.info("No clicks detected")
            # return dash.no_update, dash.no_update, True, dash.no_update
            return dash.no_update, dash.no_update, True

        # if edit_button_nclicks is None:
        #     logger.info("No clicks detected")
        #     return dash.no_update, dash.no_update, dash.no_update, True

        triggered_input = ctx.triggered[0]["prop_id"].split(".")[0]
        logger.info(f"triggered_input: {triggered_input}")

        if triggered_input == "add-button":
            # Update the stored add button count
            stored_add_button["count"] += 1
            logger.info(f"Updated stored_add_button: {stored_add_button}")
            index = stored_add_button["count"]
            current_draggable_children = add_new_component(str(index))

            return current_draggable_children, stored_add_button, True
            # return current_draggable_children, stored_add_button, True, dash.no_update

        # elif "edit-box-button" in triggered_input:
        #     # Generate and return the new component
        #     index = str(eval(triggered_input)["index"])
        #     logger.info(f"Edit button clicked for index: {index}")
        #     current_draggable_children = edit_component(str(index), active=0)

        #     return current_draggable_children, stored_add_button, dash.no_update, True
        else:
            logger.warning(f"Unexpected triggered_input: {triggered_input}")
            return dash.no_update, dash.no_update, True, True

    @app.callback(
        Output("interactive-values-store", "data"),
        Input({"type": "interactive-component-value", "index": ALL}, "value"),
        State({"type": "interactive-component-value", "index": ALL}, "id"),
        State({"type": "stored-metadata-component", "index": ALL}, "data"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def update_interactive_values_store(interactive_values, ids, stored_metadata, pathname):
        logger.info("Callback 'update_interactive_values_store' triggered.")
        logger.info(f"Interactive values: {interactive_values}")
        logger.info(f"Interactive ids: {ids}")
        logger.info(f"Stored metadata: {stored_metadata}")
        stored_metadata_interactive = [e for e in stored_metadata if e["component_type"] == "interactive"]
        logger.info(f"Stored metadata interactive: {stored_metadata_interactive}")

        # Extract dashboard_id from the URL pathname
        try:
            dashboard_id = pathname.split("/")[-1]
            logger.debug(f"Dashboard ID: {dashboard_id}")
        except Exception as e:
            logger.error(f"Error extracting dashboard_id from pathname '{pathname}': {e}")
            raise dash.exceptions.PreventUpdate

        # Ensure that the lengths of interactive_values, ids, and stored_metadata match
        if not (len(interactive_values) == len(ids) == len(stored_metadata_interactive)):
            logger.error("Mismatch in lengths of interactive_values, ids, and stored_metadata.")
            raise dash.exceptions.PreventUpdate

        # Combine interactive_values with their corresponding metadata
        components = []
        for value, metadata in zip(interactive_values, stored_metadata_interactive):
            if metadata is None:
                logger.warning(f"Metadata is None for a component with value: {value}")
                continue
            components.append({"value": value, "metadata": metadata, "index": metadata["index"]})

        output_data = {"interactive_components_values": components}

        logger.info(f"Output data: {output_data}")
        return output_data


def design_draggable(data, init_layout, init_children, local_data):
    # Generate core layout based on data availability

    TOKEN = local_data["access_token"]

    workflows = httpx.get(
        f"{API_BASE_URL}/depictio/api/v1/workflows/get_all_workflows",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    logger.info("Code: %s", workflows.status_code)

    workflows = workflows.json()

    logger.info(f"workflows {workflows}")

    if not workflows:
        # When there are no workflows, log information and prepare a message
        # logger.info(f"init_children {init_children}")
        logger.info(f"init_layout {init_layout}")
        # message = html.Div(["No workflows available."])
        message = html.Div(
            [
                html.Hr(),
                dmc.Center(
                    dmc.Group(
                        [
                            DashIconify(icon="feather:info", color="red", width=40),
                            dmc.Text(
                                "No data available.",
                                variant="gradient",
                                gradient={"from": "red", "to": "orange", "deg": 45},
                                style={"fontSize": 30, "textAlign": "center"},
                            ),
                        ]
                    )
                ),
                dmc.Text(
                    "Please first register workflows and data using Depictio CLI.",
                    variant="gradient",
                    gradient={"from": "red", "to": "orange", "deg": 45},
                    style={"fontSize": 25, "textAlign": "center"},
                ),
            ]
        )
        display_style = "none"  # Hide the draggable layout
        core_children = [message]
    else:
        display_style = "flex"  # Show the draggable layout
        core_children = []

    # Create the draggable layout outside of the if-else to keep it in the DOM
    draggable = dash_draggable.ResponsiveGridLayout(
        id="draggable",
        clearSavedLayout=True,
        layouts=init_layout,
        children=init_children,
        isDraggable=True,
        isResizable=True,
        # autoSize=True,
        style={
            "display": display_style,
            "flex-grow": 1,
            "width": "100%",
            "height": "100%",
        },
    )

    # Add draggable to the core children list whether it's visible or not
    core_children.append(draggable)

    # The core Div contains all elements, managing visibility as needed
    core = html.Div(core_children)

    return core
