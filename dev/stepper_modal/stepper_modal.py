from dash import html, dcc, Input, Output, State, ALL, MATCH, ctx, callback
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import dash
from dash_iconify import DashIconify
import dash_ag_grid as dag
import pandas as pd

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

min_step = 0
max_step = 3
active = 0

SELECTED_STYLE = {
    "display": "inline-block",
    "width": "250px",
    "height": "100px",
    "border": "3px solid",
    "opacity": 1,
}

UNSELECTED_STYLE = {
    "display": "inline-block",
    "width": "250px",
    "height": "100px",
    "opacity": 0.65,
}


stepper_dropdowns = html.Div(
    [
        dbc.Row(
            [
                dbc.Col(
                    dmc.Select(
                        id="workflow-selection",
                        label=html.H4(
                            [
                                DashIconify(icon="flat-color-icons:workflow"),
                                "Workflow selection",
                            ]
                        ),
                        data=["Test1", "Test2"],
                    )
                ),
                dbc.Col(
                    dmc.Select(
                        id="data-collection-selection",
                        label=html.H4(
                            [
                                DashIconify(icon="bxs:data"),
                                "Data collection selection",
                            ]
                        ),
                        data=["Test3", "Test4"],
                    )
                ),
            ],
            style={"width": "80%"},
        ),
        dbc.Row(html.Div(id="dropdown-output")),
    ]
)

stepper_buttons = dbc.Row(
    [
        dbc.Col(
            dmc.Button(
                "Figure",
                id={
                    "type": "btn-option",
                    # "index": n,
                    "value": "Figure",
                },
                n_clicks=0,
                # style={
                #     "display": "inline-block",
                #     "width": "250px",
                #     "height": "100px",
                # },
                style=UNSELECTED_STYLE,
                size="xl",
                color="grape",
                leftIcon=DashIconify(icon="mdi:graph-box"),
            )
        ),
        dbc.Col(
            dmc.Button(
                "Card",
                id={
                    "type": "btn-option",
                    # "index": n,
                    "value": "Card",
                },
                n_clicks=0,
                # style={
                #     "display": "inline-block",
                #     "width": "250px",
                #     "height": "100px",
                # },
                style=UNSELECTED_STYLE,
                size="xl",
                color="violet",
                leftIcon=DashIconify(icon="formkit:number", color="white"),
            )
        ),
        dbc.Col(
            dmc.Button(
                "Interaction",
                id={
                    "type": "btn-option",
                    # "index": n,
                    "value": "Interactive",
                },
                n_clicks=0,
                # style={
                #     "display": "inline-block",
                #     "width": "250px",
                #     "height": "100px",
                # },
                style=UNSELECTED_STYLE,
                size="xl",
                color="indigo",
                leftIcon=DashIconify(icon="bx:slider-alt", color="white"),
            )
        ),
    ]
)

app.layout = html.Div(
    [
        dmc.Stepper(
            id="stepper-basic-usage",
            active=active,
            # color="green",
            breakpoint="sm",
            children=[
                dmc.StepperStep(
                    label="First step",
                    description="Create an account",
                    children=stepper_buttons,
                    id="stepper-step-1",
                ),
                dmc.StepperStep(
                    label="Second step",
                    description="Verify email",
                    children=stepper_dropdowns,
                    id="stepper-step-2",
                ),
                dmc.StepperStep(
                    label="Final step",
                    description="Get full access",
                    children=dmc.Text(
                        "Step 3 content: Get full access", align="center"
                    ),
                    id="stepper-step-3",
                ),
                dmc.StepperCompleted(
                    children=dmc.Text(
                        "Completed, click back button to get to previous step",
                        align="center",
                    ),
                ),
            ],
        ),
        dmc.Group(
            position="center",
            mt="xl",
            children=[
                dmc.Button("Back", id="back-basic-usage", variant="default"),
                dmc.Button("Next step", id="next-basic-usage"),
            ],
        ),
    ]
)


@app.callback(
    Output("dropdown-output", "children"),
    Input("workflow-selection", "value"),
    Input("data-collection-selection", "value"),
    prevent_initial_call=True,
)
def update_step_2(workflow_selection, data_collection_selection):
    if workflow_selection is not None and data_collection_selection is not None:
        df = pd.read_csv(
            "https://raw.githubusercontent.com/plotly/datasets/master/wind_dataset.csv"
        )

        columnDefs = [
            {"field": "direction"},
            {"field": "strength"},
            {"field": "frequency"},
        ]

        grid = dag.AgGrid(
            id="get-started-example-basic",
            rowData=df.to_dict("records"),
            columnDefs=columnDefs,
        )
        return grid
    else:
        return html.Div()


@app.callback(
    [
        Output({"type": "btn-option", "value": "Figure"}, "style"),
        Output({"type": "btn-option", "value": "Card"}, "style"),
        Output({"type": "btn-option", "value": "Interactive"}, "style"),
    ],
    [
        Input({"type": "btn-option", "value": "Figure"}, "n_clicks"),
        Input({"type": "btn-option", "value": "Card"}, "n_clicks"),
        Input({"type": "btn-option", "value": "Interactive"}, "n_clicks"),
    ],
    prevent_initial_call=True,
)
def update_button_style(figure_clicks, card_clicks, interactive_clicks):
    ctx_triggered = dash.callback_context.triggered

    # Reset all buttons to unselected style
    figure_style = UNSELECTED_STYLE
    card_style = UNSELECTED_STYLE
    interactive_style = UNSELECTED_STYLE

    # Check which button was clicked and update its style
    if ctx_triggered:
        button_id = ctx_triggered[0]["prop_id"].split(".")[0]
        button_value = eval(button_id)["value"]

        if button_value == "Figure":
            figure_style = SELECTED_STYLE
        elif button_value == "Card":
            card_style = SELECTED_STYLE
        elif button_value == "Interactive":
            interactive_style = SELECTED_STYLE

    return figure_style, card_style, interactive_style


@app.callback(
    Output("stepper-basic-usage", "active"),
    Input("back-basic-usage", "n_clicks"),
    Input("next-basic-usage", "n_clicks"),
    State("stepper-basic-usage", "active"),
    prevent_initial_call=True,
)
def update(back, next_, current):
    button_id = ctx.triggered_id
    step = current if current is not None else active
    if button_id == "back-basic-usage":
        step = step - 1 if step > min_step else step
    else:
        step = step + 1 if step < max_step else step
    return step


if __name__ == "__main__":
    app.run_server(debug=True)
