#!/usr/bin/env python3
"""
Minimal dash-dock prototype with MultiQC HTML serving
Single tab, single iframe, focused on getting the basic functionality working
"""

from pathlib import Path

import dash_dock
import dash_mantine_components as dmc
import polars as pl
from flask import Flask, abort, send_from_directory

import dash
from dash import ClientsideFunction, Input, Output, State, callback, clientside_callback, dcc, html

# Initialize Flask server for serving external HTML files
server = Flask(__name__)

# Flask route to serve external files (HTML, CSS, JS, images, source maps, etc.)
@server.route('/external/<path:filename>')
def serve_external_html(filename):
    """Serve files from external MultiQC locations"""
    external_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData"
    
    print(f"📁 Serving: {filename}")
    print(f"📂 From: {external_path}")
    
    file_path = Path(external_path) / filename
    print(f"🔍 Full path: {file_path}")
    print(f"✅ Exists: {file_path.exists()}")
    
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        # Handle missing source maps gracefully - return empty response instead of 404
        if file_path.suffix.lower() == '.map':
            print("🗺️ Source map missing - returning empty response (this is OK)")
            return '', 200, {'Content-Type': 'application/json'}
        abort(404)
    
    # Allow common MultiQC file types
    allowed_extensions = {'.html', '.css', '.js', '.map', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.json', '.woff', '.woff2', '.ttf', '.eot'}
    if file_path.suffix.lower() not in allowed_extensions:
        print(f"❌ File type not allowed: {file_path.suffix}")
        abort(404)
    
    return send_from_directory(external_path, filename)

# Test route
@server.route('/test')
def test_route():
    return "<h1>Flask is working!</h1><p>Server is running correctly.</p>"

# Initialize Dash app with Flask server
app = dash.Dash(__name__, server=server)

# Load sample list from MultiQC parquet file
def load_multiqc_samples():
    """Load unique sample names from MultiQC parquet file using general_stats_table anchor"""
    try:
        parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_fastqc_v1_30_0/multiqc_data/BETA-multiqc.parquet"
        df = pl.read_parquet(parquet_path)
        
        if 'sample' in df.columns and 'anchor' in df.columns:
            # Filter by general_stats_table anchor, select sample column, drop nulls
            sample_series = (
                df.filter(pl.col("anchor") == "general_stats_table")
                .select("sample")
                .drop_nulls()
                .unique()
                .sort("sample")
            )
            
            # Convert to list and filter out None values and "null" strings
            sample_list = [
                s for s in sample_series["sample"].to_list() 
                if s is not None and s != "null" and s != ""
            ]
            
            print(f"✅ Loaded {len(sample_list)} unique samples from general_stats_table")
            return sample_list
        else:
            missing_cols = [col for col in ['sample', 'anchor'] if col not in df.columns]
            print(f"❌ Missing columns in parquet file: {missing_cols}")
            return ["00050101", "F1-1A_S1_R1_001"]  # Fallback samples
    except Exception as e:
        print(f"❌ Error loading MultiQC samples: {e}")
        return ["00050101", "F1-1A_S1_R1_001"]  # Fallback samples

# Load available samples
AVAILABLE_SAMPLES = load_multiqc_samples()

# Define dock configuration - minimal single tab
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
                        "id": "multiqc-tab",
                        "enableFloat": True
                    }
                ]
            }
        ]
    }
}

# Create tab content
tab_components = [
    dash_dock.Tab(
        id="multiqc-tab",
        children=[
            html.Div([
                # html.H4("MultiQC Report Viewer", 
                #        style={'margin': '10px', 'color': '#333', 'textAlign': 'center'}),
                # html.Div([
                #     html.A("🔗 Test Flask Route", href="/test", target="_blank", 
                #            style={'marginRight': '20px', 'color': 'blue'}),
                #     html.A("📊 Direct MultiQC Link", 
                #            href="/external/multiqc_output_fastqc_v1_30_0/multiqc_report.html", 
                #            target="_blank", style={'color': 'green'})
                # ], style={'textAlign': 'center', 'margin': '10px'}),
                # html.Hr(),
                html.Iframe(
                    id="multiqc-iframe",
                    src="/external/multiqc_output_fastqc_v1_30_0/multiqc_report.html",
                    style={
                        'width': '100%',
                        'height': 'calc(100vh - 200px)', 
                        'border': '2px solid #ddd',
                        'borderRadius': '8px'
                    }
                )
            ], style={
                'height': '100%', 
                'padding': '15px',
                'backgroundColor': '#f9f9f9'
            })
        ]
    )
]

# App layout
app.layout = dmc.MantineProvider(
    theme={"colorScheme": "light"},
    children=[
    html.Div([
        html.H1("🧪 Minimal Depictio x MultiQC interface prototype", 
               style={'textAlign': 'center', 'margin': '20px', 'color': '#2c3e50'}),
        
        # html.Div([
        #     "✅ Flask serving external HTML files",
        #     html.Br(),
        #     "✅ Single dash-dock tab with iframe", 
        #     html.Br(),
        #     "✅ Tab floating enabled (tabEnableFloat: True)",
        # ], style={
        #     'backgroundColor': '#e8f5e8', 
        #     'padding': '15px', 
        #     'margin': '20px',
        #     'borderRadius': '8px',
        #     'border': '1px solid #4CAF50'
        # })
        # ,
        
        # MultiQC Toolbox Automation Panel
        html.Div([
            html.H4("🔍 MultiQC Toolbox Automation"),
            
            # HIGHLIGHT SAMPLES SECTION
            html.Div([
                html.H5("🎨 Highlight Samples", style={'margin': '0 0 10px 0', 'color': '#1976d2'}),
                html.Div([
                    # TagsInput for sample patterns with autocomplete
                    dmc.TagsInput(
                        id="highlight-pattern-input",
                        label="Sample Patterns",
                        placeholder="Type or select samples (supports regex)",
                        value=[],
                        data=AVAILABLE_SAMPLES,
                        maxDropdownHeight=300,
                        limit=10,
                        clearable=True,
                        searchValue="",
                        style={'width': '280px', 'marginRight': '10px'}
                    ),
                    # Regex toggle
                    dmc.Switch(
                        id="highlight-regex-switch",
                        label="Use Regex",
                        checked=False,
                        style={'marginRight': '15px'}
                    ),
                    # Action buttons
                    dmc.Button("Clear All", id="highlight-clear-btn", variant="outline", color="red", size="sm", style={'margin': '0 5px'}),
                ], style={'display': 'flex', 'alignItems': 'end', 'flexWrap': 'wrap', 'gap': '10px'})
            ], style={
                'backgroundColor': '#e3f2fd', 
                'padding': '15px', 
                'margin': '10px 0',
                'borderRadius': '8px',
                'border': '2px solid #1976d2'
            }),
            
            # SHOW/HIDE SAMPLES SECTION
            html.Div([
                html.H5("👁️ Show/Hide Samples", style={'margin': '0 0 10px 0', 'color': '#388e3c'}),
                html.Div([
                    # TagsInput for sample patterns with autocomplete
                    dmc.TagsInput(
                        id="showhide-pattern-input",
                        label="Sample Patterns",
                        placeholder="Type or select samples (supports regex)",
                        value=[],
                        data=AVAILABLE_SAMPLES,
                        maxDropdownHeight=300,
                        limit=10,
                        clearable=True,
                        searchValue="",
                        style={'width': '280px', 'marginRight': '10px'}
                    ),
                    # Regex toggle
                    dmc.Switch(
                        id="showhide-regex-switch",
                        label="Use Regex",
                        checked=False,
                        style={'marginRight': '15px'}
                    ),
                    # Show/Hide mode toggle
                    dmc.SegmentedControl(
                        id="showhide-mode-control",
                        value="show",
                        data=[
                            {"label": "👁️ Show Only", "value": "show"},
                            {"label": "🙈 Hide", "value": "hide"}
                        ],
                        style={'marginRight': '15px'}
                    ),
                    # Action buttons
                    dmc.Button("Clear All", id="showhide-clear-btn", variant="outline", color="red", size="sm", style={'margin': '0 5px'}),
                ], style={'display': 'flex', 'alignItems': 'end', 'flexWrap': 'wrap', 'gap': '10px'})
            ], style={
                'backgroundColor': '#e8f5e9', 
                'padding': '15px', 
                'margin': '10px 0',
                'borderRadius': '8px',
                'border': '2px solid #388e3c'
            }),
            
            # DEBUG SECTION (collapsible)
            dmc.Accordion(
                children=[
                    dmc.AccordionItem([
                        dmc.AccordionControl("🔧 Debug Controls"),
                        dmc.AccordionPanel([
                            dmc.Group([
                                dmc.Button("Inspect MultiQC", id="inspect-highlight-btn", variant="outline", size="xs"),
                                dmc.Button("Inspect Show/Hide", id="inspect-showhide-btn", variant="outline", size="xs"),
                                dmc.Button("Test Pattern Input", id="test-sample-input-btn", variant="outline", size="xs"),
                                dmc.Button("Test + Button", id="simulate-plus-btn", variant="outline", size="xs"),
                                dmc.Button("Test Apply", id="simulate-apply-btn", variant="outline", size="xs"),
                                dmc.Button("Test Hide + Button", id="test-hide-plus-btn", variant="outline", size="xs"),
                                dmc.Button("Test Hide Apply", id="test-hide-apply-btn", variant="outline", size="xs"),
                                dmc.Button("Test Enter", id="simulate-enter-btn", variant="outline", size="xs"),
                            ], gap="xs", style={'flexWrap': 'wrap'})
                        ])
                    ], value="debug-controls")
                ],
                style={'margin': '10px 0'}
            ),
            
            # OUTPUT AREA (collapsible)
            dmc.Accordion(
                children=[
                    dmc.AccordionItem([
                        dmc.AccordionControl("📋 Debug Console Output"),
                        dmc.AccordionPanel([
                            html.Pre(id="investigation-output", style={
                                'backgroundColor': '#f8f9fa', 
                                'padding': '10px', 
                                'margin': '0',
                                'borderRadius': '4px',
                                'border': '1px solid #ddd',
                                'fontSize': '12px',
                                'maxHeight': '300px',
                                'overflow': 'auto',
                                'whiteSpace': 'pre-wrap'
                            })
                        ])
                    ], value="debug-output")
                ],
                value=["debug-output"],  # Start with output expanded
                multiple=True,
                style={'margin': '10px 0'}
            )
        ], style={
            'backgroundColor': '#fff', 
            'padding': '20px', 
            'margin': '20px',
            'borderRadius': '12px',
            'border': '1px solid #ddd',
            'boxShadow': '0 2px 8px rgba(0,0,0,0.1)'
        }),
        
        # Dock container
        html.Div([
            dash_dock.DashDock(
                id='minimal-dock',
                model=dock_config,
                children=tab_components,
                useStateForModel=True,
                style={
                    'position': 'relative',
                    'height': '100%',
                    'width': '100%',
                    'overflow': 'hidden'
                }
            )
        ], style={
            'height': '70vh',
            'width': '95%',
            'margin': '20px auto',
            'border': '3px solid #3498db',
            'borderRadius': '10px',
            'backgroundColor': 'white'
        }, id='dock-container'),
        
        # Hidden components for clientside functionality
        dcc.Interval(id='inject-fullscreen-btn', interval=300, n_intervals=0, max_intervals=1),
        html.Div(id='fullscreen-trigger', style={'display': 'none'})
    ], style={'minHeight': '100vh', 'backgroundColor': '#ecf0f1'})
    ]
)

# Clientside callback to inject fullscreen button into dash-dock toolbar
clientside_callback(
    ClientsideFunction(
        namespace='dashDock',
        function_name='injectFullscreenButton'
    ),
    Output('fullscreen-trigger', 'children'),
    Input('inject-fullscreen-btn', 'n_intervals')
)

# ESC key handler to restore from expanded view
clientside_callback(
    ClientsideFunction(
        namespace='dashDock',
        function_name='setupEscapeKeyHandler'
    ),
    Output('fullscreen-trigger', 'title'),
    Input('minimal-dock', 'id')
)

# Combined MultiQC Automation Callback - Using modular JS functions!
clientside_callback(
    ClientsideFunction(
        namespace='multiqc',
        function_name='handleMultiQCCallback'
    ),
    Output('investigation-output', 'children'),
    [# Debug buttons - Inputs
     Input('inspect-highlight-btn', 'n_clicks'),
     Input('inspect-showhide-btn', 'n_clicks'),
     Input('test-sample-input-btn', 'n_clicks'),
     Input('simulate-plus-btn', 'n_clicks'),
     Input('simulate-apply-btn', 'n_clicks'),
     Input('test-hide-plus-btn', 'n_clicks'),
     Input('test-hide-apply-btn', 'n_clicks'),
     Input('simulate-enter-btn', 'n_clicks'),
     # Clear buttons - Inputs
     Input('highlight-clear-btn', 'n_clicks'),
     Input('showhide-clear-btn', 'n_clicks'),
     # Automatic triggers on dropdown changes - Inputs
     Input('highlight-pattern-input', 'value'),
     Input('showhide-pattern-input', 'value')],
    [# All States (for configuration)
     State('highlight-regex-switch', 'checked'),
     State('showhide-regex-switch', 'checked'),
     State('showhide-mode-control', 'value')]
)


if __name__ == '__main__':
    print("🚀 Starting minimal dash-dock + MultiQC test...")
    print("📍 http://localhost:8054")
    print("🔧 Test Flask: http://localhost:8054/test")
    print("📊 Test MultiQC: http://localhost:8054/external/multiqc_output_fastqc_v1_30_0/multiqc_report.html")
    print("\n🧪 CRITICAL TEST: Checking if iframe access is blocked by CORS")
    print("   - If buttons show 'SAME-ORIGIN ACCESS CONFIRMED' → No CORS issues")
    print("   - If buttons show 'CORS BLOCKED' → CORS is the problem")
    app.run(debug=True, port=8054)