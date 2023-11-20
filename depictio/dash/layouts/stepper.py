from dash import html, dcc, Input, Output, State, ALL, MATCH, ctx, callback
import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify

from depictio.dash.utils import (
    SELECTED_STYLE,
    UNSELECTED_STYLE,
    list_data_collections_for_dropdown,
    list_workflows_for_dropdown,
)
from depictio.dash.modules.figure_component.frontend import create_stepper_figure_button
from depictio.dash.modules.card_component.frontend import create_stepper_card_button
from depictio.dash.modules.interactive_component.frontend import (
    create_stepper_interactive_button,
)
from depictio.dash.modules.jbrowse_component.frontend import (
    create_stepper_jbrowse_button,
)


def register_callbacks_stepper(app):
    @dash.callback(
        Output({"type": "workflow-selection-label", "index": MATCH}, "data"),
        Output({"type": "workflow-selection-label", "index": MATCH}, "value"),
        [
            Input("interval_long", "n_intervals")
        ],  # or whatever triggers the workflow dropdown to update
        # prevent_initial_call=True,
    )
    def set_workflow_options(n_intervals):
        """Define the options for the workflow dropdown

        Args:
            n_intervals (_type_): _description_

        Returns:
            _type_: _description_
        """
        tmp_data = list_workflows_for_dropdown()
        # print("\n\n\n")
        # print("set_workflow_options")

        # print(tmp_data)
        # print("\n\n\n")

        # Return the data and the first value if the data is not empty
        if tmp_data:
            return tmp_data, tmp_data[0]["value"]
        else:
            return dash.no_update

    @dash.callback(
        Output({"type": "datacollection-selection-label", "index": MATCH}, "data"),
        Output({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
        # prevent_initial_call=True,
    )
    def set_datacollection_options(selected_workflow):
        """Define the options for the data collection dropdown

        Args:
            selected_workflow (_type_): _description_

        Raises:
            dash.exceptions.PreventUpdate: _description_
            dash.exceptions.PreventUpdate: _description_

        Returns:
            _type_: _description_
        """
        # print("\n\n\n")
        # print("set_datacollection_options")
        # print(selected_workflow)
        # print("\n\n\n")
        if not selected_workflow:
            raise dash.exceptions.PreventUpdate

        tmp_data = list_data_collections_for_dropdown(selected_workflow)
        # print("set_datacollection_options")
        # print(tmp_data)

        # Return the data and the first value if the data is not empty
        if tmp_data:
            return tmp_data, tmp_data[0]["value"]
        else:
            raise dash.exceptions.PreventUpdate


def create_stepper_dropdowns(n):
    """
    Create the dropdowns for the stepper

    Args:
        n (_type_): _description_

    Returns:
        _type_: _description_
    """
    stepper_dropdowns = html.Div(
        [
            html.Hr(),
            dbc.Row(
                [
                    dbc.Col(
                        # Workflow selection dropdown
                        dmc.Select(
                            id={"type": "workflow-selection-label", "index": n},
                            label=html.H4(
                                [
                                    DashIconify(icon="flat-color-icons:workflow"),
                                    "Workflow selection",
                                ]
                            ),
                            # data=["Test1", "Test2"],
                            style={
                                "height": "100%",
                                "display": "inline-block",
                                "width": "100%",
                                # "display": "flex",
                                # "flex-direction": "column",
                                # "flex-grow": "0",
                            },
                        )
                    ),
                    dbc.Col(
                        # Data collection selection dropdown
                        dmc.Select(
                            id={
                                "type": "datacollection-selection-label",
                                "index": n,
                            },
                            label=html.H4(
                                [
                                    DashIconify(icon="bxs:data"),
                                    "Data collection selection",
                                ]
                            ),
                            # data=["Test3", "Test4"],
                            style={
                                "height": "100%",
                                "width": "100%",
                                "display": "inline-block",
                                # "display": "flex",
                                # "flex-direction": "column",
                                # "flex-grow": "0",
                            },
                        )
                    ),
                ],
                # style={"width": "80%"},
            ),
            html.Hr(),
            dbc.Row(html.Div(id={"type": "dropdown-output", "index": n})),
        ],
        style={
            "height": "100%",
            "width": "822px",
            # "display": "flex",
            # "flex-direction": "column",
            # "flex-grow": "0",
        },
    )
    return stepper_dropdowns


def create_stepper_buttons(n):
    """
    Create the buttons for the stepper

    Args:
        n (_type_): _description_

    Returns:
        _type_: _description_
    """

    # IMPORTANT: TO BE UPDATED FOR EACH NEW COMPONENT
    figure_stepper_button, figure_stepper_button_store = create_stepper_figure_button(n)
    card_stepper_button, card_stepper_button_store = create_stepper_card_button(n)
    (
        interactive_stepper_button,
        interactive_stepper_button_store,
    ) = create_stepper_interactive_button(n)
    (
        jbrowse_stepper_button,
        jbrowse_stepper_button_store,
    ) = create_stepper_jbrowse_button(n)

    store_list = [
        figure_stepper_button_store,
        card_stepper_button_store,
        interactive_stepper_button_store,
        jbrowse_stepper_button_store,
    ]

    standard_components = [
        figure_stepper_button,
        card_stepper_button,
        interactive_stepper_button,
    ]

    special_components = [jbrowse_stepper_button]

    buttons_list = [
        html.H5("Standard components", style={"margin-top": "20px"}),
        html.Hr(),
        dmc.Center(dbc.Row(standard_components)),
        html.Br(),
        html.H5("Special components", style={"margin-top": "20px"}),
        html.Hr(),
        dmc.Center(dbc.Row(special_components)),
    ]

    # print(store_list + buttons_list)

    stepper_buttons = dbc.Row(store_list + buttons_list)
    # print(stepper_buttons)
    return stepper_buttons


def create_stepper_output(n, active, new_plot_id, stepper_dropdowns, stepper_buttons):
    new_element = html.Div(
        [
            html.Div(id={"type": "add-content", "index": n}),
            dbc.Modal(
                id={"type": "modal", "index": n},
                children=[
                    dbc.ModalHeader(html.H5("Design your new dashboard component")),
                    dbc.ModalBody(
                        [
                            dmc.Stepper(
                                id={"type": "stepper-basic-usage", "index": n},
                                active=active,
                                # color="green",
                                breakpoint="sm",
                                children=[
                                    dmc.StepperStep(
                                        label="Data selection",
                                        description="Select your workflow and data collection",
                                        children=stepper_dropdowns,
                                        id={"type": "stepper-step-1", "index": n},
                                    ),
                                    dmc.StepperStep(
                                        label="Component selection",
                                        description="Select your component type",
                                        children=stepper_buttons,
                                        id={"type": "stepper-step-2", "index": n},
                                    ),
                                    dmc.StepperStep(
                                        label="Design your component",
                                        description="Customize your component as you wish",
                                        children=html.Div(
                                            id={
                                                "type": "output-stepper-step-3",
                                                "index": n,
                                            }
                                        ),
                                        id={"type": "stepper-step-3", "index": n},
                                    ),
                                    dmc.StepperCompleted(
                                        children=[
                                            dmc.Center(
                                                [
                                                    dmc.Button(
                                                        "Add to dashboard",
                                                        id={
                                                            "type": "btn-done",
                                                            "index": n,
                                                        },
                                                        n_clicks=0,
                                                        size="xl",
                                                        color="grape",
                                                        style={
                                                            "display": "block",
                                                            "align": "center",
                                                            "height": "100px",
                                                        },
                                                    ),
                                                ]
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            dmc.Group(
                                position="center",
                                mt="xl",
                                children=[
                                    dmc.Button(
                                        "Back",
                                        id={"type": "back-basic-usage", "index": n},
                                        variant="default",
                                    ),
                                    dmc.Button(
                                        "Next step",
                                        id={"type": "next-basic-usage", "index": n},
                                        disabled=True,
                                    ),
                                ],
                            ),
                        ],
                        id={"type": "modal-body", "index": n},
                        style={
                            "display": "flex",
                            "justify-content": "center",
                            "align-items": "center",
                            "flex-direction": "column",
                            "height": "100%",
                            "width": "100%",
                        },
                    ),
                ],
                is_open=True,
                size="xl",
                backdrop=False,
                style={
                    "height": "100%",
                    "width": "100%",
                    # "display": "flex",
                    # "flex-direction": "column",
                    # "flex-grow": "0",
                },
            ),
        ],
        id=new_plot_id,
    )
    return new_element
