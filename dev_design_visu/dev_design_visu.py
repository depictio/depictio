from dash import dcc, html
from dash.dependencies import Input, Output, State
import ast
import dash
import dash_bootstrap_components as dbc
import json
import os, json
import pandas as pd
import plotly.express as px
import time

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP, "custom.css"],
    # prevent_initial_callbacks=True,
    suppress_callback_exceptions=True,
)

df = pd.read_csv(
    "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
    # "https://raw.githubusercontent.com/plotly/datasets/master/titanic.csv"
)


import inspect

plotly_vizu_list = [px.scatter, px.line, px.bar, px.histogram, px.box]

visualization_types = [func.__name__ for func in plotly_vizu_list]


plotly_vizu_dict = {}
for vizu_func in plotly_vizu_list:
    plotly_vizu_dict[vizu_func.__name__] = vizu_func


common_params = set.intersection(
    *[set(inspect.signature(func).parameters.keys()) for func in plotly_vizu_list]
)
common_param_names = [p for p in list(common_params)]
common_param_names.sort(
    key=lambda x: list(inspect.signature(plotly_vizu_list[0]).parameters).index(x)
)


specific_params = {}

for vizu_func in plotly_vizu_list:
    func_params = inspect.signature(vizu_func).parameters
    param_names = list(func_params.keys())

    common_params_tmp = (
        common_params.intersection(func_params.keys())
        if common_params
        else set(func_params.keys())
    )

    specific_params[vizu_func] = [p for p in param_names if p not in common_params_tmp]

print("Common parameters:", common_param_names)
for vizu_func, params in specific_params.items():
    print(f"Specific parameters for {vizu_func.__name__}: {params}")


# Create a DataFrame from the JSON data for plotting
# df = pd.DataFrame.from_dict(json_data, orient="index")
# print(df)

# Generate dropdown options based on DataFrame columns
dropdown_options = [{"label": col, "value": col} for col in df.columns]


dropdown_elements = [
    "x",
    "y",
    "color",
]


import inspect

# Define the available visualizations
plotly_vizu_list = [px.scatter, px.line, px.bar, px.histogram, px.box]

common_params = set.intersection(
    *[set(inspect.signature(func).parameters.keys()) for func in plotly_vizu_list]
)
common_param_names = [p for p in list(common_params)]
common_param_names.sort(
    key=lambda x: list(inspect.signature(plotly_vizu_list[0]).parameters).index(x)
)

specific_params = {}

for vizu_func in plotly_vizu_list:
    func_params = inspect.signature(vizu_func).parameters
    param_names = list(func_params.keys())

    common_params_tmp = (
        common_params.intersection(func_params.keys())
        if common_params
        else set(func_params.keys())
    )

    specific_params[vizu_func.__name__] = [
        p for p in param_names if p not in common_params_tmp
    ]

print(specific_params)

secondary_common_params = [
    e for e in list(common_param_names[1:]) if e not in dropdown_elements
]


param_info = {}


def extract_info_from_docstring(docstring):
    lines = docstring.split("\n")
    # print(lines)
    parameters_section = False
    result = {}

    for line in lines:
        # print(line)
        if line.startswith("Parameters"):
            parameters_section = True
            continue
        if parameters_section:
            # if line.startswith("----------"):
            #     break
            if line.startswith("    ") is False:
                # print(line.split(': '))
                line_processed = line.split(": ")
                # print(line_processed)
                if len(line_processed) == 2:
                    parameter, type = line_processed[0], line_processed[1]
                    result[parameter] = {"type": type, "description": list()}
                else:
                    continue

            elif line.startswith("    ") is True:
                # result[-1] += " " + line.strip()
                # print(line.strip())
                result[parameter]["description"].append(line.strip())

    return result


import re
from pprint import pprint


def process_json_from_docstring(data):
    for key, value in data.items():
        # Get the type associated with the field
        field_type = value.get("type")
        # field_type = value.get('type')
        description = " ".join(value.get("description"))

        # Check if there are any options available for the field
        options = []
        # for description in value.get('description', []):
        if "One of" in description:
            # The options are usually listed after 'One of'
            option_str = description.split("One of")[-1].split(".")[0]

            options = list(set(re.findall("`'(.*?)'`", option_str)))
        elif "one of" in data[key]["type"]:
            option_str = data[key]["type"].split("one of")[-1]
            options = list(set(re.findall("`'(.*?)'`", option_str)))

        if options:
            data[key]["options"] = options

        if "Series or array-like" in field_type:
            data[key]["processed_type"] = "column"
        else:
            data[key]["processed_type"] = data[key]["type"].split(" ")[0].split(",")[0]
    return data


for func in plotly_vizu_list:
    param_info[func.__name__] = extract_info_from_docstring(func.__doc__)
    param_info[func.__name__] = process_json_from_docstring(param_info[func.__name__])
# pprint(param_info)

allowed_types = ["str", "int", "float", "boolean", "column"]
plotly_bootstrap_mapping = {
    "str": dbc.Input,
    "int": dbc.Input,
    "float": dbc.Input,
    "boolean": dbc.Checklist,
    "column": dcc.Dropdown
    # "float" : dbc.Input(type="number"), "boolean", "column"
}


def load_data():
    if os.path.exists("data_prepare.json"):
        with open("data_prepare.json", "r") as file:
            data = json.load(file)
        return data
    return None


# data = load_data()

init_children = list()


app.layout = dbc.Container(
    [
        dcc.Interval(
            id="interval",
            interval=5000,  # Save slider value every 1 second
            n_intervals=0,
        ),
        html.H1(
            "Prepare your visualization",
            className="text-center mb-4",
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
        html.Hr(),
    ],
    fluid=True,
)


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
save_value_callback, update_value_callback = generate_callback("visualization-type")


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
            with open(f"data/{figure_hash}.json", "w") as file:
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
        Input("visualization-type", "value"),
        Input("x", "value"),
        Input("y", "value"),
        Input("color", "value"),
        Input("specific-params-container", "children"),
    ],
)
def update_graph(visualization_type, x_axis, y_axis, color, *children_values):
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

    figure = plot_func(data_frame=df, **plot_kwargs)
    return figure


if __name__ == "__main__":
    app.run_server(debug=True)
