#!/usr/bin/env python3
"""
Split Callback Prototype: Demonstrate render vs design callback separation

This minimal Dash app proves the concept of loading design callbacks on-demand
while keeping core rendering callbacks always loaded.
"""

import time
from dash import Dash, html, dcc, callback, Input, Output, State, MATCH, ALL
import dash_mantine_components as dmc

# Track startup time
APP_START_TIME = time.perf_counter()

# Create app
app = Dash(__name__, suppress_callback_exceptions=True)

# Flag to track if design callbacks are registered
DESIGN_CALLBACKS_REGISTERED = False


def register_core_rendering_callbacks(app):
    """
    Core rendering callbacks - ALWAYS loaded.
    These handle displaying data and basic interactivity.
    """
    print("✓ Registering core rendering callbacks...")

    @app.callback(
        Output({"type": "card-value", "index": MATCH}, "children"),
        Input({"type": "card-data-store", "index": MATCH}, "data"),
    )
    def render_card_value(data):
        """Render card value from data (core functionality)"""
        if not data:
            return "..."
        return f"{data.get('value', 0):.1f}"

    @app.callback(
        Output({"type": "card-title", "index": MATCH}, "children"),
        Input({"type": "card-data-store", "index": MATCH}, "data"),
    )
    def render_card_title(data):
        """Render card title (core functionality)"""
        if not data:
            return "Loading..."
        return data.get("title", "Card")


def register_design_callbacks(app):
    """
    Design/edit mode callbacks - LAZY loaded only when needed.
    These handle styling, color pickers, icon selection, etc.
    """
    global DESIGN_CALLBACKS_REGISTERED

    if DESIGN_CALLBACKS_REGISTERED:
        print("⚠️  Design callbacks already registered, skipping...")
        return

    print("✓ Registering design callbacks (LAZY)...")

    @app.callback(
        Output({"type": "card-container", "index": MATCH}, "style"),
        Input({"type": "card-color-picker", "index": MATCH}, "value"),
        State({"type": "card-container", "index": MATCH}, "style"),
    )
    def update_card_color(color, current_style):
        """Update card background color (design mode only)"""
        if not color:
            return current_style or {}

        style = current_style or {}
        style["backgroundColor"] = color
        return style

    @app.callback(
        Output({"type": "card-title-style", "index": MATCH}, "style"),
        Input({"type": "card-font-size-slider", "index": MATCH}, "value"),
    )
    def update_title_font_size(font_size):
        """Update title font size (design mode only)"""
        if not font_size:
            return {}
        return {"fontSize": f"{font_size}px"}

    DESIGN_CALLBACKS_REGISTERED = True
    print("✅ Design callbacks registered successfully")


def create_card(index, title, value):
    """Create a simple card component"""
    return dmc.Card(
        id={"type": "card-container", "index": index},
        children=[
            dmc.Text(
                id={"type": "card-title", "index": index},
                children=title,
                style={"fontSize": "14px", "fontWeight": "bold"},
            ),
            dmc.Text(
                id={"type": "card-title-style", "index": index},  # For design mode styling
                children="",
                style={"display": "none"},
            ),
            dmc.Text(
                id={"type": "card-value", "index": index},
                children=str(value),
                style={"fontSize": "24px"},
            ),
            dcc.Store(
                id={"type": "card-data-store", "index": index},
                data={"title": title, "value": value},
            ),
        ],
        style={
            "padding": "20px",
            "margin": "10px",
            "border": "1px solid #ddd",
            "borderRadius": "8px",
        },
    )


def create_design_controls(index):
    """Create design mode controls (color picker, font size slider)"""
    return dmc.Card(
        children=[
            dmc.Text("Design Controls", style={"fontWeight": "bold", "marginBottom": "10px"}),
            dmc.ColorPicker(
                id={"type": "card-color-picker", "index": index},
                format="hex",
                value="#ffffff",
            ),
            dmc.Slider(
                id={"type": "card-font-size-slider", "index": index},
                min=10,
                max=30,
                value=14,
                marks=[{"value": 14, "label": "14px"}],
            ),
        ],
        style={
            "padding": "15px",
            "margin": "10px",
            "border": "1px solid #e0e0e0",
            "borderRadius": "8px",
            "backgroundColor": "#f5f5f5",
        },
    )


# App layout
app.layout = dmc.MantineProvider(
    children=html.Div(
        [
            dmc.Title("Split Callback Prototype", order=2, style={"margin": "20px"}),
            dmc.Text(
                "This app demonstrates lazy loading of design callbacks",
                style={"margin": "20px", "color": "#666"},
            ),
            # Mode toggle
            dmc.Group(
                [
                    dmc.Button(
                        "View Mode (Fast Startup)",
                        id="view-mode-btn",
                        color="blue",
                        style={"margin": "20px"},
                    ),
                    dmc.Button(
                        "Design Mode (Load Design Callbacks)",
                        id="design-mode-btn",
                        color="orange",
                        style={"margin": "20px"},
                    ),
                ],
                style={"marginBottom": "20px"},
            ),
            # Status display
            html.Div(id="mode-status", style={"margin": "20px", "fontWeight": "bold"}),
            # Cards container
            html.Div(
                id="cards-container",
                children=[
                    create_card(1, "Revenue", 45620.50),
                    create_card(2, "Users", 1234),
                    create_card(3, "Conversion", 3.45),
                ],
                style={"display": "flex", "flexWrap": "wrap"},
            ),
            # Design controls (hidden initially)
            html.Div(id="design-controls-container"),
        ]
    )
)


# Register core callbacks on startup
register_core_rendering_callbacks(app)

startup_time = (time.perf_counter() - APP_START_TIME) * 1000
print(f"\n✅ App initialized in {startup_time:.0f}ms (core callbacks only)\n")


@app.callback(
    Output("mode-status", "children"),
    Output("design-controls-container", "children"),
    Input("view-mode-btn", "n_clicks"),
    Input("design-mode-btn", "n_clicks"),
)
def toggle_mode(view_clicks, design_clicks):
    """Toggle between view mode and design mode"""
    from dash import ctx

    if not ctx.triggered_id:
        return "Mode: View (core rendering only)", []

    if ctx.triggered_id == "design-mode-btn":
        # Lazy load design callbacks
        load_start = time.perf_counter()
        register_design_callbacks(app)
        load_time = (time.perf_counter() - load_start) * 1000

        # Show design controls
        controls = [create_design_controls(i) for i in [1, 2, 3]]

        return (
            dmc.Text(
                [
                    "Mode: Design (all callbacks loaded) ",
                    dmc.Badge(f"Loaded in {load_time:.0f}ms", color="green"),
                ]
            ),
            controls,
        )
    else:
        # View mode - hide design controls
        return "Mode: View (core rendering only)", []


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("SPLIT CALLBACK PROTOTYPE")
    print("=" * 80)
    print("\nInstructions:")
    print("1. App starts with ONLY core rendering callbacks (fast startup)")
    print("2. Click 'Design Mode' to lazy-load design callbacks")
    print("3. Design controls (color picker, font slider) will appear")
    print("4. Switch back to 'View Mode' to hide design controls")
    print("\nStarting server...")
    print("=" * 80 + "\n")

    app.run(debug=True, port=8051)
