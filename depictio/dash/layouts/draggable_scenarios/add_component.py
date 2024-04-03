
import dash
from dash import html, dcc, Input, Output, State, ALL, MATCH

from depictio.api.v1.configs.config import logger
from depictio.dash.layouts.header import enable_box_edit_mode
from depictio.dash.layouts.stepper import create_stepper_output
from depictio.dash.utils import analyze_structure, analyze_structure_and_get_deepest_type

def register_callbacks_add_component(app):

    @app.callback(
        Output({"type": "add-content", "index": MATCH}, "children"),
        Output({"type": "test-container", "index": MATCH}, "children", allow_duplicate=True),
        [
            Input({"type": "btn-done", "index": MATCH}, "n_clicks"),
        ],
        [
            State({"type": "test-container", "index": MATCH}, "children"),
            State({"type": "btn-done", "index": MATCH}, "id"),
            State("stored-edit-dashboard-mode-button", "data"),
            # State({"type": "graph", "index": MATCH}, "figure"),
        ],
        prevent_initial_call=True,
    )
    def update_button(n_clicks, children, btn_id, switch_state):

        children["props"]["id"]["type"] = "updated-" + children["props"]["id"]["type"]
        # logger.info(children)

        btn_index = btn_id["index"]  # Extracting index from btn_id dict

        # switch_state_bool = True if len(switch_state) > 0 else False

        # new_draggable_child = children
        new_draggable_child = enable_box_edit_mode(children, switch_state)
        # new_draggable_child = enable_box_edit_mode(children, btn_index, switch_state_bool)
        # with open("/app/data/update_button.json", "w") as f:
        #     f.write(str(new_draggable_child))
        # analyze_structure_and_get_deepest_type(new_draggable_child, print=True)


        return new_draggable_child, []


def add_new_component(
        add_button_nclicks,
        stored_add_button,
        current_draggable_children,
        current_layouts,
        stored_edit_dashboard,
        ctx,
        
):
        # Retrieve index of the button that was clicked - this is the number of the plot
    if add_button_nclicks > stored_add_button["count"]:

        # Get the index of the plot
        n = ctx.triggered[0]["value"]
        new_plot_id = f"{n}"

        active = 0

        # Trigger the stepper module
        stepper_output = create_stepper_output(
            n,
            active,
            new_plot_id,
        )
        current_draggable_children.append(stepper_output)
        stored_add_button["count"] += 1

        # logger.info(f"Current draggable children: {current_draggable_children}")



        # Design something smarter for new layout item based on the component type
        # Get the deepest type of the component
        max_depth, deepest_type = analyze_structure_and_get_deepest_type(stepper_output)
        # logger.info(f"Deepest type: {deepest_type}")
        # logger.info(f"Max depth: {max_depth}")
        # logger.info(f"Stepper output: {stepper_output}")

        # Update the layout item based on the deepest type
        new_layout_item = {
            "i": f"{new_plot_id}",
            "x": 10 * ((len(current_draggable_children) + 1) % 2),
            "y": n * 10,
        }

        # Adjust height and width based on the deepest type
        if deepest_type == "graph":
            new_layout_item["w"] = 6
            new_layout_item["h"] = 10
        elif deepest_type == "table-aggrid":
            new_layout_item["w"] = 6
            new_layout_item["h"] = 10
        elif deepest_type in ["interactive-component", "card"]:
            new_layout_item["w"] = 3
            new_layout_item["h"] = 5
        elif deepest_type == "iframe-jbrowse":
            new_layout_item["w"] = 12
            new_layout_item["h"] = 15
        else:
            new_layout_item["w"] = 6
            new_layout_item["h"] = 5


        # TODO: update based on the component type
        # Define the default size and position for the new plot
        new_layout_item = {
            "i": f"{new_plot_id}",
            "x": 10 * ((len(current_draggable_children) + 1) % 2),
            "y": n * 10,
            "w": 6,
            "h": 5,
        }


        # Update the layouts property for both 'lg' and 'sm' sizes
        updated_layouts = {}
        for size in ["lg", "sm"]:
            if size not in current_layouts:
                current_layouts[size] = []
            current_layouts[size] = current_layouts[size] + [new_layout_item]



        # Update the stored layout data
        return (
            current_draggable_children,
            current_layouts,
            stored_add_button,
        )
    else:
        raise dash.exceptions.PreventUpdate