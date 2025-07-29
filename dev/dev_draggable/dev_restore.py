import dash
import dash_bootstrap_components as dbc
import dash_draggable
from dash import Input, Output, State, dcc, html


# Simulated function to load data (replace with your actual loading function)
def load_depictio_data():
    # This should return the exact format expected by the layout
    return {
        "stored_layout_data": {},
        "stored_children_data": [
            html.Div(
                [
                    dbc.Button(
                        "Remove", id={"type": "remove-box-button", "index": "1"}, color="danger"
                    ),
                    dbc.Card(
                        [
                            dbc.CardHeader("count on sample"),
                            dbc.CardBody("3072.0", id={"type": "card-value", "index": "1"}),
                        ],
                        id={"type": "card", "index": "1"},
                    ),
                ],
                id="1",
            ),
        ],  # Add closing square bracket
    }


app = dash.Dash(__name__)


def create_app_layout():
    depictio_dash_data = load_depictio_data()
    if depictio_dash_data:
        init_children = depictio_dash_data["stored_children_data"]
    else:
        init_children = []

    # Wrap the ResponsiveGridLayout in a Loading component
    layout = html.Div(
        [
            dbc.Container(
                [
                    dcc.Loading(
                        id="loading",
                        children=[
                            dash_draggable.ResponsiveGridLayout(
                                children=init_children, id="draggable-container"
                            )
                        ],
                    ),
                    html.Div(id="dummy-output", style={"display": "none"}),
                ]
            )
        ]
    )
    return layout


app.layout = create_app_layout


@app.callback(
    Output("draggable-container", "children"),
    [Input("loading", "children")],  # Use the Loading component as a trigger
    [State("draggable-container", "children")],
)
def check_contents(loaded_children, existing_children):
    print("Existing Children: ", existing_children)
    # Debugging prints
    if existing_children and isinstance(existing_children, list) and existing_children:
        print("Length of existing children: ", len(existing_children))
        print("Existing children type: ", type(existing_children[0]))
        if type(existing_children[0]) is dict:
            print("Existing children keys: ", existing_children[0].keys())
            if "props" in existing_children[0]:
                print("Existing children props keys: ", existing_children[0]["props"].keys())
                print("ID: ", existing_children[0]["props"]["id"])
                if "children" in existing_children[0]["props"]:
                    print(
                        "Existing children props children: ",
                        existing_children[0]["props"]["children"],
                    )

                    new_children = existing_children[0]["props"]["children"]
                    print("Unwrapped children:", new_children)
                    return new_children

    # # Check and unwrap if necessary
    # if len(existing_children) == 1 and hasattr(existing_children[0], 'props') and 'children' in existing_children[0].props:
    #     new_children = existing_children[0].props['children']
    #     print("Unwrapped children:", new_children)
    #     return new_children
    print("No unwrapping needed")

    return existing_children


if __name__ == "__main__":
    app.run_server(debug=True, port=8053)
