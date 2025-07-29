#!/usr/bin/env python3
"""
Simple test without DraggableWrapper to isolate the positioning issue
"""

import sys
import uuid
import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html

# Add the depictio package to the path
sys.path.insert(0, "/Users/tweber/Gits/workspaces/depictio-workspace/depictio")


def create_simple_test():
    app = dash.Dash(__name__)

    test_uuid = str(uuid.uuid4())

    # Create the problematic card structure directly
    mantine_card_content = dmc.Card(
        [
            dmc.Text("Median of flipper_length_mm", size="sm", c="dimmed"),
            dmc.Text("197.0", size="xl", fw=700, c="dark"),
        ],
        withBorder=True,
        style={
            "height": "100%",
            "minHeight": "120px",
            "backgroundColor": "var(--app-surface-color, #ffffff)",
            "borderColor": "var(--app-border-color, #ddd)",
            "padding": "var(--mantine-spacing-md)",
        },
        className="m_e615b15f mantine-Card-root m_1b7284a3 mantine-Paper-root",
    )

    card_body = html.Div(
        mantine_card_content,
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

    bootstrap_card = html.Div(
        card_body,
        className="card",
        style={
            "backgroundColor": "transparent",
            "width": "100%",
            "height": "100%",
            "padding": "0px",
            "margin": "0px",
            "boxShadow": "none",
            "border": "none",
            "borderRadius": "4px",
            "display": "flex",
            "flexDirection": "column",
            "flex": "1 1 0%",
        },
    )

    # Create the blue box directly
    blue_box = html.Div(
        bootstrap_card,
        id=f"box-{test_uuid}",
        style={
            # FORCE EXACT MATCH WITH RED CONTAINER
            "position": "absolute",
            "top": "0",
            "left": "0",
            "right": "0",
            "bottom": "0",
            "width": "100%",
            "height": "100%",
            "display": "flex",
            "flexDirection": "column",
            "backgroundColor": "rgba(0, 255, 0, 0.3)",  # Green tint
            "border": "3px solid blue",
            "boxSizing": "border-box",  # CRITICAL: Include border in size calculation
        },
    )

    # Create the red container
    red_container = html.Div(
        blue_box,
        className="react-grid-item react-draggable cssTransforms react-resizable",
        style={
            "position": "relative",
            "width": "400px",
            "height": "300px",
            "backgroundColor": "rgba(255, 0, 0, 0.1)",  # Red tint
            "border": "3px solid red",
            "margin": "50px",
            "boxSizing": "border-box",  # Include border in size calculation
        },
    )

    app.index_string = """
    <!DOCTYPE html>
    <html>
        <head>
            {%metas%}
            <title>{%title%}</title>
            {%favicon%}
            {%css%}
            <style>
            @import url('https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css');
            </style>
            <script>
            function logElementDimensions() {
                console.log("=== SIMPLE TEST DIMENSIONS ===");
                
                const redContainer = document.querySelector('.react-grid-item');
                const blueBox = document.querySelector('div[id^="box-"]');
                
                if (redContainer) {
                    const rect = redContainer.getBoundingClientRect();
                    console.log('RED CONTAINER:', {
                        width: rect.width,
                        height: rect.height,
                        position: `x:${Math.round(rect.x)}, y:${Math.round(rect.y)}`
                    });
                }
                
                if (blueBox) {
                    const rect = blueBox.getBoundingClientRect();
                    console.log('BLUE BOX:', {
                        width: rect.width,
                        height: rect.height,
                        position: `x:${Math.round(rect.x)}, y:${Math.round(rect.y)}`
                    });
                }
                
                console.log("=== END SIMPLE TEST ===");
            }
            
            window.addEventListener('load', () => {
                setTimeout(logElementDimensions, 500);
            });
            
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
                button.onclick = logElementDimensions;
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

    app.layout = dmc.MantineProvider(
        [
            html.H1("Simple Positioning Test"),
            html.P("Red container should be 400x300px, blue box should match exactly"),
            red_container,
        ]
    )

    return app


if __name__ == "__main__":
    app = create_simple_test()
    print("🚀 Starting Simple Test...")
    print("Red container: 400x300px with red border")
    print("Blue box: Should match red exactly with green tint and blue border")
    app.run(debug=True, port=8088)
