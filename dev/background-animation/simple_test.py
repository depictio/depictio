"""
Simple test to debug the background animation
"""

import dash
from dash import dcc, html
import dash_mantine_components as dmc

# Initialize Dash app
app = dash.Dash(__name__)

# Simple test layout with visible triangles
app.layout = dmc.MantineProvider(
    html.Div(
        [
            # Simple test triangle to see if anything shows up
            html.Div(
                [
                    "Test Triangle",
                    html.Div(
                        style={
                            "position": "absolute",
                            "top": "100px",
                            "left": "100px",
                            "width": "50px",
                            "height": "50px",
                            "background": "red",
                            "clipPath": "polygon(50% 0%, 0% 100%, 100% 100%)",
                            "zIndex": 1,
                        }
                    ),
                    html.Div(
                        style={
                            "position": "absolute",
                            "top": "200px",
                            "left": "200px",
                            "width": "30px",
                            "height": "30px",
                            "background": "blue",
                            "clipPath": "polygon(50% 0%, 0% 100%, 100% 100%)",
                            "zIndex": 1,
                            "animation": "spin 2s linear infinite",
                        }
                    ),
                ],
                style={
                    "position": "relative",
                    "minHeight": "100vh",
                    "backgroundColor": "white",
                },
            ),
            # Add CSS for animation using a script tag
            html.Script("""
            const style = document.createElement('style');
            style.textContent = `
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `;
            document.head.appendChild(style);
        """),
        ]
    )
)

if __name__ == "__main__":
    app.run(debug=True, port=8052)
