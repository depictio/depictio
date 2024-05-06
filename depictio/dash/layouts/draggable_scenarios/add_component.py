from dash import html
from depictio.api.v1.configs.config import logger
from depictio.dash.layouts.stepper import create_stepper_output

def add_new_component(
    index
):
    # Retrieve index of the button that was clicked - this is the number of the plot

    active = 0

    # Trigger the stepper module
    current_draggable_children = create_stepper_output(
        index,
        active,
    )

    # import dash_bootstrap_components as dbc
    # current_draggable_children = html.Div(
    #     [
    #         dbc.Button("Done", id={"type": "btn-done", "index": index}),
    #         html.Div(html.Div(f"TEST-{index}", id={"type": "TEST", "index": index}), id={"type": "component-container", "index": index}),
    #     ]
    # )
    # logger.info(f"Current draggable children: {current_draggable_children}")

    return current_draggable_children

