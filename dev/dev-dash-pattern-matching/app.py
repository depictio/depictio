from dash import MATCH, Dash, Input, Output, Patch, State, callback, dcc, html

app = Dash()

app.layout = html.Div([
    html.Button("Add Filter", id="dynamic-add-filter-btn", n_clicks=0),
    html.Div(id='dynamic-dropdown-container-div', children=[]),
])

@callback(
    Output('dynamic-dropdown-container-div', 'children'),
    Input('dynamic-add-filter-btn', 'n_clicks')
    )
def display_dropdowns(n_clicks):
    patched_children = Patch()
    import uuid
    uuid = str(uuid.uuid4())

    new_element = html.Div([
        dcc.Dropdown(
            ['NYC', 'MTL', 'LA', 'TOKYO'],
            id={
                'type': 'city-dynamic-dropdown',
                'index': uuid
            }
        ),
        html.Div(
            id={
                'type': 'city-dynamic-output',
                'index': uuid
            }
        )
    ])
    patched_children.append(new_element)
    return patched_children


@callback(
    Output({'type': 'city-dynamic-output', 'index': MATCH}, 'children'),
    Input({'type': 'city-dynamic-dropdown', 'index': MATCH}, 'value'),
    State({'type': 'city-dynamic-dropdown', 'index': MATCH}, 'id'),
)
def display_output(value, id):
    return html.Div(f"Dropdown {id['index']} = {value}")


if __name__ == '__main__':
    app.run(debug=True)
