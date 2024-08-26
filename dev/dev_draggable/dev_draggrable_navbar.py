from dash import html, dcc, Dash
import dash_draggable
import dash.dependencies as dd
import dash

app = Dash(__name__)

app.layout = html.Div([
    # Sidebar (collapsible)
    html.Div(id='sidebar', style={'width': '250px', 'display': 'block', 'float': 'left', 'height': '100%', 'background-color': '#f0f0f0', 'border-right': '1px solid black'}, children=["Sidebar"]),

    # Main container with the ResponsiveGridLayout
    html.Div([
        dash_draggable.ResponsiveGridLayout(
            id="draggable",
            clearSavedLayout=True,
            layouts={'lg': [{'i': 'item1', 'x': 0, 'y': 0, 'w': 2, 'h': 2}, {'i': 'item2', 'x': 2, 'y': 0, 'w': 2, 'h': 2}]},
            children=[
                html.Div("Item 1", id='item1', style={"border": "1px solid black"}),
                html.Div("Item 2", id='item2', style={"border": "1px solid black"}),
            ],
            isDraggable=True,
            isResizable=True,
            style={"width": "100%", "height": "100%"},
        ),
    ], id='main-content', style={"margin-left": "250px"}),

    # A hidden div to store the state of the sidebar
    dcc.Store(id='sidebar-state', data={'collapsed': False}),

    # Button to toggle the sidebar
    html.Button('Toggle Sidebar', id='toggle-sidebar')
])

@app.callback(
    dd.Output('sidebar', 'style'),
    dd.Output('main-content', 'style'),
    dd.Output('sidebar-state', 'data'),
    [dd.Input('toggle-sidebar', 'n_clicks')],
    [dd.State('sidebar-state', 'data')]
)
def toggle_sidebar(n_clicks, sidebar_state):
    if n_clicks:
        sidebar_collapsed = not sidebar_state['collapsed']
        sidebar_style = {'width': '50px'} if sidebar_collapsed else {'width': '250px'}
        main_content_style = {"margin-left": "50px"} if sidebar_collapsed else {"margin-left": "250px"}
        return sidebar_style, main_content_style, {'collapsed': sidebar_collapsed}
    return dash.no_update, dash.no_update, sidebar_state

# Inject JavaScript to handle the resize
app.clientside_callback(
    """
    function(n_clicks) {
        setTimeout(function() {
            window.dispatchEvent(new Event('resize'));
        }, 100);
        return null;
    }
    """,
    dd.Output('sidebar', 'style', allow_duplicate=True),
    [dd.Input('toggle-sidebar', 'n_clicks')],
    prevent_initial_call=True
)

if __name__ == '__main__':
    app.run_server(debug=True)
