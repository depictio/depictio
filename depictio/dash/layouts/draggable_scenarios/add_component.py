from depictio.dash.layouts.stepper import create_stepper_output


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
