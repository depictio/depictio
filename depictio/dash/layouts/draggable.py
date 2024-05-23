import dash_mantine_components as dmc
from dash_iconify import DashIconify
import dash_draggable
from dash import html, Input, Output, State, ALL
import dash
import httpx


from depictio.dash.layouts.draggable_scenarios.add_component import add_new_component
from depictio.api.v1.configs.config import API_BASE_URL, TOKEN, logger
from depictio.dash.layouts.draggable_scenarios.interactive_component_update import update_interactive_component
from depictio.dash.layouts.header import enable_box_edit_mode


# Mapping of component types to their respective dimensions (width and height)
component_dimensions = {"card-component": {"w": 3, "h": 4}, "interactive-component": {"w": 6, "h": 6}, "graph-component": {"w": 9, "h": 8}}


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
        Input("remove-all-components-button", "n_clicks"),
        State("toggle-interactivity-button", "checked"),
        State("edit-dashboard-mode-button", "checked"),
        Input("edit-dashboard-mode-button", "checked"),
        prevent_initial_call=True,
    )
    def populate_draggable(
        btn_done_clicks,
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
        remove_all_components_button,
        toggle_interactivity_button,
        edit_dashboard_mode_button,
        input_edit_dashboard_mode_button,
    ):
        logger.info("btn_done_clicks: {}".format(btn_done_clicks))
        logger.info("stored_add_button: {}".format(stored_add_button))

        ctx = dash.callback_context

        logger.info("CTX: {}".format(ctx))
        # logger.info("CTX triggered: {}".format(ctx.triggered))
        logger.info("CTX triggered_id: {}".format(ctx.triggered_id))
        logger.info("TYPE CTX triggered_id: {}".format(type(ctx.triggered_id)))
        logger.info("CTX triggered_props_id: {}".format(ctx.triggered_prop_ids))
        # logger.info("CTX args_grouping: {}".format(ctx.args_grouping))
        # logger.info("CTX inputs: {}".format(ctx.inputs))
        # logger.info("CTX inputs_list: {}".format(ctx.inputs_list))
        # logger.info("CTX states: {}".format(ctx.states))
        # logger.info("CTX states_list: {}".format(ctx.states_list))

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

        logger.info("Interactive component values: {}".format(interactive_component_values))
        logger.info("Interactive component ids: {}".format(interactive_component_ids))
        stored_metadata_interactive = [e for e in stored_metadata if e["component_type"] == "interactive"]

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
            # logger.info("TOTOTOOTO: Draggable children {}".format(draggable_children))

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
            required_breakpoints = ["xl", "lg", "sm", "md", "xs", "xxs"]
            for bp in required_breakpoints:
                if bp not in draggable_layouts:
                    draggable_layouts[bp] = []

            for child in test_container:
                # logger.info(f"Child: {child}")
                child_index = int(child["props"]["id"]["index"])
                child_type = child["props"]["id"]["type"]
                logger.info(f"Child index: {child_index}")
                logger.info(f"Child type: {child_type}")
                # child types: card-component (w:3,h:4), interactive-component (w:6,h:6), graph-component (w:9,h:8)
                if child_index not in existing_ids:
                    child = enable_box_edit_mode(child, True)
                    draggable_children.append(child)
                    child_id = f"box-{str(child_index)}"

                    # Calculate layout item position and size based on type
                    new_layout_item = calculate_new_layout_position(child_type, draggable_layouts, child_id, n)

                    # Update necessary breakpoints, this example only updates 'lg' for simplicity
                    draggable_layouts["lg"].append(new_layout_item)

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
            return draggable_children, draggable_layouts, draggable_children, draggable_layouts
        #     else:
        #         return dash.no_update, dash.no_update, dash.no_update, dash.no_update
        # # elif triggered_input == "draggable":
        # #     return draggable_children, draggable_layouts

        elif triggered_input == "draggable":
            ctx_triggered_props_id = ctx.triggered_prop_ids
            if "draggable.layouts" in ctx_triggered_props_id:
                new_layouts = input_draggable_layouts
                return draggable_children, new_layouts, draggable_children, new_layouts
            else:
                return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        elif "interactive-component" in triggered_input:
            logger.info("Interactive component triggered")
            logger.info("Interactive component values: {}".format(interactive_component_values))

            new_children = update_interactive_component(stored_metadata, interactive_components_dict, draggable_children, switch_state=edit_dashboard_mode_button)
            return new_children, dash.no_update, new_children, dash.no_update

        elif "edit-dashboard-mode-button" in triggered_input:
            logger.info(f"Edit dashboard mode button triggered: {edit_dashboard_mode_button}")
            new_children = list()
            # logger.info("Current draggable children: {}".format(draggable_children))
            logger.info("Len Current draggable children: {}".format(len(draggable_children)))
            for child in draggable_children:
                child = enable_box_edit_mode(child["props"]["children"][-1], edit_dashboard_mode_button)
                new_children.append(child)
            return new_children, dash.no_update, new_children, dash.no_update

        elif triggered_input == "stored-draggable-children":
            if state_stored_draggable_layouts and state_stored_draggable_children:
                return (
                    state_stored_draggable_children,
                    state_stored_draggable_layouts,
                    state_stored_draggable_children,
                    state_stored_draggable_layouts,
                )

            else:
                return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        elif triggered_input == "remove-box-button":
            logger.info("Remove box button clicked")
            input_id = ctx.triggered_id["index"]
            logger.info("Input ID: {}".format(input_id))

            # Use list comprehension to filter
            # logger.info("Current draggable children: {}".format(draggable_children))
            updated_children = [child for child in draggable_children if child["props"]["id"] != f"box-{input_id}"]
            # logger.info("Updated draggable children: {}".format(updated_children))

            return updated_children, draggable_layouts, updated_children, draggable_layouts

        elif triggered_input == "remove-all-components-button":
            logger.info("Remove all components button clicked")
            return [], {}, [], {}

        else:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    @app.callback(
        Output("test-output", "children"),
        Output("stored-add-button", "data"),
        Input("add-button", "n_clicks"),
        State("stored-add-button", "data"),
        prevent_initial_call=True,
    )
    def trigger_modal(add_button_nclicks, stored_add_button):
        logger.info("\n\n")
        logger.info("Trigger modal")
        logger.info("n_clicks: {}".format(add_button_nclicks))
        logger.info("stored_add_button: {}".format(stored_add_button))
        # update the stored add button count using current value + n_clicks - warning: do not reuse the same n_clicks value multiple times
        stored_add_button["count"] += 1
        logger.info("Updated stored_add_button: {}".format(stored_add_button))
        index = stored_add_button["count"]
        # Generate index from the number of clicks
        # index = add_button_nclicks
        current_draggable_children = add_new_component(str(index))

        return current_draggable_children, stored_add_button

    # @app.callback(
    #     [
    #         Output("test-output", "children"),
    #         # Output("draggable", "children"),
    #         # Output("draggable", "layouts"),
    #         # Output("stored-layout", "data"),
    #         # Output("stored-children", "data"),
    #         # Output("stored-edit-dashboard-mode-button", "data"),
    #         # Output("stored-add-button", "data"),
    #     ],
    #     [
    #         Input(
    #             {
    #                 "type": "btn-done",
    #                 "index": dash.dependencies.ALL,
    #             },
    #             "n_clicks",
    #         ),
    #         State(
    #             {
    #                 "type": "interactive-component",
    #                 "index": dash.dependencies.ALL,
    #             },
    #             "id",
    #         ),
    #         State(
    #             {
    #                 "type": "stored-metadata-component",
    #                 "index": dash.dependencies.ALL,
    #             },
    #             "data",
    #         ),
    #         Input("add-button", "n_clicks"),
    #         Input("edit-dashboard-mode-button", "checked"),
    #         State("stored-add-button", "data"),
    #         Input(
    #             {"type": "remove-box-button", "index": dash.dependencies.ALL},
    #             "n_clicks",
    #         ),
    #         Input(
    #             {
    #                 "type": "interactive-component",
    #                 "index": dash.dependencies.ALL,
    #             },
    #             "value",
    #         ),
    #         Input("stored-layout", "data"),
    #         Input("stored-children", "data"),
    #         Input("draggable", "layouts"),
    #     ],
    #     [
    #         State("test-input", "children"),
    #         State("test-input", "style"),
    #         State("stored-layout", "data"),
    #         State("stored-children", "data"),
    #         State("stored-edit-dashboard-mode-button", "data"),
    #         State("toggle-interactivity-button", "checked"),
    #         Input("remove-all-components-button", "n_clicks"),
    #     ],
    #     prevent_initial_call=True,
    # )
    # def update_draggable_children(
    #     *args,
    # ):
    #     # Getting the arguments

    #     btn_done = args[0]
    #     interactive_component_ids = args[1]
    #     stored_metadata = args[2]
    #     add_button_nclicks = args[3]
    #     switch_state = args[4]
    #     stored_add_button = args[5]
    #     remove_box_button_values = args[6]
    #     interactive_component_values = args[7]
    #     stored_layout_data = args[8]
    #     stored_children_data = args[9]  # Commented out, adjust if including it again
    #     new_layouts = args[10]
    #     current_draggable_children = args[11]
    #     current_draggable_children = []
    #     current_layouts = args[12]
    #     current_layouts = {}
    #     stored_layout = args[13]
    #     stored_figures = args[14]  # Commented out, adjust if including it again
    #     stored_edit_dashboard = args[15]
    #     toggle_interactivity_button = args[16]
    #     remove_all_components_button = args[17]

    #     # Check if the callback was triggered by an input or a state
    #     ctx = dash.callback_context
    #     ctx_triggered = ctx.triggered
    #     logger.info("\n\n")
    #     logger.info("CTX triggered: {}".format(ctx_triggered))
    #     triggered_input = ctx.triggered[0]["prop_id"].split(".")[0]
    #     logger.info("triggered_input : {}".format(triggered_input))
    #     logger.info("Switch state: {}".format(switch_state))
    #     # Set the switch state index to 0 if switch_state is True, else set it to -1

    #     # Create a dictionary to store the values of the interactive components
    #     stored_metadata_interactive = [e for e in stored_metadata if e["component_type"] == "interactive_component"]
    #     interactive_components_dict = {
    #         id["index"]: {"value": value, "metadata": metadata}
    #         for (id, value, metadata) in zip(
    #             interactive_component_ids,
    #             interactive_component_values,
    #             stored_metadata_interactive,
    #         )
    #     }

    #     # Check if the value of the interactive component is not None
    #     check_value = False
    #     if "interactive-component" in triggered_input:
    #         triggered_input_eval = ast.literal_eval(triggered_input)
    #         triggered_input_eval_index = int(triggered_input_eval["index"])

    #         value = interactive_components_dict[triggered_input_eval_index]["value"]
    #         # Handle the case of the TextInput component
    #         if interactive_components_dict[triggered_input_eval_index]["metadata"]["interactive_component_type"] != "TextInput":
    #             check_value = True if value is not None else False
    #         else:
    #             check_value = True if value is not "" else False

    #     # Create a dictionary to store the values of the other components
    #     other_components_dict = {
    #         id["index"]: {"value": value, "metadata": metadata}
    #         for (id, value, metadata) in zip(
    #             interactive_component_ids,
    #             interactive_component_values,
    #             stored_metadata_interactive,
    #         )
    #     }

    #     new_draggable_children = []

    #     logger.info("Current draggable children: {}".format(current_draggable_children))

    #     # if type(current_draggable_children) is list:
    #     #     for child in current_draggable_children:
    #     #         for sub_child in child["props"]["children"]:
    #     #             if sub_child["props"]["id"]["type"] == "add-content":
    #     #                 child["props"]["children"] = [sub_child]
    #     #                 continue

    #     max_depth, deepest_type = analyze_structure_and_get_deepest_type(current_draggable_children)
    #     logger.info("\n\n")
    #     logger.info(f"Max depth: {max_depth}")
    #     logger.info(f"Deepest type: {deepest_type}")

    #     # Add a new box to the dashboard
    #     if triggered_input == "add-button":
    #         current_draggable_children, current_layouts, stored_add_button = add_new_component(
    #             add_button_nclicks,
    #             stored_add_button,
    #             current_draggable_children,
    #             current_layouts,
    #             stored_edit_dashboard,
    #             ctx,
    #         )

    #         return current_draggable_children
    #         # )
    #     # [], {}
    #     # current_draggable_children,
    #     # current_layouts,
    #     # [],
    #     # # current_layouts,
    #     # [],
    #     # # current_draggable_children,
    #     # stored_edit_dashboard,
    #     # stored_add_button,
    #     # # elif "btn-done" in triggered_input:
    #     # #     logger.info("\n\n\n")
    #     # #     logger.info(f"btn-done {btn_done}")

    #     # #     max_depth, deepest_type = analyze_structure_and_get_deepest_type(

    #     # #     return (
    #     # #         current_draggable_children,
    #     # #         current_layouts,
    #     # #         stored_layout,
    #     # #         stored_figures,
    #     # #         stored_edit_dashboard,
    #     # #         stored_add_button,
    #     # #     )

    #     # elif "interactive-component" in triggered_input and check_value and toggle_interactivity_button:
    #     #     updated_draggable_children = update_interactive_component(stored_metadata, interactive_components_dict, plotly_vizu_dict, join_deltatables, current_draggable_children)

    #     #     # output_children = deepcopy(updated_draggable_children)

    #     #     # with open("/app/data/interactive-component.json", "w") as file:
    #     #     #     json.dump(serialize_dash_component(output_children), file, indent=4)

    #     #     return (
    #     #         updated_draggable_children,
    #     #         current_layouts,
    #     #         # current_layouts,
    #     #         # updated_draggable_children,
    #     #         # stored_edit_dashboard,
    #     #         # stored_add_button,
    #     #     )
    #     # # if the remove button was clicked, return an empty list to remove all the plots

    #     # # elif "remove-" in triggered_input and [e for e in remove_box_button_values if e]:
    #     # #     print("\nREMOVE")
    #     # #     print("Triggered Input:", triggered_input)

    #     # #     input_id_dict = ast.literal_eval(triggered_input)
    #     # #     input_id = input_id_dict["index"]
    #     # #     print("Input ID:", input_id)

    #     # #     # Use list comprehension to filter
    #     # #     current_draggable_children = [child for child in current_draggable_children if child["props"]["id"] != input_id]

    #     # #     # elif "remove-" in triggered_input and [e for e in args[-10] if e]:
    #     # #     #     print("\nREMOVE")
    #     # #     #     print(triggered_input, type(triggered_input))
    #     # #     #     # print(current_draggable_children)
    #     # #     #     input_id = ast.literal_eval(triggered_input)["index"]
    #     # #     #     print(input_id)

    #     # #     #     # new_filter_dict = filter_dict
    #     # #     #     # print(new_filter_dict)

    #     # #     #     # Use a list comprehension to filter out the child with the matching ID
    #     # #     #     current_draggable_children = [
    #     # #     #         child for child in current_draggable_children
    #     # #     #         if "-".join(child["props"]["id"].split("-")[1:]) != "-".join(input_id.split("-")[1:])
    #     # #     #     ]
    #     # #     # for child in current_draggable_children:
    #     # #     #     print(child)
    #     # #     #     # print("-".join(child["props"]["id"].split("-")[1:]))
    #     # #     #     # print("-".join(input_id.split("-")[1:]))
    #     # #     #     if "-".join(child["props"]["id"].split("-")[1:]) == "-".join(
    #     # #     #         input_id.split("-")[1:]
    #     # #     #     ):
    #     # #     #         current_draggable_children.remove(child)
    #     # #     #         input_id = "-".join(input_id.split("-")[2:])

    #     # #     #         # Remove the corresponding entry from filter dictionary
    #     # #     #         tmp_input_id = "-".join(input_id.split("-")[1:])
    #     # #     #         if "-".join(input_id.split("-")[1:]) in new_filter_dict:
    #     # #     #             del new_filter_dict[tmp_input_id]
    #     # #     #         print(new_filter_dict)

    #     # #     # updated_draggable_children = []

    #     # #     # for j, child in enumerate(current_draggable_children):
    #     # #     #     if child["props"]["id"].replace("draggable-", "") == input_id:
    #     # #     #         updated_draggable_children.append(child)
    #     # #     #     elif (
    #     # #     #         child["props"]["id"].replace("draggable-", "") != input_id
    #     # #     #         and "-input" not in child["props"]["id"]
    #     # #     #     ):
    #     # #     #         # print(child["props"]["id"]["index"])
    #     # #     #         index = -1 if switch_state is True else 0
    #     # #     #         graph = child["props"]["children"][index]
    #     # #     #         if type(graph["props"]["id"]) is str:
    #     # #     #             print("TEST")
    #     # #     #             # Extract the figure type and its corresponding function
    #     # #     #             figure_type = "-".join(graph["props"]["id"].split("-")[2:])
    #     # #     #             graph_id = graph["props"]["id"]
    #     # #     #             updated_fig = create_initial_figure(
    #     # #     #                 df,
    #     # #     #                 figure_type,
    #     # #     #                 input_id="-".join(input_id.split("-")[2:]),
    #     # #     #                 filter=new_filter_dict,
    #     # #     #             )

    #     # #     #             if "-card" in graph_id:
    #     # #     #                 graph["props"]["children"] = updated_fig

    #     # #     #             else:
    #     # #     #                 graph["props"]["figure"] = updated_fig
    #     # #     #             rm_button = dbc.Button(
    #     # #     #                 "Remove",
    #     # #     #                 id={
    #     # #     #                     "type": "remove-button",
    #     # #     #                     "index": child["props"]["id"],
    #     # #     #                 },
    #     # #     #                 color="danger",
    #     # #     #             )
    #     # #     #             edit_button = dbc.Button(
    #     # #     #                 "Edit",
    #     # #     #                 id={
    #     # #     #                     "type": "edit-button",
    #     # #     #                     "index": child["props"]["id"],
    #     # #     #                 },
    #     # #     #                 color="secondary",
    #     # #     #                 style={"margin-left": "10px"},
    #     # #     #             )
    #     # #     #             children = (
    #     # #     #                 [rm_button, edit_button, graph]
    #     # #     #                 if switch_state is True
    #     # #     #                 else [graph]
    #     # #     #             )
    #     # #     #             updated_child = html.Div(
    #     # #     #                 children=children,
    #     # #     #                 id=child["props"]["id"],
    #     # #     #             )

    #     # #     #             updated_draggable_children.append(updated_child)
    #     # #     #     else:
    #     # #     #         updated_draggable_children.append(child)

    #     # #     return (
    #     # #         current_draggable_children,
    #     # #         new_layouts,
    #     # #         # selected_year,
    #     # #         new_layouts,
    #     # #         current_draggable_children,
    #     # #         stored_edit_dashboard,
    #     # #         stored_add_button,
    #     # #         # selected_year,
    #     # #     )
    #     # #     # return (
    #     # #     #     updated_draggable_children,
    #     # #     #     current_layouts,
    #     # #     #     current_layouts,
    #     # #     #     updated_draggable_children,
    #     # #     # )

    #     # # elif "remove-all-components-button" in triggered_input:
    #     # #     return (
    #     # #         [],
    #     # #         {},
    #     # #         {},
    #     # #         [],
    #     # #         stored_edit_dashboard,
    #     # #         stored_add_button,
    #     # #     )

    #     # # elif triggered_input == "stored-layout" or triggered_input == "stored-children":
    #     # #     if stored_layout_data and stored_children_data:
    #     # #         return (
    #     # #             stored_children_data,
    #     # #             stored_layout_data,
    #     # #             stored_layout_data,
    #     # #             stored_children_data,
    #     # #             stored_edit_dashboard,
    #     # #             stored_add_button,
    #     # #         )
    #     # #     else:
    #     # #         # Load data from the file if it exists
    #     # #         # loaded_data = None
    #     # #         loaded_data = load_depictio_data()
    #     # #         if loaded_data:
    #     # #             return (
    #     # #                 loaded_data["stored_children_data"],
    #     # #                 loaded_data["stored_layout_data"],
    #     # #                 loaded_data["stored_layout_data"],
    #     # #                 loaded_data["stored_children_data"],
    #     # #                 stored_edit_dashboard,
    #     # #                 stored_add_button,
    #     # #             )
    #     # #         else:
    #     # #             return (
    #     # #                 current_draggable_children,
    #     # #                 {},
    #     # #                 stored_layout,
    #     # #                 stored_figures,
    #     # #                 stored_edit_dashboard,
    #     # #                 stored_add_button,
    #     # #             )

    #     # elif triggered_input == "draggable":
    #     #     # for child in current_draggable_children:
    #     #     logger.info(f"current_draggable_children: {current_draggable_children}")
    #     #     logger.info(f"current_layout: {current_layouts}")
    #     #     #     print(child)
    #     #     return current_draggable_children
    #     # (
    #     #         # dash.no_update,
    #     #         current_draggable_children
    #     #         # new_layouts,
    #     #         # selected_year,
    #     #         # new_layouts,
    #     #         # dash.no_update,
    #     #         # # current_draggable_children,
    #     #         # stored_edit_dashboard,
    #     #         # stored_add_button,
    #     #         # selected_year,
    #     #     )

    #     # # div_index = 4 if box_type == "segmented-control-visu-graph" else 2
    #     # # if box_type:
    #     # #     if box_type == "segmented-control-visu-graph":
    #     # #         child = children[div_index]["props"]["children"][0]["props"][
    #     # #             "children"
    #     # #         ]  # Figure
    #     # #         child["props"]["id"]["type"] = (
    #     # #             "updated-" + child["props"]["id"]["type"]
    #     # #         )  # Figure

    #     # #         # print(child)
    #     # #         print("OK")
    #     # #     elif box_type == "card":
    #     # #         # print(children)
    #     # #         child = children[div_index]["props"]["children"][1]["props"]["children"][
    #     # #             1
    #     # #         ]  # Card
    #     # #         print(child)
    #     # #         child["props"]["children"]["props"]["id"]["type"] = (
    #     # #             "updated-" + child["props"]["children"]["props"]["id"]["type"]
    #     # #         )  # Figure
    #     # #     elif box_type == "input":
    #     # #         # print(children)
    #     # #         child = children[div_index]["props"]["children"][1]["props"]["children"][
    #     # #             1
    #     # #         ]  # Card
    #     # #         print(child)
    #     # #         child["props"]["children"]["props"]["id"]["type"] = (
    #     # #             "updated-" + child["props"]["children"]["props"]["id"]["type"]

    #     # # edit_button = dmc.Button(
    #     # #     "Edit",
    #     # #     id={
    #     # #         "type": "edit-button",
    #     # #         "index": f"edit-{btn_index}",
    #     # #     },
    #     # #     color="gray",
    #     # #     variant="filled",
    #     # #     leftIcon=DashIconify(icon="basil:edit-solid", color="white"),
    #     # # )

    #     # # remove_button = dmc.Button(
    #     # #     "Remove",
    #     # #     id={"type": "remove-button", "index": f"remove-{btn_index}"},
    #     # #     color="red",
    #     # #     variant="filled",
    #     # #     leftIcon=DashIconify(icon="jam:trash", color="white"),
    #     # # )

    #     # # new_draggable_child = html.Div(
    #     # #     [
    #     # #         html.Div([remove_button, edit_button]),
    #     # #         child,
    #     # #     ],
    #     # #     id=f"draggable-{btn_id}",
    #     # # )

    #     # # elif triggered_input == "edit-dashboard-mode-button":
    #     # #     for child in current_draggable_children:
    #     # #         # Get the deepest element type
    #     # #         (
    #     # #             max_depth,
    #     # #             deepest_element_type,
    #     # #         ) = analyze_structure_and_get_deepest_type(child)
    #     # #         # print("\n")
    #     # #         # print("analyze_structure_and_get_deepest_type")
    #     # #         # print(max_depth, deepest_element_type)

    #     # #         if deepest_element_type in ["graph", "table-aggrid", "card-value", "interactive-component", "iframe-jbrowse"]:
    #     # #             if not switch_state:
    #     # #                 child["props"]["children"][0]["props"]["children"]["props"]["children"] = [child["props"]["children"][0]["props"]["children"]["props"]["children"][-1]]
    #     # #             else:
    #     # #                 child["props"]["children"][0]["props"]["children"]["props"]["children"] = [
    #     # #                     dmc.Button(
    #     # #                         "Remove",
    #     # #                         id={"type": "remove-box-button", "index": str(child["props"]["children"][0]["props"]["children"]["props"]["children"][-1]["props"]["id"]["index"])},
    #     # #                         color="red",
    #     # #                         leftIcon=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
    #     # #                     ),
    #     # #                     child["props"]["children"][0]["props"]["children"]["props"]["children"][-1],
    #     # #                 ]
    #     # #         # elif deepest_element_type == "iframe-jbrowse":
    #     # #         #     if not switch_state:
    #     # #         #         child["props"]["children"][0]["props"]["children"]["props"]["children"] = [child["props"]["children"][0]["props"]["children"]["props"]["children"][-1]]
    #     # #         #     else:
    #     # #         #         child["props"]["children"][0]["props"]["children"]["props"]["children"] = [
    #     # #         #             dmc.Button(
    #     # #         #                 "Remove",
    #     # #         #                 id={"type": "remove-box-button", "index": str(child["props"]["children"][0]["props"]["children"]["props"]["children"][-1]["props"]["id"]["index"])},
    #     # #         #                 color="red",
    #     # #         #                 leftIcon=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
    #     # #         #             ),
    #     # #         #             child["props"]["children"][0]["props"]["children"]["props"]["children"][-1],
    #     # #         #         ]

    #     # #     # print("\n\n")

    #     # #     # switch_state = True if len(ctx.triggered[0]["value"]) > 0 else False
    #     # #     # print(switch_state)
    #     # #     # print(stored_edit_dashboard)
    #     # #     # print(current_draggable_children)
    #     # #     # assuming the switch state is added as the first argument in args
    #     # #     # updated_draggable_children = []
    #     # #     # updated_draggable_children = current_draggable_children
    #     # #     # print("\n\n")
    #     # #     # print("edit-dashboard-mode-button")
    #     # #     # print(switch_state)
    #     # #     # print(stored_edit_dashboard)

    #     # #     # stored_edit_dashboard = switch_state

    #     # #     # # analyze_structure(current_draggable_children)
    #     # #     # # print(current_draggable_children[0]["props"]["children"])
    #     # #     # # print(len(current_draggable_children[0]["props"]["children"]))
    #     # #     # # print(
    #     # #     # #     current_draggable_children[0]["props"]["children"][:-1],
    #     # #     # #     type(current_draggable_children[0]["props"]["children"][:-1]),
    #     # #     # #     len(current_draggable_children[0]["props"]["children"][:-1]),
    #     # #     # # )
    #     # #     # for j, child in enumerate(current_draggable_children):
    #     # #     #     for i, sub_child in enumerate(child["props"]["children"]):
    #     # #     #         if i != (len(child["props"]["children"]) - 1):
    #     # #     #             try:
    #     # #     #                 updated_sub_child = enable_box_edit_mode_dev(sub_child, switch_state)
    #     # #     #             except Exception as e:
    #     # #     #                 print(f"Error when calling enable_box_edit_mode_dev: {e}")
    #     # #     #             # print(updated_sub_child)
    #     # #     #             child["props"]["children"][i] = updated_sub_child
    #     # #     #         else:
    #     # #     #             child["props"]["children"][i] = sub_child
    #     # #     #     updated_draggable_children.append(child)
    #     # #     # if j != (len(current_draggable_children)-1):
    #     # #     #         print("\n\n")
    #     # #     #         print("updated_child")

    #     # #     #         print(child)

    #     # #     #         print("\n\n")
    #     # #     #         print("\n\n")
    #     # #     #         print("\n\n")
    #     # #     #         print("\n\n")
    #     # #     #         print("\n\n")
    #     # #     #         analyze_structure(child)

    #     # #     #         print(child)
    #     # #     #         print(switch_state)
    #     # #     #         try:
    #     # #     # updated_child = enable_box_edit_mode_dev(child, switch_state)
    #     # #     #         except Exception as e:
    #     # #     #             print(f"Error when calling enable_box_edit_mode_dev: {e}")
    #     # #     #         # print(updated_child)
    #     # #     #         print("\n\n")

    #     # #     # print(len(child))
    #     # #     # print(child["props"]["id"])
    #     # #     # print(len(child["props"]["children"]))
    #     # #     # graph = child["props"]["children"][0]["props"]["children"][
    #     # #     #     -2
    #     # #     # ]  # Assuming graph is always the last child
    #     # #     #     graph = child["props"]["children"][0]["props"]["children"][0]["props"]["children"]
    #     # #     #     print(child["props"]["children"])
    #     # #     # if switch_state:  # If switch is 'on', add the remove button
    #     # #     #     # if "graph" in child["props"]["id"]:
    #     # #     #     graph = child["props"]["children"][0]
    #     # #     #     # print(graph["props"]["id"])

    #     # #     #     edit_button = dmc.Button(
    #     # #     #         "Edit",
    #     # #     #         id={
    #     # #     #             "type": "edit-button",
    #     # #     #             "index": child["props"]["id"],
    #     # #     #         },
    #     # #     #         color="gray",
    #     # #     #         variant="filled",
    #     # #     #         leftIcon=DashIconify(icon="basil:edit-solid", color="white"),
    #     # #     #     )

    #     # #     #     remove_button = dmc.Button(
    #     # #     #         "Remove",
    #     # #     #         id={"type": "remove-button", "index": child["props"]["id"]},
    #     # #     #         color="red",
    #     # #     #         variant="filled",
    #     # #     #         leftIcon=DashIconify(icon="jam:trash", color="white"),
    #     # #     #     )

    #     # #     #     updated_child = html.Div(
    #     # #     #         [
    #     # #     #             remove_button,
    #     # #     #             edit_button,
    #     # #     #             graph,
    #     # #     #         ],
    #     # #     #         id=child["props"]["id"],
    #     # #     #     )

    #     # #     #     # remove_button = dbc.Button(
    #     # #     #     #     "Remove",
    #     # #     #     #     id={
    #     # #     #     #         "type": "remove-button",
    #     # #     #     #         "index": child["props"]["id"],
    #     # #     #     #     },
    #     # #     #     #     color="danger",
    #     # #     #     # )
    #     # #     #     # edit_button = dbc.Button(
    #     # #     #     #     "Edit",
    #     # #     #     #     id={
    #     # #     #     #         "type": "edit-button",
    #     # #     #     #         "index": child["props"]["id"],
    #     # #     #     #     },
    #     # #     #     #     color="secondary",
    #     # #     #     #     style={"margin-left": "10px"},
    #     # #     #     # )

    #     # #     #     # updated_child = html.Div(
    #     # #     #     #     [remove_button, edit_button, graph],
    #     # #     #     #     id=child["props"]["id"],
    #     # #     #     # )
    #     # #     # elif (
    #     # #     #     switch_state is False and stored_edit_dashboard["count"] == 0
    #     # #     # ):  # If switch is 'off', remove the button
    #     # #     #     graph = child["props"]["children"][0]["props"]["children"]["props"][
    #     # #     #         "children"
    #     # #     #     ][2]
    #     # #     #     # print(graph["props"]["id"])

    #     # #     #     updated_child = html.Div(
    #     # #     #         [graph],
    #     # #     #         id=child["props"]["id"],
    #     # #     #     )
    #     # #     # else:
    #     # #     #     graph = child["props"]["children"][-1]
    #     # #     #     # print(child["props"]["id"])

    #     # #     #     updated_child = html.Div(
    #     # #     #         [graph],
    #     # #     #         id=child["props"]["id"],
    #     # #     #     )
    #     # #     # updated_draggable_children.append(updated_child)
    #     # #     # else:
    #     # #     #     updated_draggable_children.append(child)
    #     # #     # updated_draggable_children.append(child)

    #     # #     return (
    #     # #         current_draggable_children,
    #     # #         new_layouts,
    #     # #         # selected_year,
    #     # #         new_layouts,
    #     # #         current_draggable_children,
    #     # #         stored_edit_dashboard,
    #     # #         stored_add_button,
    #     # #         # selected_year,
    #     # #     )

    #     # # # Add an else condition to return the current layout when there's no triggering input
    #     # else:
    #     #     raise dash.exceptions.PreventUpdate

    #     else:
    #         return dash.no_update


def design_draggable(data, init_layout, init_children):
    # # Generate core layout based on data availability
    # if not data:
    #     core = html.Div(
    #         [
    #             html.Hr(),
    #             dmc.Center(dmc.Group(
    #                 [
    #                     DashIconify(icon="feather:info", color="orange", width=45),
    #                     dmc.Text(
    #                         "No data available.",
    #                         variant="gradient",
    #                         gradient={"from": "red", "to": "yellow", "deg": 45},
    #                         style={"fontSize": 40, "textAlign": "center"},
    #                     ),
    #                 ]
    #             )),
    #             dmc.Text(
    #                 "Please first register workflows and data using Depictio CLI.",
    #                 variant="gradient",
    #                 gradient={"from": "red", "to": "yellow", "deg": 45},
    #                 style={"fontSize": 30, "textAlign": "center"},
    #             ),
    #         ]
    #     )
    # else:

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
        display_style = "block"  # Show the draggable layout
        core_children = []

    # Create the draggable layout outside of the if-else to keep it in the DOM
    draggable = dash_draggable.ResponsiveGridLayout(
        id="draggable",
        clearSavedLayout=True,
        layouts=init_layout,
        children=init_children,
        isDraggable=True,
        isResizable=True,
        style={"display": display_style},
    )

    # Add draggable to the core children list whether it's visible or not
    core_children.append(draggable)

    # The core Div contains all elements, managing visibility as needed
    core = html.Div(core_children)

    return core
