# Import necessary libraries
from dash import dcc, html
from dash.dependencies import Input, Output, State
import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import inspect

import os, sys
# sys.path.append("dev")
from pages.utils import (
    load_data,
    get_common_params,
    get_specific_params,
    get_param_info,
    get_dropdown_options,
)

# from dev import utils 
# TO REGISTER THE PAGE INTO THE MAIN APP.PY
# app = dash.Dash(__name__)
dash.register_page(__name__, path="/design-visualisation", title="Design Visualisation")


# Set up Dash app with Bootstrap CSS and additional CSS file
# app = dash.Dash(
#     __name__,
#     external_stylesheets=[dbc.themes.BOOTSTRAP, "custom.css"],
#     suppress_callback_exceptions=True,
# )

# TODO: replace with FASTAPI
# Create list of workflows
workflows = ["ashleys-qc-pipeline", "nf-core-ampliseq"]

# TODO: replace with FASTAPI
# Create dictionary mapping workflows to their options
workflow_options = {
    "ashleys-qc-pipeline": ["mosaicatcher counts statistics", "ashleys predictions"],
    "nf-core-ampliseq": ["Read Mean Quality", "Read GC Content"],
}


# TODO: utils
def read_df(data_source_url):
    _, file_extension = os.path.splitext(data_source_url)

    if file_extension == ".csv":
        df = pd.read_csv(data_source_url)
    elif file_extension == ".tsv":
        df = pd.read_csv(data_source_url, sep="\t")
    elif file_extension in [".xls", ".xlsx"]:
        df = pd.read_excel(data_source_url)
    elif file_extension == ".json":
        df = pd.read_json(data_source_url)
    elif file_extension == ".parquet":
        df = pd.read_parquet(data_source_url)
        # print(df.to_dict())
        # exit()
    elif file_extension == ".feather":
        df = pd.read_feather(data_source_url)
    else:
        raise ValueError(f"Unsupported file extension: {file_extension}")

    return df.reset_index(drop=True).to_dict()


# TODO: replace with FASTAPI
# Define your data sources
option_to_data_source = {
    # "mosaicatcher counts statistics": "dataframe.parquet",
    # "mosaicatcher counts statistics": "dev_design_visu/data/mosaicatcher_counts_statistics.csv",
    "mosaicatcher counts statistics": "https://raw.githubusercontent.com/plotly/datasets/master/Antibiotics.csv",
    # "ashleys predictions": "dev_design_visu/data/ashleys_predictions.csv",
    "ashleys predictions": "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv",
    # "Read Mean Quality": "dev_design_visu/data/read_mean_quality.csv",
    "Read Mean Quality": "https://raw.githubusercontent.com/plotly/datasets/master/beers.csv",
    # "Read GC Content": "dev_design_visu/data/read_gc_content.csv",
    "Read GC Content": "https://raw.githubusercontent.com/plotly/datasets/master/diabetes.csv",
}

dataframes_dict = {k: read_df(v) for k, v in option_to_data_source.items()}


df = pd.DataFrame(list(dataframes_dict.values())[0])


# TODO: utils / config

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


layout = dbc.Container(
    [
        dcc.Interval(
            id="interval",
            interval=2000,  # Save slider value every 1 second
            n_intervals=0,
        ),
        dcc.Store(
            id="dataframe-store",
            storage_type="memory",
            data=dataframes_dict,
        ),
        dcc.Store(id="selections-store", storage_type="session", data={}),
        html.H1(
            "Prepare your visualization",
            className="text-center mb-4",
        ),
        html.Hr(),
        dbc.Row(
            [
                dbc.Col(html.H5("Select your workflow"), width=2),
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
                dbc.Col(html.H5("Select an option"), width=2),
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
                dbc.Col(html.H5("Visualization type"), width=2),
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
                        dbc.Col(html.H6("X-axis"), width=1),
                        dbc.Col(
                            dcc.Dropdown(
                                id="x",
                                options=dropdown_options,
                                value=list(df.columns)[0],
                            ),
                            width=2,
                        ),
                        dbc.Col(html.H6("Y-axis"), width=1),
                        dbc.Col(
                            dcc.Dropdown(
                                id="y",
                                options=dropdown_options,
                                value=list(df.columns)[1],
                            ),
                            width=2,
                        ),
                        dbc.Col(html.H6("Color group"), width=1),
                        dbc.Col(
                            dcc.Dropdown(
                                id="color",
                                options=dropdown_options,
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
                                        className="text-success",
                                        id="success-modal-header",
                                    )
                                ),
                                dbc.ModalBody(
                                    html.H5(
                                        # "Your amazing dashboard was successfully saved!",
                                        id="success-modal-body",
                                        className="text-success",
                                    ),
                                    id="success-H5",
                                    style={"background-color": "#F0FFF0"},
                                ),
                                dbc.ModalFooter(
                                    dbc.Button(
                                        "Close",
                                        id="success-modal-close",
                                        # id="modal-close-button",
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
    ],
    fluid=False,
)


# Define a callback to update the options when the workflow selection changes
@dash.callback(
    Output("wf-option-selector", "options"), Input("workflow-selector", "value")
)
def update_options(workflow):
    options = workflow_options[workflow]
    return [{"label": option, "value": option} for option in options]


@dash.callback(
    [
        Output("x", "options"),
        Output("y", "options"),
        Output("color", "options"),
        Output("x", "value"),
        Output("y", "value"),
        Output("color", "value"),
    ],
    [Input("wf-option-selector", "value")],
    [State("dataframe-store", "data"), State("selections-store", "data")],
)
def update_dropdown_values(df_name, df_data, selections_dict):
    df = pd.DataFrame(df_data[df_name])
    df_columns = [{"label": col, "value": col} for col in df.columns]

    if df_name in selections_dict:
        x, y, color = (
            selections_dict[df_name]["x"],
            selections_dict[df_name]["y"],
            selections_dict[df_name]["color"],
        )
    else:
        x, y = df.columns[0], df.columns[1]
        color = df.columns[2] if len(df.columns) > 2 else None
        selections_dict[df_name] = {"x": x, "y": y, "color": color}

    return df_columns, df_columns, df_columns, x, y, color


@dash.callback(
    Output("selections-store", "data"),
    [
        Input("x", "value"),
        Input("y", "value"),
        Input("color", "value"),
    ],
    [State("wf-option-selector", "value"), State("selections-store", "data")],
)
def update_selections_store(x, y, color, df_name, selections_dict):
    if x is not None and y is not None:
        selections_dict[df_name] = {"x": x, "y": y, "color": color}
    return selections_dict


# define the callback to show/hide the modal
@dash.callback(
    Output("modal", "is_open"),
    [Input("edit-button", "n_clicks")],
    [State("modal", "is_open")],
)
def toggle_modal(n1, is_open):
    print(n1, is_open)
    if n1:
        return not is_open
    return is_open


@dash.callback(
    Output("success-modal", "is_open"),
    [
        Input("save-button", "n_clicks"),
        Input("success-modal-close", "n_clicks"),
    ],
    [State("success-modal", "is_open")],
)
def toggle_success_modal(n_save, n_close, is_open):
    print(n_save, n_close, is_open)
    ctx = dash.callback_context

    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    # print(trigger_id, n_save, n_close)

    print(trigger_id)
    if trigger_id == "save-button":
        if n_save is None or n_save == 0:
            raise dash.exceptions.PreventUpdate
        else:
            return True

    elif trigger_id == "success-modal-close":
        if n_close is None or n_close == 0:
            raise dash.exceptions.PreventUpdate
        else:
            return False

    return is_open


@dash.callback(
    [
        Output("success-modal-header", "className"),
        Output("success-H5", "style"),
        Output("success-modal-body", "className"),
    ],
    Input("success-modal-body", "children"),
)
def update_modal_style(success_message):
    if "Figure saved" in success_message:
        return "text-success", {"background-color": "#F0FFF0"}, "text-success"

    elif "already" in success_message:
        return "text-warning", {"background-color": "#FFF5EE"}, "text-warning"
    else:
        return dash.no_update, dash.no_update


@dash.callback(
    Output("success-modal-header", "children"),
    Input("success-modal-body", "children"),
)
def update_modal_header(success_message):
    if "Figure saved" in success_message:
        return "Figure Saved!"
    elif "already exists" in success_message:
        return "Figure Already Exists!"
    else:
        return dash.no_update


def generate_callback(element_id):
    @dash.callback(
        Output(f"stored-{element_id}", "data"),
        Input("interval", "n_intervals"),
        State(element_id, "value"),
    )
    def save_value(n_intervals, value):
        if n_intervals == 0:
            raise dash.exceptions.PreventUpdate
        return value

    @dash.callback(
        Output(element_id, "value"),
        Input(f"stored-{element_id}", "data"),
    )
    def update_value(data):
        if data is None:
            raise dash.exceptions.PreventUpdate
        return data

    return save_value, update_value


layout.children.insert(
    0,
    dcc.Store(id=f"stored-visualization-type", storage_type="session", data="scatter"),
)

save_value_callback, update_value_callback = generate_callback("visualization-type")


# Define the callback to update the specific parameters dropdowns
@dash.callback(
    [
        Output("specific-params-container", "children"),
        Output("offcanvas-state-store", "data"),
    ],
    [Input("visualization-type", "value"), Input("interval", "n_intervals")],
    [State("offcanvas-state-store", "data")],
)
def update_specific_params(value, n_intervals, offcanvas_states):
    if value is not None:
        specific_params_options = [
            {"label": param_name, "value": param_name}
            for param_name in specific_params[value]
        ]

        specific_params_dropdowns = list()
        for e in specific_params[value]:
            processed_type_tmp = param_info[value][e]["processed_type"]
            allowed_types = ["str", "int", "float", "column"]
            if processed_type_tmp in allowed_types:
                input_fct = plotly_bootstrap_mapping[processed_type_tmp]
                # print(e, input_fct(), processed_type_tmp)
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

        secondary_common_params_dropdowns = list()
        for e in secondary_common_params:
            processed_type_tmp = param_info[value][e]["processed_type"]
            allowed_types = ["str", "int", "float", "column"]
            if processed_type_tmp in allowed_types:
                input_fct = plotly_bootstrap_mapping[processed_type_tmp]
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

        secondary_common_params_layout = [html.H5("Common parameters")] + [
            dbc.Accordion(
                secondary_common_params_dropdowns,
                flush=True,
                always_open=True,
                persistence_type="session",
                persistence=True,
                id="accordion-sec-common",
            ),
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
        ]

        return (
            secondary_common_params_layout + dynamic_specific_params_layout,
            secondary_common_params_layout + dynamic_specific_params_layout,
        )
    else:
        return html.Div(), html.Div()


@dash.callback(
    [Output("save-button", "n_clicks"), Output("success-modal-body", "children")],
    Input("save-button", "n_clicks"),
    State("graph-container", "figure"),
)
def save_data(
    n_clicks,
    figure,
):
    if n_clicks:
        import hashlib, json

        figure_hash = hashlib.md5(json.dumps(figure).encode("utf-8")).hexdigest()
        print(os.getcwd())
        if f"{figure_hash}.json" not in os.listdir("dev_design_visu/data"):
            with open(f"dev_design_visu/data/{figure_hash}.json", "w") as file:
                json.dump(figure, file)
            message = f"Figure saved with hash {figure_hash}"
            print(message)
            return n_clicks, message

        else:
            message = f"Figure with hash {figure_hash} already exists"
            print(message)
            return n_clicks, message
    else:
        return n_clicks, dash.no_update


def generate_dropdown_ids(value):
    specific_param_ids = [
        f"{value}-{param_name}" for param_name in specific_params[value]
    ]
    secondary_param_ids = [f"{value}-{e}" for e in secondary_common_params]

    return secondary_param_ids + specific_param_ids


@dash.callback(
    Output("graph-container", "figure"),
    [
        Input("wf-option-selector", "value"),
        Input("dataframe-store", "data"),
        Input("visualization-type", "value"),
        Input("x", "value"),
        Input("y", "value"),
        Input("color", "value"),
        Input("specific-params-container", "children"),
    ],
)
def update_graph(
    wf_option, df_data, visualization_type, x_axis, y_axis, color, *children_values
):
    d = dict()
    for child in children_values[0][1]["props"]["children"]:
        # print(child)
        d[
            child["props"]["children"][0]["props"]["children"]["props"]["id"].replace(
                f"{visualization_type}-", ""
            )
        ] = child["props"]["children"][0]["props"]["children"]["props"]["value"]
    for child in children_values[0][3]["props"]["children"]:
        d[
            child["props"]["children"][0]["props"]["children"]["props"]["id"].replace(
                f"{visualization_type}-", ""
            )
        ] = child["props"]["children"][0]["props"]["children"]["props"]["value"]

    # Process inputs and generate the appropriate graph
    plot_func = plotly_vizu_dict[visualization_type]
    plot_kwargs = {}

    plot_kwargs["x"] = x_axis
    plot_kwargs["y"] = y_axis
    if color:
        plot_kwargs["color"] = color

    plot_kwargs = {**plot_kwargs, **d}

    figure = plot_func(
        data_frame=pd.DataFrame(df_data[wf_option]),
        **plot_kwargs,
    )
    figure.update_layout(uirevision=1)

    return figure


# if __name__ == "__main__":
#     app.run_server(debug=True, port=8051)
