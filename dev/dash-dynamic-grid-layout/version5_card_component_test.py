#!/usr/bin/env python3
"""
Version 5: Card Component Vertical Growing Test
This version replicates the exact DOM structure from the problematic card component
to isolate and test the vertical growing behavior issue
"""

import sys
import uuid

import dash
import dash_bootstrap_components as dbc
import dash_dynamic_grid_layout as dgl
import dash_mantine_components as dmc
from dash import Input, Output, dcc, html
from dash_iconify import DashIconify

# Add the depictio package to the path
sys.path.insert(0, "/Users/tweber/Gits/workspaces/depictio-workspace/depictio")


def generate_unique_index():
    return str(uuid.uuid4())


def create_problematic_card_component(component_uuid):
    """Create the exact card component structure that's not growing vertically"""

    # Create edit buttons with hover-only visibility (matching the DOM structure)
    edit_buttons = dmc.ActionIconGroup(
        [
            dmc.ActionIcon(
                id={"type": "drag-handle", "index": component_uuid},
                color="gray",
                variant="subtle",
                size="sm",
                children=DashIconify(icon="mdi:dots-grid", width=14, color="#888"),
                className="react-grid-dragHandle",
                style={"cursor": "grab"},
            ),
            dmc.ActionIcon(
                id={"type": "remove-box-button", "index": component_uuid},
                color="red",
                variant="filled",
                size="sm",
                children=DashIconify(icon="mdi:trash-can-outline", width=16, color="white"),
            ),
            dmc.ActionIcon(
                id={"type": "edit-box-button", "index": component_uuid},
                color="blue",
                variant="filled",
                size="sm",
                children=DashIconify(icon="mdi:pen", width=16, color="white"),
            ),
            dmc.ActionIcon(
                id={"type": "duplicate-box-button", "index": component_uuid},
                color="gray",
                variant="filled",
                size="sm",
                children=DashIconify(icon="mdi:content-copy", width=16, color="white"),
            ),
        ],
        orientation="horizontal",
    )

    # Create the Mantine Card content (the actual card data)
    mantine_card_content = dmc.Card(
        [
            dmc.Text(
                "Median of flipper_length_mm",
                size="sm",
                c="dimmed",
            ),
            dmc.Text(
                "197.0",
                size="xl",
                fw=700,
                c="dark",
                id={"index": component_uuid, "type": "card-value"},
            ),
        ],
        withBorder=True,
        id={"index": component_uuid, "type": "card"},
        style={
            "--paper-radius": "var(--mantine-radius-md)",
            "--paper-shadow": "var(--mantine-shadow-sm)",
            "height": "100%",
            "minHeight": "120px",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "borderColor": "var(--app-border-color, #ddd)",
            "padding": "var(--mantine-spacing-md)",
        },
        className="m_e615b15f mantine-Card-root m_1b7284a3 mantine-Paper-root",
    )

    # Create the Bootstrap card-body wrapper
    card_body = html.Div(
        mantine_card_content,
        id={"index": component_uuid, "type": "card-body"},
        className="card-body",
        style={
            "padding": "5px",
            "display": "flex",
            "flexDirection": "column",
            "height": "100%",
            "flex": "1",
            "minHeight": "0px",
        },
    )

    # Create the Bootstrap card wrapper (NUCLEAR: force absolute positioning)
    bootstrap_card = html.Div(
        card_body,
        id={"index": component_uuid, "type": "card-component"},
        className="card",
        style={
            "backgroundColor": "rgba(128, 0, 128, 0.3)",  # Purple to confirm it's working
            "position": "absolute",  # NUCLEAR: bypass all CSS issues
            "top": "0",
            "left": "0",
            "right": "0",
            "bottom": "0",
            "width": "100%",
            "height": "100%",
            "padding": "0px",
            "margin": "0px",
            "boxShadow": "none",
            "border": "none",
            "borderRadius": "4px",
            "display": "flex",
            "flexDirection": "column",
            "boxSizing": "border-box",
        },
    )

    # NUCLEAR: Skip all intermediate wrapper divs - put card directly in content
    content_wrapper = bootstrap_card

    # Create the main content div (dashboard-component-hover responsive-content)
    content_div = html.Div(
        [
            content_wrapper,
            # Buttons positioned absolutely
            html.Div(
                edit_buttons,
                style={
                    "position": "absolute",
                    "top": "4px",
                    "right": "8px",
                    "zIndex": 1000,
                    "alignItems": "center",
                    "height": "auto",
                    "background": "transparent",
                    "borderRadius": "6px",
                    "padding": "4px",
                },
            ),
        ],
        id=f"content-box-{component_uuid}",
        className="dashboard-component-hover responsive-content",
        style={
            "overflow": "visible",
            "width": "100%",
            "height": "100%",
            "boxSizing": "border-box",
            "padding": "5px",
            "border": "1px solid var(--app-border-color, #ddd)",
            "borderRadius": "8px",
            "background": "var(--app-surface-color, #ffffff)",
            "position": "relative",
            "minHeight": "100px",
            "transition": "all 0.3s ease",
            "display": "flex",
            "flexDirection": "column",
        },
    )

    # Create the flex wrapper - adjust for absolute positioning
    flex_wrapper = html.Div(
        content_div,
        style={
            "position": "absolute",
            "top": "25px",  # Leave space for drag handle
            "left": "0",
            "right": "0",
            "bottom": "0",
            "overflow": "hidden",
        },
    )

    # Create drag handle - make it small and positioned
    drag_handle = html.Div(
        "Drag",
        className="react-grid-dragHandle",
        style={
            "padding": "2px 8px",
            "cursor": "move",
            "background": "rgb(85, 85, 85)",
            "textAlign": "center",
            "color": "white",
            "fontSize": "10px",
            "position": "absolute",
            "top": "2px",
            "left": "2px",
            "zIndex": "1000",
            "borderRadius": "3px",
        },
    )

    # Create DraggableWrapper content - revert to normal layout
    draggable_content = html.Div(
        [drag_handle, flex_wrapper],
        id=f"box-{component_uuid}",
        style={
            "height": "100%",
            "display": "flex",
            "flexDirection": "column",
            "backgroundColor": "rgba(0, 255, 0, 0.3)",  # Green background to confirm it's applied
        },
    )

    # NUCLEAR OPTION: Make responsive wrapper fill parent with absolute positioning
    responsive_wrapper = html.Div(
        draggable_content,
        className="responsive-wrapper",
        style={
            "position": "absolute",
            "top": "0",
            "left": "0",
            "right": "0",
            "bottom": "0",
            "width": "100%",
            "height": "100%",
            "backgroundColor": "rgba(255, 255, 0, 0.3)",  # Yellow tint to track this element
            "boxSizing": "border-box",
            "padding": "0",
            "margin": "0",
        },
    )

    # Create DraggableWrapper
    draggable_wrapper = dgl.DraggableWrapper(
        id=f"box-{component_uuid}",
        children=[responsive_wrapper],
        handleText="Drag",
    )

    return draggable_wrapper


def create_card_vertical_growing_app():
    # Create app with assets folder for CSS
    import os

    assets_path = os.path.join(os.path.dirname(__file__), "assets")
    os.makedirs(assets_path, exist_ok=True)

    # Copy our CSS file to assets
    import shutil

    css_source = os.path.join(os.path.dirname(__file__), "prototype-fixes.css")
    css_dest = os.path.join(assets_path, "prototype-fixes.css")
    shutil.copy(css_source, css_dest)

    app = dash.Dash(__name__, assets_folder=assets_path)

    # Add debug endpoint to receive dimension data
    @app.server.route("/debug-dimensions", methods=["POST"])
    def debug_dimensions():
        try:
            from flask import request

            data = request.get_json()

            print("\n" + "=" * 80)
            print("🔍 DIMENSION DEBUG DATA FROM BROWSER:")
            print("=" * 80)

            # Check if all elements are roughly the same size
            heights = []
            for name, elem_data in data.items():
                if elem_data != "NOT_FOUND":
                    heights.append(elem_data["height"])
                    print(
                        f"{name.upper():>20}: {elem_data['width']:>3}x{elem_data['height']:>3} | "
                        f"display:{elem_data['computedDisplay']:>5} | "
                        f"flex:{elem_data['computedFlex']:>8} | "
                        f"grow:{elem_data['computedFlexGrow']:>1} | "
                        f"pos:{elem_data['computedPosition']:>8}"
                    )
                else:
                    print(f"{name.upper():>20}: NOT FOUND")

            # Analyze height distribution
            if heights:
                min_height = min(heights)
                max_height = max(heights)
                height_range = max_height - min_height

                print("\n" + "-" * 40)
                print("📊 HEIGHT ANALYSIS:")
                print(f"   Min Height: {min_height}px")
                print(f"   Max Height: {max_height}px")
                print(f"   Range: {height_range}px")

                if height_range < 20:
                    print("   ✅ GOOD: All elements are roughly the same height!")
                elif height_range < 100:
                    print("   ⚠️  MODERATE: Some height differences, but manageable")
                else:
                    print("   ❌ BAD: Significant height differences - vertical growing issue!")

            print("=" * 80 + "\n")

            return {"status": "ok"}
        except Exception as e:
            print(f"Error in debug endpoint: {e}")
            return {"status": "error"}

    # Generate UUID for the test component
    test_uuid = generate_unique_index()

    print("=== Card Component Vertical Growing Test ===")
    print(f"Test Component UUID: {test_uuid}")

    # Create the problematic card component
    test_component = create_problematic_card_component(test_uuid)

    # Add Bootstrap for card styling and debugging JavaScript
    app.index_string = """
    <!DOCTYPE html>
    <html>
        <head>
            {%metas%}
            <title>{%title%}</title>
            {%favicon%}
            {%css%}
            <style>
            /* Import Bootstrap for card styling */
            @import url('https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css');
            
            /* Visual debugging - add colored borders to identify elements */
            .react-grid-item.react-draggable.cssTransforms.react-resizable {
                border: 3px solid red !important;
            }
            
            div[id^="box-"] {
                border: 3px solid blue !important;
            }
            
            .responsive-wrapper {
                border: 3px solid green !important;
            }
            
            .responsive-content {
                border: 3px solid orange !important;
            }
            
            .card[id*="card-component"] {
                border: 3px solid purple !important;
            }
            
            .card-body {
                border: 3px solid yellow !important;
            }
            
            .mantine-Card-root {
                border: 3px solid cyan !important;
            }
            
            /* CRITICAL INLINE FIX: Force box element to behave as flex child */
            .react-grid-item.react-draggable.cssTransforms.react-resizable > div[id^="box-"] {
                height: 100% !important;
                flex: 1 1 0% !important;
                flex-grow: 1 !important;
                flex-shrink: 1 !important;
                flex-basis: 0% !important;
                display: flex !important;
                flex-direction: column !important;
                min-height: 0 !important;
                max-height: 100% !important;
                overflow: hidden !important;
                background-color: rgba(0, 255, 0, 0.1) !important; /* Green tint to confirm CSS is applied */
            }
            
            /* Also ensure parent is flex container and can contain absolute children */
            .react-grid-item.react-draggable.cssTransforms.react-resizable {
                position: relative !important; /* Required for absolute positioning of child */
                background-color: rgba(255, 0, 0, 0.1) !important; /* Red tint to confirm CSS is applied */
                overflow: hidden !important; /* Contain absolute children */
            }
            
            /* CRITICAL: Target the unnamed DIV that DashGridLayout creates (Child 0) */
            .react-grid-item.react-draggable.cssTransforms.react-resizable > div:first-child {
                position: absolute !important;
                top: 0 !important;
                left: 0 !important;
                right: 0 !important;
                bottom: 0 !important;
                width: 100% !important;
                height: 100% !important;
                box-sizing: border-box !important;
                display: flex !important;
                flex-direction: column !important;
                background-color: rgba(255, 165, 0, 0.4) !important; /* Orange background between red and blue */
            }
            
            /* CRITICAL: Force responsive-wrapper to use flex instead of block */
            .responsive-wrapper {
                display: flex !important;
                flex-direction: column !important;
                flex: 1 !important;
                flex-grow: 1 !important;
                background-color: rgba(255, 255, 0, 0.2) !important; /* Confirm CSS applied */
            }
            
            /* CRITICAL: Force responsive-content to grow fully */
            .responsive-content {
                flex: 1 !important;
                flex-grow: 1 !important;
                background-color: rgba(255, 165, 0, 0.2) !important; /* Orange tint to confirm */
            }
            
            /* CRITICAL: Fix all intermediate wrapper divs in responsive-content */
            .responsive-content > div {
                height: 100% !important;
                flex: 1 !important;
                display: flex !important;
                flex-direction: column !important;
            }
            
            /* CRITICAL: Target nested wrapper divs (wrapper_div_1, wrapper_div_2, wrapper_div_3) */
            .responsive-content div[style*=""] {
                height: 100% !important;
                flex: 1 !important;
                display: flex !important;
                flex-direction: column !important;
            }
            
            /* NUCLEAR: Target all divs inside responsive-content */
            .responsive-content div {
                min-height: 0 !important;
                flex: 1 !important;
            }
            
            /* NUCLEAR: Force card-component to absolute position within responsive-content */
            .responsive-content .card[id*="card-component"] {
                position: absolute !important;
                top: 0 !important;
                left: 0 !important;
                right: 0 !important;
                bottom: 0 !important;
                width: 100% !important;
                height: 100% !important;
                background-color: rgba(128, 0, 128, 0.3) !important; /* Purple tint */
                box-sizing: border-box !important;
            }
            
            /* Ensure responsive-content is relative for absolute child */
            .responsive-content {
                position: relative !important;
            }
            
            .card-body {
                height: 100% !important;
                flex: 1 !important;
                min-height: 0 !important;
                background-color: rgba(255, 255, 0, 0.2) !important; /* Yellow tint */
            }
            
            .mantine-Card-root {
                height: 100% !important;
                flex: 1 !important;
                min-height: 0 !important;
                background-color: rgba(0, 255, 255, 0.2) !important; /* Cyan tint */
            }
            
            /* NUCLEAR OPTION: Make blue element absolutely positioned to match red exactly */
            .react-grid-item.react-draggable.cssTransforms.react-resizable > div[id^="box-"] {
                position: absolute !important;
                inset: 0 !important; /* Fill entire container */
                display: flex !important;
                flex-direction: column !important;
                background-color: rgba(0, 255, 0, 0.1) !important; /* Green tint to confirm CSS is applied */
                box-sizing: border-box !important;
                margin: 0 !important;
                padding: 0 !important;
            }
            
            /* Make resize handles more visible for debugging and force them to overlay */
            .react-resizable-handle {
                background: rgba(255, 0, 0, 0.3) !important; /* Red tint to see handle boundaries */
                border: 1px solid red !important;
                z-index: 1000 !important; /* Force handles on top */
            }
            
            /* Ensure resize handles don't interfere with blue box content */
            .react-grid-item.react-draggable.cssTransforms.react-resizable {
                overflow: visible !important; /* Allow handles to extend outside */
            }
            </style>
            <script>
            // Dimension logging function
            function logElementDimensions() {
                console.log("=== DIMENSION LOGGING ===");
                
                // Get all relevant elements
                const gridItem = document.querySelector('.react-grid-item.react-draggable.cssTransforms.react-resizable');
                const boxElement = document.querySelector('div[id^="box-"]');
                const responsiveWrapper = document.querySelector('.responsive-wrapper');
                const responsiveContent = document.querySelector('.responsive-content');
                const cardComponent = document.querySelector('.card[id*="card-component"]');
                const cardBody = document.querySelector('.card-body');
                const mantineCard = document.querySelector('.mantine-Card-root');
                
                // CRITICAL DEBUG: Find what's between react-grid-item and box element
                if (gridItem && boxElement) {
                    console.log("=== DOM STRUCTURE ANALYSIS ===");
                    console.log("gridItem classes:", gridItem.className);
                    console.log("gridItem children count:", gridItem.children.length);
                    for (let i = 0; i < gridItem.children.length; i++) {
                        const child = gridItem.children[i];
                        console.log(`Child ${i}:`, {
                            tagName: child.tagName,
                            className: child.className,
                            id: child.id,
                            width: child.getBoundingClientRect().width,
                            height: child.getBoundingClientRect().height,
                            styles: {
                                position: window.getComputedStyle(child).position,
                                display: window.getComputedStyle(child).display,
                                flex: window.getComputedStyle(child).flex,
                            }
                        });
                    }
                }
                
                const elements = [
                    {name: 'react-grid-item', elem: gridItem},
                    {name: 'box-element', elem: boxElement},
                    {name: 'responsive-wrapper', elem: responsiveWrapper},
                    {name: 'responsive-content', elem: responsiveContent},
                    {name: 'card-component', elem: cardComponent},
                    {name: 'card-body', elem: cardBody},
                    {name: 'mantine-card', elem: mantineCard}
                ];
                
                // Create a comprehensive report string for easy copying
                let report = "ELEMENT DIMENSIONS REPORT:\\n\\n";
                
                elements.forEach(({name, elem}) => {
                    if (elem) {
                        const rect = elem.getBoundingClientRect();
                        const computed = window.getComputedStyle(elem);
                        
                        report += `${name.toUpperCase()}:\\n`;
                        report += `  Size: ${Math.round(rect.width)}x${Math.round(rect.height)}\\n`;
                        report += `  Position: x:${Math.round(rect.x)}, y:${Math.round(rect.y)}\\n`;
                        report += `  Computed Height: ${computed.height}\\n`;
                        report += `  Computed Display: ${computed.display}\\n`;
                        report += `  Computed Flex: ${computed.flex}\\n`;
                        report += `  Computed FlexGrow: ${computed.flexGrow}\\n`;
                        report += `  Computed FlexDirection: ${computed.flexDirection}\\n`;
                        report += `  Min/Max Height: ${computed.minHeight} / ${computed.maxHeight}\\n`;
                        report += `\\n`;
                        
                        // Also log individual objects for detailed inspection
                        console.log(`${name}:`, {
                            width: rect.width,
                            height: rect.height,
                            computedHeight: computed.height,
                            computedMinHeight: computed.minHeight,
                            computedMaxHeight: computed.maxHeight,
                            computedFlex: computed.flex,
                            computedFlexGrow: computed.flexGrow,
                            computedFlexShrink: computed.flexShrink,
                            computedFlexBasis: computed.flexBasis,
                            computedDisplay: computed.display,
                            computedFlexDirection: computed.flexDirection,
                            position: `x:${Math.round(rect.x)}, y:${Math.round(rect.y)}`
                        });
                    } else {
                        report += `${name.toUpperCase()}: NOT FOUND\\n\\n`;
                        console.log(`${name}: NOT FOUND`);
                    }
                });
                
                // Log the complete report as a single string for easy copying
                console.log("\\n" + "=".repeat(60));
                console.log("COPY-PASTE FRIENDLY REPORT:");
                console.log("=".repeat(60));
                console.log(report);
                console.log("=".repeat(60));
                
                console.log("=== END DIMENSION LOGGING ===");
            }
            
            // Function to send dimensions to Python terminal
            function sendDimensionsToTerminal() {
                const gridItem = document.querySelector('.react-grid-item.react-draggable.cssTransforms.react-resizable');
                const boxElement = document.querySelector('div[id^="box-"]');
                const responsiveWrapper = document.querySelector('.responsive-wrapper');
                const responsiveContent = document.querySelector('.responsive-content');
                const cardComponent = document.querySelector('.card[id*="card-component"]');
                const cardBody = document.querySelector('.card-body');
                const mantineCard = document.querySelector('.mantine-Card-root');
                
                const elements = [
                    {name: 'react-grid-item', elem: gridItem},
                    {name: 'box-element', elem: boxElement},
                    {name: 'responsive-wrapper', elem: responsiveWrapper},
                    {name: 'responsive-content', elem: responsiveContent},
                    {name: 'card-component', elem: cardComponent},
                    {name: 'card-body', elem: cardBody},
                    {name: 'mantine-card', elem: mantineCard}
                ];
                
                const dimensionData = {};
                elements.forEach(({name, elem}) => {
                    if (elem) {
                        const rect = elem.getBoundingClientRect();
                        const computed = window.getComputedStyle(elem);
                        dimensionData[name] = {
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                            computedDisplay: computed.display,
                            computedFlex: computed.flex,
                            computedFlexGrow: computed.flexGrow,
                            computedPosition: computed.position,
                        };
                    } else {
                        dimensionData[name] = 'NOT_FOUND';
                    }
                });
                
                // Send to Python app endpoint
                fetch('/debug-dimensions', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(dimensionData)
                }).catch(e => console.log('Could not send to terminal:', e));
                
                // Also call the regular logging
                logElementDimensions();
            }
            
            // Log dimensions after page loads and on resize
            window.addEventListener('load', () => {
                setTimeout(sendDimensionsToTerminal, 1000);
                // Send every 2 seconds for debugging
                setInterval(sendDimensionsToTerminal, 2000);
            });
            
            // Also log on resize to see what changes
            window.addEventListener('resize', sendDimensionsToTerminal);
            
            // Add a manual trigger button
            function addLogButton() {
                const button = document.createElement('button');
                button.innerText = '🔍 Log Dimensions';
                button.style.position = 'fixed';
                button.style.top = '10px';
                button.style.right = '10px';
                button.style.zIndex = '9999';
                button.style.padding = '10px';
                button.style.backgroundColor = '#007bff';
                button.style.color = 'white';
                button.style.border = 'none';
                button.style.borderRadius = '5px';
                button.style.cursor = 'pointer';
                button.onclick = sendDimensionsToTerminal;
                document.body.appendChild(button);
            }
            
            window.addEventListener('load', addLogButton);
            </script>
        </head>
        <body>
            {%app_entry%}
            <footer>
                {%config%}
                {%scripts%}
                {%renderer%}
            </footer>
        </body>
    </html>
    """

    # Create the layout
    app.layout = dmc.MantineProvider(
        [
            # html.H1("🧪 Card Component Vertical Growing Test (Version 5)"),
            # html.Div(
            #     [
            #         html.H3("Testing Problematic Card Component Structure"),
            #         html.P("🎯 This replicates the exact DOM structure from depictio that's not growing vertically"),
            #         html.P("🔧 Bootstrap Card → Card Body → Mantine Card structure"),
            #         html.P("📊 Component should grow vertically when resized"),
            #         html.P(f"🆔 Test UUID: {test_uuid[:8]}..."),
            #     ],
            #     style={"background": "#fff3cd", "padding": "15px", "margin": "10px 0", "border": "1px solid #ffeaa7", "borderRadius": "8px"},
            # ),
            # Control panel
            html.Div(
                [
                    html.H4("🎛️ Layout Controls"),
                    dmc.Group(
                        [
                            dmc.Button(
                                "🔄 Reset Layout",
                                id="reset-layout-btn",
                                color="blue",
                                size="sm",
                            ),
                            dmc.Switch(
                                id="edit-mode-toggle",
                                label="Edit Mode",
                                checked=True,
                                color="green",
                                size="md",
                            ),
                        ],
                        gap="md",
                    ),
                    html.P(
                        "💡 Try resizing the component vertically to test the growing behavior!",
                        style={"marginTop": "10px", "fontStyle": "italic"},
                    ),
                ],
                style={
                    "background": "#f0fff0",
                    "padding": "15px",
                    "margin": "10px 0",
                    "border": "1px solid #ddd",
                    "borderRadius": "8px",
                },
            ),
            html.Hr(),
            # Dynamic Grid Layout with the problematic card component
            dgl.DashGridLayout(
                id="card-test-grid-layout",
                items=[test_component],
                rowHeight=10,  # Same as depictio
                cols={"lg": 96, "md": 10, "sm": 6, "xs": 4, "xxs": 2},
                style={
                    "minHeight": "600px",
                    "height": "auto",
                },
                showRemoveButton=False,
                showResizeHandles=True,
                className="draggable-grid-container",
                itemLayout=[
                    {
                        "i": f"box-{test_uuid}",
                        "x": 0,
                        "y": 0,
                        "w": 20,  # Medium width
                        "h": 20,  # Smaller height (20*10px = 200px) to limit red box size
                    },
                ],
            ),
        ]
    )

    # Callback to handle layout reset
    @app.callback(
        Output("card-test-grid-layout", "itemLayout"),
        Input("reset-layout-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def reset_layout(n_clicks):
        if n_clicks:
            return [{"i": f"box-{test_uuid}", "x": 0, "y": 0, "w": 20, "h": 25}]
        return dash.no_update

    # Callback to toggle edit mode
    @app.callback(
        Output("card-test-grid-layout", "className"),
        Input("edit-mode-toggle", "checked"),
    )
    def toggle_edit_mode(edit_enabled):
        if edit_enabled:
            return "draggable-grid-container"
        else:
            return "draggable-grid-container drag-handles-hidden"

    return app


if __name__ == "__main__":
    app = create_card_vertical_growing_app()
    print("🚀 Starting Card Component Vertical Growing Test (Version 5)...")
    print("🎯 Testing the exact DOM structure that's problematic in depictio")
    print("🔧 Component: Bootstrap Card → Card Body → Mantine Card")
    app.run(debug=True, port=8087)
