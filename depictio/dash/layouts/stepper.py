from dash import html, Input, Output, State, ALL, MATCH, ctx
import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify

# Depictio imports
from depictio.dash.utils import (
    list_data_collections_for_dropdown,
    list_workflows_for_dropdown,
)


min_step = 0
max_step = 3
active = 0

def register_callbacks_stepper(app):

    @app.callback(
        Output({"type": "modal", "index": MATCH}, "is_open"),
        [Input({"type": "btn-done", "index": MATCH}, "n_clicks")],
        prevent_initial_call=True,
    )
    def close_modal(n_clicks):
        if n_clicks > 0:
            return False
        return True

    @app.callback(
        Output({"type": "workflow-selection-label", "index": MATCH}, "data"),
        Output({"type": "workflow-selection-label", "index": MATCH}, "value"),
        Input("add-button", "n_clicks"),
        # State("stored-add-button", "data"),
        # Input("interval_long", "n_intervals"),
        # prevent_initial_call=True,
    )
    def set_workflow_options(n_clicks):
        """Define the options for the workflow dropdown

        Args:
            n_intervals (_type_): _description_

        Returns:
            _type_: _description_
        """
        print("\n\n\n")
        print("set_workflow_options")
        print(n_clicks)
        if int(n_clicks) > 0:
            # print(id)
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
        else:
            raise dash.exceptions.PreventUpdate

    @app.callback(
        Output({"type": "datacollection-selection-label", "index": MATCH}, "data"),
        Output({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
        State({"type": "workflow-selection-label", "index": MATCH}, "id"),
        # prevent_initial_call=True,
    )
    def set_datacollection_options(selected_workflow, id):
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
        # print(id)
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





    @app.callback(
        Output({"type": "stepper-basic-usage", "index": MATCH}, "active"),
        Output({"type": "next-basic-usage", "index": MATCH}, "disabled"),
        Input({"type": "back-basic-usage", "index": MATCH}, "n_clicks"),
        Input({"type": "next-basic-usage", "index": MATCH}, "n_clicks"),
        Input({"type": "workflow-selection-label", "index": MATCH}, "value"),
        Input({"type": "datacollection-selection-label", "index": MATCH}, "value"),
        Input({"type": "btn-option", "index": MATCH, "value": ALL}, "n_clicks"),
        State({"type": "stepper-basic-usage", "index": MATCH}, "active"),
        prevent_initial_call=True,
    )
    def update(back, next_, workflow_selection, data_selection, btn_component, current):



        if back is None and next_ is None:
            if workflow_selection is not None and data_selection is not None:
                disable_next = False
            else:
                disable_next = True

            return current, disable_next
        else:
            button_id = ctx.triggered_id
            step = current if current is not None else active

            if button_id["type"] == "back-basic-usage":
                step = step - 1 if step > min_step else step
                return step, False

            else:
                step = step + 1 if step < max_step else step
                return step, False


# def create_stepper_dropdowns(n):
#     """
#     Create the dropdowns for the stepper

#     Args:
#         n (_type_): _description_

#     Returns:
#         _type_: _description_
#     """
#     stepper_dropdowns = html.Div(
#         [
#             html.Hr(),
#             dbc.Row(
#                 [
#                     dbc.Col(
#                         # Workflow selection dropdown
#                         dmc.Select(
#                             id={"type": "workflow-selection-label", "index": n},
#                             label=html.H4(
#                                 [
#                                     DashIconify(icon="flat-color-icons:workflow"),
#                                     "Workflow selection",
#                                 ]
#                             ),
#                             # data=["Test1", "Test2"],
#                             style={
#                                 "height": "100%",
#                                 "display": "inline-block",
#                                 "width": "100%",
#                                 # "display": "flex",
#                                 # "flex-direction": "column",
#                                 # "flex-grow": "0",
#                             },
#                         )
#                     ),
#                     dbc.Col(
#                         # Data collection selection dropdown
#                         dmc.Select(
#                             id={
#                                 "type": "datacollection-selection-label",
#                                 "index": n,
#                             },
#                             label=html.H4(
#                                 [
#                                     DashIconify(icon="bxs:data"),
#                                     "Data collection selection",
#                                 ]
#                             ),
#                             # data=["Test3", "Test4"],
#                             style={
#                                 "height": "100%",
#                                 "width": "100%",
#                                 "display": "inline-block",
#                                 # "display": "flex",
#                                 # "flex-direction": "column",
#                                 # "flex-grow": "0",
#                             },
#                         )
#                     ),
#                 ],
#                 # style={"width": "80%"},
#             ),
#             html.Hr(),
#             dbc.Row(html.Div(id={"type": "dropdown-output", "index": n})),
#         ],
#         style={
#             "height": "100%",
#             "width": "822px",
#             # "display": "flex",
#             # "flex-direction": "column",
#             # "flex-grow": "0",
#         },
#     )
#     return stepper_dropdowns


# def create_stepper_buttons(n, data_collection_type):
#     """
#     Create the buttons for the stepper

#     Args:
#         n (_type_): _description_

#     Returns:
#         _type_: _description_
#     """

#     # IMPORTANT: TO BE UPDATED FOR EACH NEW COMPONENT


def create_stepper_output(n, active, new_plot_id, data_collection_type=None):

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

    buttons_list = html.Div(
        [
            html.Div(
                id={
                    "type": "buttons-list",
                    "index": n,
                }
            ),
            html.Div(
                id={
                    "type": "store-list",
                    "index": n,
                }
            ),
        ]
    )

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
                                        children=buttons_list,
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
