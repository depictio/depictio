"""
Inline Editable Text Component

A component where you can directly edit the rendered text by clicking on it.
Perfect for dashboard section delimiters - no separate editor/preview needed.
"""

import dash
import dash_mantine_components as dmc
from dash import Dash, Input, Output, State, callback, clientside_callback, dcc, html
from dash_iconify import DashIconify

app = Dash(__name__, suppress_callback_exceptions=True)

def create_inline_editable_text(component_id, initial_text="# Section Title", initial_order=1):
    """Create an inline editable text component."""
    
    return html.Div([
        # The editable text display
        dmc.Title(
            initial_text.lstrip('#').strip() if initial_text.startswith('#') else initial_text,
            order=initial_order,
            id={"type": "editable-title", "index": component_id},
            style={
                "cursor": "text",
                "padding": "4px 8px",
                "borderRadius": "4px",
                "transition": "background-color 0.2s",
                "margin": "8px 0",
                "minHeight": "24px",
                "border": "1px dashed transparent"
            },
            c="dark"
        ),
        
        # Hidden input for editing
        dmc.TextInput(
            id={"type": "edit-input", "index": component_id},
            value=initial_text,
            style={"display": "none"}
        ),
        
        # Control buttons (initially hidden)
        dmc.Group([
            dmc.ActionIcon(
                DashIconify(icon="material-symbols:edit", width=12),
                size="xs",
                variant="light",
                color="blue",
                id={"type": "edit-btn", "index": component_id},
                style={"opacity": "0", "transition": "opacity 0.2s"}
            ),
            dmc.Menu([
                dmc.MenuTarget(
                    dmc.ActionIcon(
                        DashIconify(icon="material-symbols:format-size", width=12),
                        size="xs",
                        variant="light",
                        color="gray",
                        style={"opacity": "0", "transition": "opacity 0.2s"}
                    )
                ),
                dmc.MenuDropdown([
                    dmc.MenuItem("H1", id={"type": "h1-menu", "index": component_id}),
                    dmc.MenuItem("H2", id={"type": "h2-menu", "index": component_id}),
                    dmc.MenuItem("H3", id={"type": "h3-menu", "index": component_id}),
                    dmc.MenuItem("H4", id={"type": "h4-menu", "index": component_id}),
                    dmc.MenuItem("H5", id={"type": "h5-menu", "index": component_id}),
                    dmc.MenuDivider(),
                    dmc.MenuItem("Text", id={"type": "text-menu", "index": component_id}),
                ])
            ]),
            dmc.ActionIcon(
                DashIconify(icon="material-symbols:delete", width=12),
                size="xs",
                variant="light",
                color="red",
                id={"type": "delete-btn", "index": component_id},
                style={"opacity": "0", "transition": "opacity 0.2s"}
            ),
        ], gap="xs", style={"marginTop": "4px"}),
        
        # Store for component state
        dcc.Store(
            id={"type": "text-store", "index": component_id},
            data={"text": initial_text, "order": initial_order, "editing": False}
        )
        
    ], style={
        "border": "1px solid transparent",
        "borderRadius": "8px",
        "padding": "8px",
        "marginBottom": "8px",
        "position": "relative"
    }, id={"type": "text-container", "index": component_id})

# Test layout with multiple inline editable components
app.layout = dmc.MantineProvider([
    dmc.Container([
        dmc.Title("Inline Editable Text Component", order=1),
        dmc.Text("Click on any text to edit directly. Use the format menu to change header levels.", c="dimmed"),
        dmc.Space(h="md"),
        
        dmc.Alert(
            "Hover over text to see controls. Click to edit inline. No separate editor needed!",
            title="How to use",
            icon=DashIconify(icon="material-symbols:info"),
            color="blue"
        ),
        
        dmc.Space(h="lg"),
        
        # Multiple inline editable components
        create_inline_editable_text("section-1", "# Main Dashboard", 1),
        
        # Simulated dashboard content
        dmc.Grid([
            dmc.GridCol([
                dmc.Card([
                    dmc.Text("Chart Component", fw=500),
                    dmc.Text("Sample visualization", size="sm", c="dimmed")
                ], withBorder=True, shadow="sm", radius="md", p="md")
            ], span=6),
            dmc.GridCol([
                dmc.Card([
                    dmc.Text("Table Component", fw=500),
                    dmc.Text("Sample data table", size="sm", c="dimmed")
                ], withBorder=True, shadow="sm", radius="md", p="md")
            ], span=6),
        ]),
        
        create_inline_editable_text("section-2", "## Analytics Overview", 2),
        
        dmc.Grid([
            dmc.GridCol([
                dmc.Card([
                    dmc.Text("KPI 1", fw=500),
                    dmc.Text("42", size="xl", c="blue")
                ], withBorder=True, shadow="sm", radius="md", p="md")
            ], span=4),
            dmc.GridCol([
                dmc.Card([
                    dmc.Text("KPI 2", fw=500),
                    dmc.Text("89%", size="xl", c="green")
                ], withBorder=True, shadow="sm", radius="md", p="md")
            ], span=4),
            dmc.GridCol([
                dmc.Card([
                    dmc.Text("KPI 3", fw=500),
                    dmc.Text("156", size="xl", c="orange")
                ], withBorder=True, shadow="sm", radius="md", p="md")
            ], span=4),
        ]),
        
        create_inline_editable_text("section-3", "### Detailed Metrics", 3),
        create_inline_editable_text("section-4", "#### Sub-metrics", 4),
        create_inline_editable_text("section-5", "##### Fine Details", 5),
        
        dmc.Card([
            dmc.Text("Additional Content", fw=500),
            dmc.Text("This demonstrates how the inline editable text works as section delimiters.", size="sm")
        ], withBorder=True, shadow="sm", radius="md", p="md"),
        
        dmc.Space(h="xl"),
        
        # Add button to create new sections
        dmc.Button(
            "Add New Section",
            leftSection=DashIconify(icon="material-symbols:add", width=16),
            variant="light",
            id="add-section-btn"
        ),
        
        # Container for new sections
        html.Div(id="new-sections-container"),
        
        dmc.Space(h="xl"),
        
        # Features list
        dmc.Card([
            dmc.Title("Component Features", order=3),
            dmc.List([
                dmc.ListItem("Direct inline editing - click to edit"),
                dmc.ListItem("Hover controls for formatting"),
                dmc.ListItem("Header level menu (H1-H5, Text)"),
                dmc.ListItem("Visual feedback with hover states"),
                dmc.ListItem("No separate editor/preview needed"),
                dmc.ListItem("Perfect for dashboard delimiters"),
                dmc.ListItem("Clean, minimal interface"),
            ])
        ], withBorder=True, p="lg")
        
    ], size="lg")
])

# Client-side hover effects
clientside_callback(
    """
    function(n_intervals) {
        // Add hover effects to containers
        const containers = document.querySelectorAll('[id*="text-container"]');
        
        containers.forEach(container => {
            container.addEventListener('mouseenter', function() {
                this.style.border = '1px dashed #ddd';
                this.style.backgroundColor = 'var(--app-surface-color, #f9f9f9)';
                
                // Show controls
                const controls = this.querySelectorAll('[style*="opacity: 0"]');
                controls.forEach(control => {
                    control.style.opacity = '1';
                });
            });
            
            container.addEventListener('mouseleave', function() {
                this.style.border = '1px solid transparent';
                this.style.backgroundColor = 'transparent';
                
                // Hide controls
                const controls = this.querySelectorAll('[style*="opacity: 1"]');
                controls.forEach(control => {
                    control.style.opacity = '0';
                });
            });
        });
        
        return window.dash_clientside.no_update;
    }
    """,
    Output("new-sections-container", "style"),
    Input("new-sections-container", "id"),
    prevent_initial_call=False
)

# Toggle edit mode when clicking on title
@callback(
    [
        Output({"type": "editable-title", "index": dash.MATCH}, "style"),
        Output({"type": "edit-input", "index": dash.MATCH}, "style"),
        Output({"type": "text-store", "index": dash.MATCH}, "data"),
    ],
    [
        Input({"type": "editable-title", "index": dash.MATCH}, "n_clicks"),
        Input({"type": "edit-btn", "index": dash.MATCH}, "n_clicks"),
        Input({"type": "edit-input", "index": dash.MATCH}, "n_submit"),
        Input({"type": "edit-input", "index": dash.MATCH}, "n_blur"),
    ],
    [
        State({"type": "edit-input", "index": dash.MATCH}, "value"),
        State({"type": "text-store", "index": dash.MATCH}, "data"),
    ],
    prevent_initial_call=True
)
def toggle_edit_mode(title_clicks, edit_clicks, input_submit, input_blur, input_value, store_data):
    """Toggle between display and edit modes."""
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update, dash.no_update, dash.no_update
    
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    
    # Base styles
    title_style = {
        "cursor": "text",
        "padding": "4px 8px",
        "borderRadius": "4px",
        "transition": "background-color 0.2s",
        "margin": "8px 0",
        "minHeight": "24px",
        "border": "1px dashed transparent"
    }
    input_style = {"display": "none"}
    
    # Current editing state
    is_editing = store_data.get("editing", False) if store_data else False
    
    if "editable-title" in trigger_id or "edit-btn" in trigger_id:
        # Start editing
        title_style["display"] = "none"
        input_style = {"display": "block", "width": "100%"}
        store_data["editing"] = True
        
    elif "edit-input" in trigger_id and ("n_submit" in ctx.triggered[0]["prop_id"] or "n_blur" in ctx.triggered[0]["prop_id"]):
        # Stop editing and save
        title_style["display"] = "block"
        input_style["display"] = "none"
        store_data["editing"] = False
        store_data["text"] = input_value
    
    return title_style, input_style, store_data

# Update title content and order from input
@callback(
    [
        Output({"type": "editable-title", "index": dash.MATCH}, "children"),
        Output({"type": "editable-title", "index": dash.MATCH}, "order"),
    ],
    Input({"type": "text-store", "index": dash.MATCH}, "data"),
    prevent_initial_call=True
)
def update_title_content(store_data):
    """Update title content and order when data changes."""
    if not store_data:
        return "Click to edit", 3
    
    text = store_data.get("text", "Click to edit")
    
    # Parse header level from text
    if text.startswith('#####'):
        return text[5:].strip(), 5
    elif text.startswith('####'):
        return text[4:].strip(), 4
    elif text.startswith('###'):
        return text[3:].strip(), 3
    elif text.startswith('##'):
        return text[2:].strip(), 2
    elif text.startswith('#'):
        return text[1:].strip(), 1
    else:
        return text, 6  # Use order 6 for regular text (smaller than h5)

# Handle header level menu clicks
@callback(
    Output({"type": "edit-input", "index": dash.MATCH}, "value"),
    [
        Input({"type": "h1-menu", "index": dash.MATCH}, "n_clicks"),
        Input({"type": "h2-menu", "index": dash.MATCH}, "n_clicks"),
        Input({"type": "h3-menu", "index": dash.MATCH}, "n_clicks"),
        Input({"type": "h4-menu", "index": dash.MATCH}, "n_clicks"),
        Input({"type": "h5-menu", "index": dash.MATCH}, "n_clicks"),
        Input({"type": "text-menu", "index": dash.MATCH}, "n_clicks"),
    ],
    State({"type": "edit-input", "index": dash.MATCH}, "value"),
    prevent_initial_call=True
)
def change_header_level(h1, h2, h3, h4, h5, text_click, current_value):
    """Change header level via menu."""
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update
    
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    
    # Extract text content (remove existing headers)
    text_content = current_value
    for prefix in ['##### ', '#### ', '### ', '## ', '# ']:
        if text_content.startswith(prefix):
            text_content = text_content[len(prefix):]
            break
    
    if "h1-menu" in trigger_id:
        return f"# {text_content}"
    elif "h2-menu" in trigger_id:
        return f"## {text_content}"
    elif "h3-menu" in trigger_id:
        return f"### {text_content}"
    elif "h4-menu" in trigger_id:
        return f"#### {text_content}"
    elif "h5-menu" in trigger_id:
        return f"##### {text_content}"
    elif "text-menu" in trigger_id:
        return text_content
    
    return dash.no_update

if __name__ == "__main__":
    print("Running Inline Editable Text Component Prototype...")
    print("Features:")
    print("- Click on text to edit directly")
    print("- Hover to see controls")
    print("- Format menu for header levels")
    print("- No separate editor/preview needed")
    print("- Perfect for dashboard section delimiters")
    print("Running on http://127.0.0.1:8061/")
    app.run(debug=True, port=8061)