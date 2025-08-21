#!/usr/bin/env python3
"""
Simple dash-dock example - replicating the basic 2-tab example
Just to verify dash-dock works properly before adding MultiQC
"""

import dash
import dash_dock
from dash import html, Input, Output, callback
import dash_mantine_components as dmc
from dash_iconify import DashIconify

# Initialize Dash app
app = dash.Dash(__name__)

# Define the dock layout configuration - exactly like the example
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
                        "name": "Tab 1",
                        "component": "text",
                        "id": "tab-1",
                    }
                ]
            },
            {
                "type": "tabset",
                "children": [
                    {
                        "type": "tab",
                        "name": "Tab 2",
                        "component": "text",
                        "id": "tab-2",
                    }
                ]
            }
        ]
    }
}

# Create tab content components - exactly like the example
tab_components = [
    dash_dock.Tab(
        id="tab-1",
        children=[
            html.H3("Tab 1 Content"),
            html.P("This is the content of tab 1"),
            html.Ul([
                html.Li("First item"),
                html.Li("Second item"),
                html.Li("Third item"),
            ]),
            dmc.Button("Sample Button", variant="filled", color="blue"),
        ]
    ),
    dash_dock.Tab(
        id="tab-2",
        children=[
            html.H3("Tab 2 Content"),
            html.P("This is the content of tab 2"),
            html.Div([
                html.P("Some sample content:"),
                dmc.Card([
                    dmc.Text("Sample Card", fw=500),
                    dmc.Text("This is a sample DMC card component", size="sm"),
                ], withBorder=True, shadow="sm", radius="md", p="md"),
            ]),
        ]
    )
]

# Main app layout - wrapped in MantineProvider
app.layout = dmc.MantineProvider([
    html.H1("Simple Dash Dock Example - 2 Tabs"),
    html.P("Basic 2-tab dash-dock implementation to verify functionality"),
    
    dmc.Box(
        dash_dock.DashDock(
            id='dock-layout',
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
            'height': '60vh',
            'width': '100%',
            'position': 'relative',
            'overflow': 'hidden',
            'border': '2px solid #ccc',
            'borderRadius': '8px',
            'margin': '20px 0'
        }
    ),
    
    html.Div([
        html.H4("Expected Behavior:"),
        html.Ul([
            html.Li("Two tabs should be visible: 'Tab 1' and 'Tab 2'"),
            html.Li("Tabs should be floatable (drag tab header to float)"),
            html.Li("Content should display properly in each tab"),
            html.Li("No MultiQC or external files - just basic Dash components"),
        ], style={'color': '#666'})
    ], style={'margin': '20px 0', 'padding': '15px', 'backgroundColor': '#f5f5f5', 'borderRadius': '8px'})
])

if __name__ == '__main__':
    print("🚀 Starting simple dash-dock 2-tab example...")
    print("📍 http://localhost:8052")
    print("✅ No external files - just basic dash-dock functionality")
    app.run(debug=True, port=8052)