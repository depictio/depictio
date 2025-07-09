#!/usr/bin/env python3
"""
Debug app for JavaScript theme issues
Isolates the theme switching logic to identify the "Cannot read properties of undefined (reading 'apply')" error
"""

import dash
import dash_draggable
import dash_mantine_components as dmc
import pandas as pd
import plotly
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, dcc, html
from dash_iconify import DashIconify

print(f"Plotly version: {plotly.__version__}")

# Initialize the Dash app
app = dash.Dash(__name__)

# Add Mantine figure templates
# dmc.add_figure_templates()

# Create sample data for the graph
sample_data = pd.DataFrame(
    {
        "x": ["Dashboards", "Projects", "About", "Settings", "Analytics"],
        "y": [15, 25, 10, 30, 20],
        "color": ["orange", "teal", "gray", "blue", "green"],
    }
)

# Simple layout with NavLinks and theme switch
app.layout = dmc.MantineProvider(
    id="mantine-provider",
    theme={"colorScheme": "light"},
    children=[
        dmc.AppShell(
            navbar={
                "width": 300,
                "breakpoint": "sm",
            },
            children=[
                # Navbar with NavLinks
                dmc.AppShellNavbar(
                    id="sidebar",
                    children=[
                        html.H3("Debug Theme Test", style={"padding": "20px"}),
                        # Test NavLinks with icons - one active, others inactive
                        dmc.NavLink(
                            id="navlink-dashboards",
                            label="Dashboards (ACTIVE)",
                            leftSection=DashIconify(icon="material-symbols:dashboard", height=25),
                            href="/dashboards",
                            style={"padding": "20px"},
                            color="orange",
                            active=True,  # This should keep its orange color
                        ),
                        dmc.NavLink(
                            id="navlink-projects",
                            label="Projects (inactive)",
                            leftSection=DashIconify(icon="mdi:jira", height=25),
                            href="/projects",
                            style={"padding": "20px"},
                            color="teal",
                            active=False,  # This should use theme colors (black/white)
                        ),
                        dmc.NavLink(
                            id="navlink-about",
                            label="About (inactive)",
                            leftSection=DashIconify(icon="mingcute:question-line", height=25),
                            href="/about",
                            style={"padding": "20px"},
                            color="gray",
                            active=False,  # This should use theme colors (black/white)
                        ),
                        # Theme switch with FIXED icons
                        html.Hr(),
                        dmc.Center(
                            [
                                dmc.Switch(
                                    id="theme-switch",
                                    checked=False,
                                    size="lg",
                                    onLabel=DashIconify(
                                        icon="tabler:sun", width=20, color="yellow"
                                    ),  # Dark mode = sun
                                    offLabel=DashIconify(
                                        icon="tabler:moon", width=20, color="blue"
                                    ),  # Light mode = moon
                                )
                            ]
                        ),
                        html.P(
                            "Expected: Light=🌙 Dark=☀️",
                            style={"padding": "10px", "fontSize": "12px"},
                        ),
                    ],
                ),
                # Main content
                dmc.AppShellMain(
                    id="page-content",
                    children=[
                        html.Div(
                            id="debug-output",
                            style={"padding": "20px"},
                            children=[
                                html.H1("Theme Debug Test"),
                                html.Div(
                                    id="current-page",
                                    children="Welcome! Click NavLinks to navigate.",
                                ),
                                html.Hr(),
                                html.H3("Expected Behavior:"),
                                html.Ul(
                                    [
                                        html.Li("🟠 ACTIVE NavLink icon should keep orange color"),
                                        html.Li(
                                            "⚫⚪ INACTIVE NavLink icons should be black (light) / white (dark)"
                                        ),
                                        html.Li(
                                            "🌙☀️ Theme toggle: Light mode = moon, Dark mode = sun"
                                        ),
                                        html.Li(
                                            "📊 Plotly figure should use mantine_light/mantine_dark templates"
                                        ),
                                        html.Li(
                                            "🎨 Full page theme should change (backgrounds, text, everything)"
                                        ),
                                    ]
                                ),
                                html.Hr(),
                                html.Div(id="theme-indicator"),
                                html.Hr(),
                                html.H3("Draggable Plotly Figure Test:"),
                                # Add draggable layout with plotly figure
                                html.Div([
                                    html.H4("🔧 Debug Info:"),
                                    html.P("Layout IDs: 'card-A', 'card-1' | Component IDs: 'card-A', 'card-1'"),
                                    html.P("Expected: Both should match exactly for positioning to work"),
                                ]),
                                dash_draggable.ResponsiveGridLayout(
                                    id="draggable",
                                    clearSavedLayout=False,
                                    layouts={},  # Start with empty, will be set by callback
                                    isDraggable=True,
                                    isResizable=True,
                                    children=[
                                        dmc.Card(
                                            id="card-A",
                                            children=[
                                                dmc.CardSection(
                                                    dmc.Title("📊 Draggable Plotly Chart", order=4),
                                                    withBorder=True,
                                                    inheritPadding=True,
                                                    py="xs",
                                                ),
                                                dcc.Graph(
                                                    id="test-graph",
                                                    figure={},  # Will be populated by callback
                                                    style={"height": "100%"},
                                                ),
                                            ],
                                            withBorder=True,
                                            shadow="sm",
                                            radius="md",
                                            style={"height": "100%"},
                                        ),
                                        dmc.Card(
                                            id="card-1",
                                            children=[
                                                dmc.CardSection(
                                                    dmc.Title("🎛️ Draggable Controls", order=4),
                                                    withBorder=True,
                                                    inheritPadding=True,
                                                    py="xs",
                                                ),
                                                html.P(
                                                    "Try dragging and resizing the cards above!"
                                                ),
                                                html.P(
                                                    "This tests theme integration with draggable components."
                                                ),
                                            ],
                                            withBorder=True,
                                            shadow="sm",
                                            radius="md",
                                            style={"height": "100%"},
                                        ),
                                    ],
                                    style={
                                        "width": "100%",
                                        "height": "600px",
                                        "margin": "20px 0",
                                    },
                                ),
                                html.Hr(),
                                html.H3("Debug Console:"),
                                html.P("Check browser console for detailed logs"),
                                html.P(
                                    "🔍 Focus: Test if theme issues occur within draggable components"
                                ),
                            ],
                        )
                    ],
                ),
            ],
        ),
        # Theme store
        dcc.Store(id="theme-store", data="light"),
        # Draggable layout stores
        dcc.Store(id="stored-draggable-layouts", storage_type="memory", data={}),
        dcc.Store(id="stored-draggable-children", storage_type="memory", data={}),
    ],
)


# Theme switch callback
@app.callback(
    Output("theme-store", "data", allow_duplicate=True),
    Input("theme-switch", "checked"),
    prevent_initial_call=True,
)
def update_theme_store(checked):
    theme = "dark" if checked else "light"
    print(f"Theme switch: {theme}")
    return theme


# Theme indicator callback
@app.callback(
    Output("theme-indicator", "children"),
    Input("theme-store", "data"),
)
def update_theme_indicator(theme):
    icon = "🌙" if theme == "light" else "☀️"
    color = "black" if theme == "light" else "white"
    bg = "white" if theme == "light" else "black"
    return html.Div(
        f"{icon} Current theme: {theme.upper()}",
        style={
            "padding": "10px",
            "backgroundColor": bg,
            "color": color,
            "border": f"2px solid {color}",
            "borderRadius": "5px",
            "textAlign": "center",
            "fontWeight": "bold",
        },
    )


# Update Mantine Provider theme
@app.callback(
    Output("mantine-provider", "theme"),
    Input("theme-store", "data"),
)
def update_mantine_theme(theme):
    return {"colorScheme": theme}


# NavLink click callbacks to update content and active states
@app.callback(
    [
        Output("current-page", "children"),
        Output("navlink-dashboards", "active"),
        Output("navlink-projects", "active"),
        Output("navlink-about", "active"),
    ],
    [
        Input("navlink-dashboards", "n_clicks"),
        Input("navlink-projects", "n_clicks"),
        Input("navlink-about", "n_clicks"),
    ],
    prevent_initial_call=True,
)
def update_page_content(*_):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if button_id == "navlink-dashboards":
        return (
            "📊 DASHBOARDS PAGE - This NavLink should have ORANGE icon!",
            True,  # dashboards active
            False,  # projects inactive
            False,  # about inactive
        )
    elif button_id == "navlink-projects":
        return (
            "📁 PROJECTS PAGE - This NavLink should have TEAL icon!",
            False,  # dashboards inactive
            True,  # projects active
            False,  # about inactive
        )
    elif button_id == "navlink-about":
        return (
            "❓ ABOUT PAGE - This NavLink should have GRAY icon!",
            False,  # dashboards inactive
            False,  # projects inactive
            True,  # about active
        )

    return dash.no_update


# Update page styles for theme change
@app.callback(
    [
        Output("page-content", "style"),
        Output("sidebar", "style"),
    ],
    Input("theme-store", "data"),
)
def update_page_styles(theme):
    if theme == "dark":
        page_style = {"backgroundColor": "#1a1b1e", "color": "#ffffff", "minHeight": "100vh"}
        sidebar_style = {"backgroundColor": "#25262b", "color": "#ffffff"}
    else:
        page_style = {"backgroundColor": "#ffffff", "color": "#000000", "minHeight": "100vh"}
        sidebar_style = {"backgroundColor": "#ffffff", "color": "#000000"}

    return page_style, sidebar_style


# Update Plotly figure with Mantine template
@app.callback(
    Output("test-graph", "figure"),
    Input("theme-store", "data"),
)
def update_plotly_figure(theme):
    # Use Mantine templates based on theme
    template = "plotly_dark" if theme == "dark" else "plotly_white"
    # template = "mantine_dark" if theme == "dark" else "mantine_light"

    # Create a bar chart with the sample data
    fig = px.bar(
        sample_data,
        x="x",
        y="y",
        color="color",
        title=f"📊 Sample Chart (Template: {template})",
        template=template,
        color_discrete_map={
            "orange": "#fd7e14",
            "teal": "#20c997",
            "gray": "#868e96",
            "blue": "#339af0",
            "green": "#51cf66",
        },
    )

    # Customize the layout
    fig.update_layout(
        showlegend=False,
        height=400,
        title_font_size=16,
    )

    return fig


# Initialize custom layout on startup
@app.callback(
    Output("draggable", "layouts"),
    Input("theme-store", "data"),  # Trigger on app startup
    prevent_initial_call=False,  # Allow initial call
)
def initialize_custom_layout(theme):
    """Initialize the custom layout with our IDs"""
    custom_layout = {
        "lg": [
            {"i": "card-A", "x": 0, "y": 0, "w": 6, "h": 8},
            {"i": "card-1", "x": 6, "y": 0, "w": 6, "h": 8},
        ]
    }
    print(f"🎯 INITIALIZING CUSTOM LAYOUT: {custom_layout}")
    return custom_layout

# Draggable layout callback to save layouts
@app.callback(
    Output("stored-draggable-layouts", "data"),
    Input("draggable", "layouts"),
    prevent_initial_call=True,
)
def save_draggable_layouts(layouts):
    """Save draggable layouts to store"""
    print(f"📐 LAYOUT CALLBACK - Received layouts: {layouts}")
    if layouts:
        for breakpoint, layout_items in layouts.items():
            print(f"  Breakpoint {breakpoint}:")
            for item in layout_items:
                print(f"    Item ID '{item.get('i')}': x={item.get('x')}, y={item.get('y')}, w={item.get('w')}, h={item.get('h')}")
    return layouts or {}


# Additional clientside callback for draggable theme integration
app.clientside_callback(
    """
    function(theme_data) {
        console.log('🎯 DRAGGABLE THEME CALLBACK START');
        console.log('Theme data for draggable:', theme_data);
        
        try {
            const theme = theme_data || 'light';
            
            // Update draggable container theme
            const draggableContainer = document.getElementById('draggable');
            if (draggableContainer) {
                const isDark = theme === 'dark';
                draggableContainer.style.backgroundColor = isDark ? '#1a1b1e' : '#ffffff';
                
                // Update all cards within draggable
                const cards = draggableContainer.querySelectorAll('.mantine-Card-root');
                cards.forEach(card => {
                    card.style.backgroundColor = isDark ? '#25262b' : '#ffffff';
                    card.style.color = isDark ? '#ffffff' : '#000000';
                    card.style.borderColor = isDark ? '#373a40' : '#dee2e6';
                });
                
                console.log(`🎯 Updated ${cards.length} draggable cards for ${theme} theme`);
            }
            
            // Trigger resize for any plots within draggable
            setTimeout(() => {
                if (window.Plotly) {
                    const plots = document.querySelectorAll('#draggable .js-plotly-plot');
                    plots.forEach(plot => {
                        console.log('🔄 Resizing draggable plot for theme change');
                        window.Plotly.Plots.resize(plot);
                    });
                }
            }, 100);
            
            console.log('🎯 DRAGGABLE THEME CALLBACK END');
            return window.dash_clientside.no_update;
            
        } catch (error) {
            console.error('❌ Draggable theme error:', error);
            return window.dash_clientside.no_update;
        }
    }
    """,
    Output("stored-draggable-children", "data", allow_duplicate=True),
    Input("theme-store", "data"),
    prevent_initial_call=True,
)

# SIMPLIFIED: NavLink icon theme callback - focused only on icons
app.clientside_callback(
    """
    function(theme_data) {
        console.log('🎨 ICON THEME CALLBACK START');
        console.log('Theme data:', theme_data);
        
        try {
            const theme = theme_data || 'light';
            const iconColor = theme === 'dark' ? '#ffffff' : '#000000';
            console.log(`Theme: ${theme}, Icon color: ${iconColor}`);
            
            // Find all NavLinks and update their icons
            const navLinks = document.querySelectorAll('#sidebar .mantine-NavLink-root');
            console.log(`Found ${navLinks.length} NavLinks`);
            
            navLinks.forEach((navLink, index) => {
                const isActive = navLink.getAttribute('data-active') === 'true';
                const icons = navLink.querySelectorAll('svg, [class*="iconify"], .iconify');
                
                console.log(`NavLink ${index}: active=${isActive}, icons=${icons.length}`);
                
                icons.forEach(icon => {
                    if (isActive) {
                        // Active NavLink: clear forced styles to show original color
                        icon.style.color = '';
                        icon.style.fill = '';
                        console.log('  🟠 Preserved active NavLink icon color');
                    } else {
                        // Inactive NavLink: use theme color
                        icon.style.color = iconColor + ' !important';
                        icon.style.fill = iconColor + ' !important';
                        console.log(`  ⚫⚪ Applied theme color: ${iconColor}`);
                    }
                    
                    // Handle SVG paths
                    if (icon.tagName === 'SVG') {
                        const paths = icon.querySelectorAll('path');
                        paths.forEach(path => {
                            if (!isActive) {
                                path.style.fill = iconColor + ' !important';
                            } else {
                                path.style.fill = 'currentColor';
                            }
                        });
                    }
                });
            });
            
            console.log('🎨 ICON THEME CALLBACK END');
            return window.dash_clientside.no_update;
            
        } catch (error) {
            console.error('❌ Icon theme error:', error);
            return window.dash_clientside.no_update;
        }
    }
    """,
    Output("theme-indicator", "children", allow_duplicate=True),
    Input("theme-store", "data"),
    prevent_initial_call=True,
)

# Debug callback to inspect DOM structure
app.clientside_callback(
    """
    function(layouts) {
        console.log('🔍 LAYOUT DEBUG CALLBACK');
        console.log('Received layouts:', layouts);
        
        // Check DOM structure
        const draggableContainer = document.getElementById('draggable');
        if (draggableContainer) {
            console.log('📦 Draggable container found');
            
            // Find all children with IDs
            const children = draggableContainer.querySelectorAll('[id]');
            console.log(`Found ${children.length} children with IDs:`);
            
            children.forEach((child, index) => {
                console.log(`  Child ${index}: ID="${child.id}", tag=${child.tagName}`);
                
                // Check if this child has a corresponding layout item
                if (layouts && layouts.lg) {
                    const layoutItem = layouts.lg.find(item => item.i === child.id);
                    if (layoutItem) {
                        console.log(`    ✅ Layout found: x=${layoutItem.x}, y=${layoutItem.y}, w=${layoutItem.w}, h=${layoutItem.h}`);
                    } else {
                        console.log(`    ❌ NO LAYOUT FOUND for ID "${child.id}"`);
                    }
                }
            });
            
            // Check for React Grid Layout elements
            const gridItems = draggableContainer.querySelectorAll('.react-grid-item');
            console.log(`Found ${gridItems.length} react-grid-item elements:`);
            
            gridItems.forEach((item, index) => {
                const dataGrid = item.getAttribute('data-grid');
                const transform = item.style.transform;
                console.log(`  Grid item ${index}: data-grid="${dataGrid}", transform="${transform}"`);
            });
        }
        
        return window.dash_clientside.no_update;
    }
    """,
    Output("debug-output", "children", allow_duplicate=True),
    Input("stored-draggable-layouts", "data"),
    prevent_initial_call=True,
)

if __name__ == "__main__":
    print("Starting debug theme app...")
    print("Check browser console for detailed logging")
    print("Open: http://127.0.0.1:8051")
    app.run(debug=True, host="127.0.0.1", port=8051)
