# Import necessary libraries
from dash import dcc, html
from dash.dependencies import Input, Output, State
import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import inspect
from utils import (
    load_data,
    get_common_params,
    get_specific_params,
    get_param_info,
    get_dropdown_options,
)

# Set up Dash app with Bootstrap CSS and additional CSS file
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP, "custom.css"],
    suppress_callback_exceptions=True,
)


# Create list of workflows
workflows = ["ashleys-qc-pipeline", "nf-core-ampliseq"]

# Create dictionary mapping workflows to their options
workflow_options = {
    "ashleys-qc-pipeline": ["mosaicatcher counts statistics", "ashleys predictions"],
    "nf-core-ampliseq": ["Read Mean Quality", "Read GC Content"],
}

# Define your data sources
option_to_data_source = {
    "mosaicatcher counts statistics": "dev_design_visu/data/mosaicatcher_counts_statistics.csv",
    "ashleys predictions": "dev_design_visu/data/ashleys_predictions.csv",
    "Read Mean Quality": "dev_design_visu/data/read_mean_quality.csv",
    "Read GC Content": "dev_design_visu/data/read_gc_content.csv",
}


def read_df(data_source_url):
    df = pd.read_csv(data_source_url)
    return df


# Load data from CSV file into pandas DataFrame
# df = pd.read_csv(
#     "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
# )
print(option_to_data_source)
df = read_df(list(option_to_data_source.values())[0])
print(df)

# Define the list of Plotly visualizations
plotly_vizu_list = [px.scatter, px.line, px.bar, px.histogram, px.box]

# Map visualization function names to the functions themselves
plotly_vizu_dict = {vizu_func.__name__: vizu_func for vizu_func in plotly_vizu_list}

# Get common and specific parameters for the visualizations
common_params, common_params_names = get_common_params(plotly_vizu_list)
specific_params = get_specific_params(plotly_vizu_list, common_params)

# Generate parameter information and dropdown options
param_info = get_param_info(plotly_vizu_list)
dropdown_options = get_dropdown_options(df)

# Define the elements for the dropdown menu
dropdown_elements = ["x", "y", "color"]

# Define allowed types and the corresponding Bootstrap components
allowed_types = ["str", "int", "float", "boolean", "column"]
plotly_bootstrap_mapping = {
    "str": dbc.Input,
    "int": dbc.Input,
    "float": dbc.Input,
    "boolean": dbc.Checklist,
    "column": dcc.Dropdown,
}

# Identify the parameters not in the dropdown elements
secondary_common_params = [
    e for e in common_params_names[1:] if e not in dropdown_elements
]


app.layout = dbc.Container(
    [
        dcc.Interval(
            id="interval",
            interval=2000,  # Save slider value every 1 second
            n_intervals=0,
        ),
        html.H1(
            "Prepare your visualization",
            className="text-center mb-4",
        ),
        html.Hr(),
        dbc.Row(
            [
                dbc.Col(html.H2("Select your workflow"), width=2),
                dbc.Col(
                    dcc.Dropdown(
                        id="workflow-selector",
                        options=[
                            {"label": workflow, "value": workflow}
                            for workflow in workflows
                        ],
                        value=workflows[0],
                    ),
                    width=4,
                ),
            ]
        ),
        dbc.Row(
            [
                dbc.Col(html.H2("Select an option"), width=2),
                dbc.Col(
                    dcc.Dropdown(
                        id="wf-option-selector",
                        # Initial options are for the first workflow
                        options=[
                            {"label": option, "value": option}
                            for option in workflow_options[workflows[0]]
                        ],
                        value=workflow_options[workflows[0]][0],
                    ),
                    width=4,
                ),
            ]
        ),
        html.Hr(),
        dbc.Row(
            [
                dbc.Col(html.H2("Visualization type"), width=2),
                dbc.Col(
                    dcc.Dropdown(
                        id="visualization-type",
                        options=[
                            {"label": func.__name__, "value": func.__name__}
                            for func in plotly_vizu_list
                        ],
                        value=plotly_vizu_list[0].__name__,
                    ),
                    width=4,
                ),
                html.Hr(),
                dbc.Row(
                    [
                        dbc.Col(html.H3("X-axis"), width=1),
                        dbc.Col(
                            dcc.Dropdown(
                                id="x",
                                options=dropdown_options,
                                value=list(df.columns)[0],
                            ),
                            width=2,
                        ),
                        dbc.Col(html.H3("Y-axis"), width=1),
                        dbc.Col(
                            dcc.Dropdown(
                                id="y",
                                options=dropdown_options,
                                value=list(df.columns)[1],
                            ),
                            width=2,
                        ),
                        dbc.Col(html.H3("color"), width=1),
                        dbc.Col(
                            dcc.Dropdown(
                                id="color",
                                options=dropdown_options,
                                # value=list(df.columns)[2],
                                value=list(df.columns)[2],
                            ),
                            width=2,
                        ),
                    ],
                    justify="center",
                ),
                html.Hr(),
                dbc.Col(
                    [
                        dbc.Button(
                            "Edit",
                            id="edit-button",
                            color="primary",
                            size="lg",
                            style={"font-size": "22px"},
                        ),
                        dbc.Modal(
                            [
                                dbc.ModalHeader(
                                    html.H1(
                                        "Success!",
                                        className="text-success",
                                    )
                                ),
                                dbc.ModalBody(
                                    html.H5(
                                        "Your amazing dashboard was successfully saved!",
                                        className="text-success",
                                    ),
                                    style={"background-color": "#F0FFF0"},
                                ),
                                dbc.ModalFooter(
                                    dbc.Button(
                                        "Close",
                                        id="modal-close-button",
                                        className="ml-auto",
                                        color="success",
                                    )
                                ),
                            ],
                            id="success-modal",
                            centered=True,
                        ),
                        dbc.Button(
                            "Save",
                            id="save-button",
                            color="success",
                            style={"margin-left": "10px", "font-size": "22px"},
                            size="lg",
                            n_clicks=0,
                        ),
                    ],
                    className="d-flex justify-content-center align-items-center",
                ),
                html.Hr(),
                dbc.Row(
                    [
                        dbc.Col(
                            dcc.Graph(id="graph-container", config={"editable": True}),
                        ),
                    ],
                    className="mt-3",
                ),
            ],
            className="text-center mt-3",
            justify="center",
        ),
        html.Hr(),
        html.Tr(),
        dbc.Row(
            [
                dcc.Store("offcanvas-state-store", storage_type="session"),
                dbc.Offcanvas(
                    [
                        html.Div(id="specific-params-container"),
                    ],
                    id="modal",
                    title="Edit Menu",
                    scrollable=True,
                    # size="xl",
                    backdrop=False,
                ),
            ],
            justify="center",
        ),
        # html.Hr(),
    ],
    fluid=True,
)


# Define a callback to update the options when the workflow selection changes
@app.callback(
    Output("wf-option-selector", "options"), Input("workflow-selector", "value")
)
def update_options(workflow):
    options = workflow_options[workflow]
    return [{"label": option, "value": option} for option in options]


# Define a callback to update your df when the option selection changes
# @app.callback(
#     Output("stored-selected-dataframe", "data"), Input("wf-option-selector", "value")
# )
# def update_df(option):
#     data_source_url = option_to_data_source[option]
#     return read_df(data_source_url)


# define the callback to show/hide the modal
@app.callback(
    Output("modal", "is_open"),
    [Input("edit-button", "n_clicks"), Input("modal-close-button", "n_clicks")],
    [State("modal", "is_open")],
)
def toggle_modal(n1, n2, is_open):
    if n1 or n2:
        return not is_open
    return is_open


def generate_callback(element_id):
    @app.callback(
        Output(f"stored-{element_id}", "data"),
        Input("interval", "n_intervals"),
        State(element_id, "value"),
    )
    def save_value(n_intervals, value):
        if n_intervals == 0:
            raise dash.exceptions.PreventUpdate
        return value

    @app.callback(
        Output(element_id, "value"),
        Input(f"stored-{element_id}", "data"),
    )
    def update_value(data):
        if data is None:
            raise dash.exceptions.PreventUpdate
        return data

    return save_value, update_value


for element_id in dropdown_elements:
    # print(element_id)
    # Create dcc.Store for each dropdown element
    app.layout.children.insert(
        0, dcc.Store(id=f"stored-{element_id}", storage_type="session", data="")
    )

    # Register the save and update callbacks for each element
    save_value_callback, update_value_callback = generate_callback(element_id)
    # print(save_value_callback)
    # print(update_value_callback)
app.layout.children.insert(
    0,
    dcc.Store(id=f"stored-visualization-type", storage_type="session", data="scatter"),
)
app.layout.children.insert(
    0,
    dcc.Store(id=f"stored-workflow-selector", storage_type="session", data="scatter"),
)
# app.layout.children.insert(
#     0,
#     dcc.Store(id=f"stored-selected-dataframe", storage_type="session"),
# )
# app.layout.children.insert(
#     0,
#     dcc.Store(id=f"stored-df", storage_type="session", data=df),
# )
save_value_callback, update_value_callback = generate_callback("visualization-type")
save_value_callback, update_value_callback = generate_callback("workflow-selector")
# save_value_callback, update_value_callback = generate_callback("selected-dataframe")


# Define the callback to update the specific parameters dropdowns
@app.callback(
    [
        Output("specific-params-container", "children"),
        Output("offcanvas-state-store", "data"),
    ],
    [Input("visualization-type", "value"), Input("interval", "n_intervals")],
    [State("offcanvas-state-store", "data")],
)
def update_specific_params(value, n_intervals, offcanvas_states):
    # print("\t", value)
    # print(specific_params[value])
    if value is not None:
        specific_params_options = [
            {"label": param_name, "value": param_name}
            for param_name in specific_params[value]
        ]

        # specific_params_dropdowns = [
        #     dbc.AccordionItem(
        #         [
        #             dbc.Row(
        #                 [
        #                     dcc.Dropdown(
        #                         id=f"{value}-{param_name}",
        #                         options=list(df.columns),
        #                         value=None,
        #                         persistence=True,
        #                     ),
        #                     dbc.Tooltip(
        #                         f"{' '.join(param_info[value][param_name]['description'])}",
        #                         target=f"{value}-{param_name}",
        #                         placement="right",
        #                         # delay={"hide": 50000},
        #                         autohide=False,
        #                     ),
        #                 ],
        #             )
        #         ],
        #         # className="bg-warning text-dark",
        #         title=param_name,
        #     )
        #     for param_name in specific_params[value]
        # ]

        specific_params_dropdowns = list()
        print(secondary_common_params)
        for e in specific_params[value]:
            processed_type_tmp = param_info[value][e]["processed_type"]
            allowed_types = ["str", "int", "float", "column"]
            if processed_type_tmp in allowed_types:
                input_fct = plotly_bootstrap_mapping[processed_type_tmp]
                print(e, input_fct(), processed_type_tmp)
                tmp_options = dict()

                if processed_type_tmp == "column":
                    tmp_options = {
                        "options": list(df.columns),
                        "value": None,
                        "persistence": True,
                        "id": f"{e}",
                    }
                if processed_type_tmp == "str":
                    tmp_options = {
                        "placeholder": e,
                        "type": "text",
                        "persistence": True,
                        # "persistence_type": "session",
                        "id": f"{e}",
                        "value": None,
                    }
                if processed_type_tmp in ["int", "float"]:
                    tmp_options = {
                        "placeholder": e,
                        "type": "number",
                        "persistence": True,
                        "id": f"{e}",
                        "value": None,
                    }
                input_fct_with_params = input_fct(**tmp_options)
                accordion_item = dbc.AccordionItem(
                    [dbc.Row(input_fct_with_params)],
                    className="my-2",
                    title=e,
                )
                specific_params_dropdowns.append(accordion_item)

        # specific_params_dropdowns = [
        #     {"label": e, "value": e} for e in specific_params[value]
        # ]

        secondary_common_params_dropdowns = list()
        print(secondary_common_params)
        for e in secondary_common_params:
            processed_type_tmp = param_info[value][e]["processed_type"]
            allowed_types = ["str", "int", "float", "column"]
            if processed_type_tmp in allowed_types:
                input_fct = plotly_bootstrap_mapping[processed_type_tmp]
                print(e, input_fct(), processed_type_tmp)
                tmp_options = dict()

                if processed_type_tmp == "column":
                    tmp_options = {
                        "options": list(df.columns),
                        "value": None,
                        "persistence": True,
                        "id": f"{e}",
                    }
                if processed_type_tmp == "str":
                    tmp_options = {
                        "placeholder": e,
                        "type": "text",
                        "persistence": True,
                        # "persistence_type": "session",
                        "id": f"{e}",
                        "value": None,
                    }
                if processed_type_tmp in ["int", "float"]:
                    tmp_options = {
                        "placeholder": e,
                        "type": "number",
                        "persistence": True,
                        "id": f"{e}",
                        "value": None,
                    }
                input_fct_with_params = input_fct(**tmp_options)
                accordion_item = dbc.AccordionItem(
                    [dbc.Row(input_fct_with_params)],
                    className="my-2",
                    title=e,
                )
                secondary_common_params_dropdowns.append(accordion_item)

        # print(list(common_param_names))
        # print(dropdown_elements)
        # print([e for e in list(common_param_names[1:]) if e not in dropdown_elements])
        secondary_common_params_layout = [html.H5("Common parameters")] + [
            dbc.Accordion(
                secondary_common_params_dropdowns,
                flush=True,
                always_open=True,
                persistence_type="session",
                persistence=True,
                id="accordion-sec-common",
                # style={"headerColor": "#ffc107", "color": "red"},
            ),
            # dcc.Store(id="accordion-state"),
        ]
        dynamic_specific_params_layout = [
            html.H5(f"{value.capitalize()} specific parameters")
        ] + [
            dbc.Accordion(
                specific_params_dropdowns,
                flush=True,
                always_open=True,
                persistence_type="session",
                persistence=True,
                id="accordion",
            ),
            # dcc.Store(id="accordion-state"),
        ]
        # print(secondary_common_params_layout + dynamic_specific_params_layout)

        return (
            secondary_common_params_layout + dynamic_specific_params_layout,
            secondary_common_params_layout + dynamic_specific_params_layout,
        )
    else:
        return html.Div(), html.Div()


@app.callback(
    Output("save-button", "n_clicks"),
    Input("save-button", "n_clicks"),
    State("graph-container", "figure")
    # [State(f"stored-{element}", "data") for element in dropdown_elements]
    # + [State(element, "value") for element in dropdown_elements],
)
def save_data(
    n_clicks,
    figure,
):
    if n_clicks > 0:
        print("\n")
        print(figure)
        import hashlib

        # print(hashlib.md5(json.dumps(figure).encode("utf-8")))
        figure_hash = hashlib.md5(json.dumps(figure).encode("utf-8")).hexdigest()
        print(os.getcwd())
        if f"{figure_hash}.json" not in os.listdir("data"):
            with open(f"dev_design_visu/data/{figure_hash}.json", "w") as file:
                json.dump(figure, file)
            print(f"Figure saved with hash {figure_hash}")

        else:
            print(f"Figure with hash {figure_hash} already exists")

    #     # print(element_data)
    #     # Store values of dropdown elements in a dictionary
    #     element_values = {}
    #     for i, element_id in enumerate(dropdown_elements):
    #         # print(i, element_id)
    #         stored_data = element_data[i + 1]
    #         # print(stored_data)
    #         # value = element_data[i + len(dropdown_elements)]
    #         element_values[element_id] = {
    #             "stored_data": stored_data,
    #             # "value": value,
    #         }

    #     print(element_values)

    #     with open("data_prepare.json", "w") as file:
    #         json.dump(element_values, file)

    #     return n_clicks

    # return n_clicks


def generate_dropdown_ids(value):
    specific_param_ids = [
        f"{value}-{param_name}" for param_name in specific_params[value]
    ]
    secondary_param_ids = [f"{value}-{e}" for e in secondary_common_params]

    return secondary_param_ids + specific_param_ids


@app.callback(
    Output("graph-container", "figure"),
    [
        Input("workflow-selector", "value"),
        Input("wf-option-selector", "value"),
        Input("visualization-type", "value"),
        Input("x", "value"),
        Input("y", "value"),
        Input("color", "value"),
        Input("specific-params-container", "children"),
    ],
)
def update_graph(
    wf, wf_option, visualization_type, x_axis, y_axis, color, *children_values
):
    # DROPDOWN
    # print(
    #     children_values[0][1]["props"]["children"][0]["props"]["children"][0]["props"][
    #         "children"
    #     ]["props"]["id"]
    # )

    print(children_values[0][3])
    d = dict()
    for child in children_values[0][1]["props"]["children"]:
        print(child)
        d[
            child["props"]["children"][0]["props"]["children"]["props"]["id"].replace(
                f"{visualization_type}-", ""
            )
        ] = child["props"]["children"][0]["props"]["children"]["props"]["value"]
    for child in children_values[0][3]["props"]["children"]:
        print(
            child,
            child["props"]["children"][0]["props"]["children"]["props"]["id"].replace(
                f"{visualization_type}-", ""
            ),
            child["props"]["children"][0]["props"]["children"]["props"]["value"],
        )
        d[
            child["props"]["children"][0]["props"]["children"]["props"]["id"].replace(
                f"{visualization_type}-", ""
            )
        ] = child["props"]["children"][0]["props"]["children"]["props"]["value"]
        # print(child["props"]["children"][0]["props"]["children"]["props"]["value"])

    # d = {
    #     e["props"]["children"][0]["props"]["children"][0]["props"]["id"].replace(
    #         f"{visualization_type}-", ""
    #     ): e["props"]["children"][0]["props"]["children"][0]["props"]["value"]
    #     for e in children_values[0][1]["props"]["children"]
    #     if e["props"]["children"][0]["props"]["children"][0]["props"]["value"]
    # }
    print(d)
    # d = {}

    # Process inputs and generate the appropriate graph
    plot_func = plotly_vizu_dict[visualization_type]
    plot_kwargs = {}

    plot_kwargs["x"] = x_axis
    plot_kwargs["y"] = y_axis
    if color:
        plot_kwargs["color"] = color

    plot_kwargs = {**plot_kwargs, **d}

    figure = plot_func(
        # data_frame=df, **plot_kwargs,
        data_frame=read_df(option_to_data_source[wf_option]),
        **plot_kwargs,
    )
    return figure


if __name__ == "__main__":
    app.run_server(debug=True)
