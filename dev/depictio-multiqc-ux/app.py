from pathlib import Path

import dash_dock
import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
import pandas as pd
import plotly.express as px
from dash_iconify import DashIconify
from flask import Flask, abort, send_from_directory

import dash
from dash import Input, Output, State, callback, dcc, html

# Initialize Flask server for serving external HTML files
server = Flask(__name__)

# Flask route to serve external HTML files
@server.route('/external/<path:filename>')
def serve_external_html(filename):
    """Serve HTML files from external locations"""
    # Define the external path where MultiQC reports are located
    external_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData"
    
    print(f"Attempting to serve: {filename}")
    print(f"From path: {external_path}")
    
    # Security check - ensure the file exists and is an HTML file
    file_path = Path(external_path) / filename
    print(f"Full file path: {file_path}")
    print(f"File exists: {file_path.exists()}")
    
    if not file_path.exists():
        print(f"File not found: {file_path}")
        abort(404)
    
    if not file_path.suffix.lower() == '.html':
        print(f"Not an HTML file: {file_path.suffix}")
        abort(404)
    
    print(f"Serving file: {file_path}")
    return send_from_directory(external_path, filename)

# Route to test if Flask is working
@server.route('/test')
def test_route():
    return "Flask route is working!"

# Initialize Dash app with the Flask server
app = dash.Dash(__name__, server=server, suppress_callback_exceptions=True)

# Component counter for unique IDs
component_counter = {'count': 0}

def get_next_id() -> str:
    component_counter['count'] += 1
    return str(component_counter['count'])

# Create initial default components
def create_initial_components():
    """Create some default components for the grid"""
    components = []
    layouts = []
    
    # Add a default figure
    components.append(
        dgl.DraggableWrapper(
            children=[
                html.Div(
                    create_basic_figure(),
                    style={
                        'height': '100%',
                        'width': '100%',
                        'border': '2px solid #1f77b4',
                        'borderRadius': '5px',
                        'background': 'var(--app-surface-color, #ffffff)',
                        'padding': '10px',
                        'boxSizing': 'border-box',
                    },
                    id="default-figure-1",
                )
            ],
            handleText="Default Figure",
        )
    )
    layouts.append({"i": "0", "x": 0, "y": 0, "w": 6, "h": 4})
    
    # Add a default card
    components.append(
        dgl.DraggableWrapper(
            children=[
                html.Div(
                    create_basic_card(),
                    style={
                        'height': '100%',
                        'width': '100%',
                        'border': '2px solid #2ca02c',
                        'borderRadius': '5px',
                        'background': 'var(--app-surface-color, #ffffff)',
                        'padding': '10px',
                        'boxSizing': 'border-box',
                    },
                    id="default-card-1",
                )
            ],
            handleText="Default Card",
        )
    )
    layouts.append({"i": "1", "x": 6, "y": 0, "w": 4, "h": 3})
    
    # Add a MultiQC component with dash-dock
    components.append(
        dgl.DraggableWrapper(
            children=[
                html.Div(
                    create_multiqc_component(),
                    style={
                        'height': '100%',
                        'width': '100%',
                        'border': '2px solid #ff7f0e',
                        'borderRadius': '5px',
                        'background': 'var(--app-surface-color, #ffffff)',
                        'padding': '5px',
                        'boxSizing': 'border-box',
                    },
                    id="default-multiqc-1",
                )
            ],
            handleText="MultiQC with Dock",
        )
    )
    layouts.append({"i": "2", "x": 0, "y": 4, "w": 12, "h": 6})
    
    return components, layouts

def create_basic_figure():
    """Create a basic figure component for testing"""
    # Generate some sample data
    df = pd.DataFrame({
        'x': range(10),
        'y': [i**2 for i in range(10)]
    })
    
    fig = px.line(df, x='x', y='y', title='Sample Line Chart')
    fig.update_layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='var(--app-text-color, #000000)'),
        title_font_color='var(--app-text-color, #000000)'
    )
    
    return dcc.Graph(
        figure=fig,
        style={'height': '100%', 'width': '100%'}
    )

def create_basic_card():
    """Create a basic card component for testing"""
    return dmc.Card(
        children=[
            dmc.CardSection([
                dmc.Title("Sample Card", order=3),
            ]),
            dmc.Text("This is a basic card component for testing the grid layout."),
            dmc.Space(h=10),
            dmc.Button("Sample Action", variant="light"),
        ],
        withBorder=True,
        shadow="sm",
        radius="md",
        style={
            'height': '100%',
            'backgroundColor': 'var(--app-surface-color, #ffffff)',
            'color': 'var(--app-text-color, #000000)',
        }
    )

def create_multiqc_component():
    """Create MultiQC component using dash-dock"""
    
    dock_config = {
        "global": {
            "tabEnableClose": False,
            "tabEnableFloat": True
        },
        "layout": {
            "type": "row",
            "children": [
                {
                    "type": "tabset",
                    "children": [
                        {
                            "type": "tab",
                            "name": "MultiQC Report",
                            "component": "text",
                            "id": "multiqc-tab-1",
                            "enableFloat": True
                        }
                    ]
                }
            ]
        }
    }

    # Tab content with iframe to external HTML
    tab_components = [
        dash_dock.Tab(
            id="multiqc-tab-1",
            children=[
                html.Iframe(
                    src="/external/multiqc_output_fastqc_v1_30_0/multiqc_report.html",
                    style={
                        'width': '100%',
                        'height': '100%',
                        'border': 'none'
                    }
                )
            ]
        )
    ]

    return html.Div(
        dash_dock.DashDock(
            id=f'dock-layout-{get_next_id()}',
            model=dock_config,
            children=tab_components,
            useStateForModel=True,
            style={
                'position': 'relative',
                'height': '100%',
                'width': '100%',
                'overflow': 'hidden'
            }
        ),
        style={
            'height': '100%',
            'width': '100%',
        }
    )

# Main app layout
app.layout = dmc.MantineProvider(
    theme={
        "colorScheme": "light",
        "primaryColor": "blue",
    },
    children=[
        dmc.AppShell(
            children=[
                dmc.AppShellHeader(
                    children=[
                        dmc.Group([
                            dmc.Title("Depictio MultiQC UX Prototype", order=2),
                            dmc.Group([
                                dmc.Button(
                                    "Add Figure",
                                    id="add-figure-btn",
                                    leftSection=DashIconify(icon="tabler:chart-line"),
                                    variant="light"
                                ),
                                dmc.Button(
                                    "Add Card",
                                    id="add-card-btn",
                                    leftSection=DashIconify(icon="tabler:card"),
                                    variant="light"
                                ),
                                dmc.Button(
                                    "Add MultiQC Report",
                                    id="add-multiqc-btn",
                                    leftSection=DashIconify(icon="tabler:file-analytics"),
                                    variant="light"
                                ),
                                html.A(
                                    dmc.Button(
                                        "Test Flask Route",
                                        leftSection=DashIconify(icon="tabler:test-pipe"),
                                        variant="outline",
                                        size="sm"
                                    ),
                                    href="/external/multiqc_output_fastqc_v1_30_0/multiqc_report.html",
                                    target="_blank"
                                ),
                            ])
                        ], justify="space-between", style={"padding": "1rem"})
                    ],
                    h=60  # Use h instead of height for DMC 2.1.0
                ),
                dmc.AppShellMain(
                    children=[
                        html.Div(
                            id="grid-container",
                            children=[
                                dgl.DashGridLayout(
                                    id='dynamic-grid',
                                    items=create_initial_components()[0],
                                    showRemoveButton=True,
                                    showResizeHandles=True,
                                    cols={"lg": 12, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
                                    rowHeight=60,
                                    itemLayout=create_initial_components()[1],
                                    style={
                                        'backgroundColor': 'var(--app-bg-color, #f8f9fa)',
                                        'minHeight': 'calc(100vh - 60px)',
                                        'padding': '1rem'
                                    }
                                )
                            ]
                        )
                    ]
                )
            ]
        )
    ]
)

# Callback to add components to the grid
@callback(
    [Output('dynamic-grid', 'items'),
     Output('dynamic-grid', 'itemLayout')],
    [Input('add-figure-btn', 'n_clicks'),
     Input('add-card-btn', 'n_clicks'),
     Input('add-multiqc-btn', 'n_clicks')],
    [State('dynamic-grid', 'items'),
     State('dynamic-grid', 'itemLayout')]
)
def add_component(_fig_clicks, _card_clicks, _multiqc_clicks, current_items, current_layout):
    ctx = dash.callback_context
    
    if not ctx.triggered:
        return current_items or [], current_layout or []
    
    # Initialize if None
    if current_items is None:
        current_items = []
    if current_layout is None:
        current_layout = []
    
    # Get the triggered button
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    # Generate unique component ID
    comp_id = get_next_id()
    
    # Create the appropriate DraggableWrapper component
    if button_id == 'add-figure-btn':
        new_item = dgl.DraggableWrapper(
            children=[
                html.Div(
                    create_basic_figure(),
                    style={
                        'height': '100%',
                        'width': '100%',
                        'border': '2px solid #1f77b4',
                        'borderRadius': '5px',
                        'background': 'var(--app-surface-color, #ffffff)',
                        'padding': '10px',
                        'boxSizing': 'border-box',
                    },
                    id=f"figure-component-{comp_id}",
                )
            ],
            handleText="Move Figure",
        )
        layout_item = {"i": comp_id, "x": 0, "y": 0, "w": 6, "h": 4}
    elif button_id == 'add-card-btn':
        new_item = dgl.DraggableWrapper(
            children=[
                html.Div(
                    create_basic_card(),
                    style={
                        'height': '100%',
                        'width': '100%',
                        'border': '2px solid #2ca02c',
                        'borderRadius': '5px',
                        'background': 'var(--app-surface-color, #ffffff)',
                        'padding': '10px',
                        'boxSizing': 'border-box',
                    },
                    id=f"card-component-{comp_id}",
                )
            ],
            handleText="Move Card",
        )
        layout_item = {"i": comp_id, "x": 0, "y": 0, "w": 4, "h": 3}
    elif button_id == 'add-multiqc-btn':
        new_item = dgl.DraggableWrapper(
            children=[
                html.Div(
                    create_multiqc_component(),
                    style={
                        'height': '100%',
                        'width': '100%',
                        'border': '2px solid #ff7f0e',
                        'borderRadius': '5px',
                        'background': 'var(--app-surface-color, #ffffff)',
                        'padding': '10px',
                        'boxSizing': 'border-box',
                    },
                    id=f"multiqc-component-{comp_id}",
                )
            ],
            handleText="Move MultiQC Report",
        )
        layout_item = {"i": comp_id, "x": 0, "y": 0, "w": 12, "h": 8}
    else:
        return current_items, current_layout
    
    # Add the new item and layout
    current_items.append(new_item)
    current_layout.append(layout_item)
    
    return current_items, current_layout

if __name__ == '__main__':
    app.run(debug=True, port=8050)