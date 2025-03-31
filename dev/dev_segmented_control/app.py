import dash
import dash_mantine_components as dmc
from dash import html, Input, Output, callback

app = dash.Dash(__name__)

app.layout = html.Div([
    dmc.SegmentedControl(
        id='status-toggle',
        value='false',
        data=[
            {'label': 'Inactive', 'value': 'false'},
            {'label': 'Active', 'value': 'true'}
        ],
        color='red',
        style={
            'width': '300px'
        }
    ),
    html.Div(id='status-output')
])

@callback(
    [Output('status-toggle', 'color'),
     Output('status-output', 'children')],
    [Input('status-toggle', 'value')]
)
def update_status(value):
    if value == 'true':
        return 'green', 'Current Status: Active'
    else:
        return 'red', 'Current Status: Inactive'

if __name__ == '__main__':
    app.run_server(debug=True)