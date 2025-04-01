from dash import html
from depictio.api.v1.configs.logging import logger
from depictio.dash.layouts.stepper import create_stepper_output, create_stepper_output_edit


def add_new_component(
    index,
    active=0,
    # component_data=None,
):
    # Trigger the stepper module
    current_draggable_children = create_stepper_output(
        index,
        active,
        # component_data,
    )

    return current_draggable_children

