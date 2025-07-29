"""
Enhanced Plotly Code Prototype App
Leverages depictio figure component logic with secure code execution
"""

import sys
from typing import Dict

import dash
import dash_mantine_components as dmc
import numpy as np
import pandas as pd
from dash import Input, Output, State, callback, dash_table, dcc

# Try to import dash-ace for syntax highlighting
try:
    import dash_ace

    ACE_AVAILABLE = True
except ImportError:
    ACE_AVAILABLE = False
    print("dash-ace not available, using enhanced textarea instead")

# Add depictio to path
sys.path.append("/Users/tweber/Gits/workspaces/depictio-workspace/depictio")

# Import our secure executor (from same directory)
from secure_code_executor import SecureCodeExecutor

# Try to import depictio utilities (optional) - currently not used but kept for future integration
try:
    from depictio.dash.modules.figure_component.definitions import (
        get_available_visualizations,  # noqa: F401
    )
    from depictio.dash.modules.figure_component.utils import render_figure  # noqa: F401

    DEPICTIO_AVAILABLE = True
except ImportError:
    DEPICTIO_AVAILABLE = False
    print("Warning: depictio modules not available, running in standalone mode")


def create_sample_datasets() -> Dict[str, pd.DataFrame]:
    """Create multiple sample datasets for testing"""
    datasets = {}

    # Simple scatter data
    datasets["scatter"] = pd.DataFrame(
        {
            "x": list(range(1, 21)),
            "y": [2, 5, 3, 8, 7, 4, 9, 6, 1, 10, 12, 15, 11, 18, 16, 13, 19, 14, 17, 20],
            "category": ["A", "B"] * 10,
            "size": [
                10,
                20,
                15,
                25,
                30,
                12,
                18,
                22,
                14,
                28,
                32,
                35,
                25,
                40,
                38,
                28,
                42,
                30,
                36,
                45,
            ],
            "color_val": list(range(1, 21)),
        }
    )

    # Time series data
    dates = pd.date_range("2023-01-01", periods=100, freq="D")
    datasets["timeseries"] = pd.DataFrame(
        {
            "date": dates,
            "value": np.random.randn(100).cumsum() + 100,
            "category": np.random.choice(["Product A", "Product B", "Product C"], 100),
            "sales": np.random.randint(50, 200, 100),
        }
    )

    # Bar chart data
    datasets["bar"] = pd.DataFrame(
        {
            "category": ["Electronics", "Clothing", "Books", "Home", "Sports", "Toys"],
            "sales": [12000, 8500, 6200, 9800, 7300, 5600],
            "profit": [2400, 1700, 1240, 1960, 1460, 1120],
            "region": ["North", "South", "East", "West", "North", "South"],
        }
    )

    # Histogram data
    datasets["histogram"] = pd.DataFrame(
        {
            "values": np.random.normal(100, 15, 1000),
            "group": np.random.choice(["Group 1", "Group 2", "Group 3"], 1000),
        }
    )

    return datasets


def create_code_examples() -> Dict[str, str]:
    """Create example code snippets"""
    examples = {
        "Scatter Plot": """fig = px.scatter(df, x='x', y='y', 
                 color='category', 
                 size='size',
                 title='Interactive Scatter Plot',
                 hover_data=['color_val'])""",
        "Line Chart": """fig = px.line(df, x='date', y='value', 
              color='category',
              title='Time Series Line Chart')""",
        "Bar Chart": """fig = px.bar(df, x='category', y='sales', 
             color='region',
             title='Sales by Category and Region')""",
        "Histogram": """fig = px.histogram(df, x='values', 
                   color='group',
                   title='Distribution by Group',
                   nbins=30)""",
        "Box Plot": """fig = px.box(df, x='category', y='sales',
             title='Sales Distribution by Category')""",
        "Custom Styling": """fig = px.scatter(df, x='x', y='y', color='category')
fig.update_layout(
    title='Custom Styled Plot',
    xaxis_title='X Axis',
    yaxis_title='Y Axis',
    font=dict(size=14),
    plot_bgcolor='rgba(0,0,0,0)',
    paper_bgcolor='rgba(0,0,0,0)'
)
fig.update_traces(marker=dict(size=12, opacity=0.7))""",
        "Multiple Traces": """import plotly.graph_objects as go

fig = go.Figure()
fig.add_trace(go.Scatter(x=df['x'], y=df['y'], 
                        mode='markers', name='Data Points'))
fig.add_trace(go.Scatter(x=df['x'], y=df['y']*1.2, 
                        mode='lines', name='Trend Line'))
fig.update_layout(title='Multiple Traces Example')""",
        "Pandas Operations": """# Data processing with pandas
df_grouped = df.groupby('category').agg({
    'sales': 'sum',
    'profit': 'mean'
}).reset_index()

fig = px.bar(df_grouped, x='category', y='sales',
            title='Aggregated Sales by Category')""",
    }
    return examples


def create_app() -> dash.Dash:
    """Create the enhanced Dash application"""
    app = dash.Dash(__name__)

    # Create sample datasets and convert to JSON-serializable format
    datasets_df = create_sample_datasets()
    datasets = {key: df.to_dict("records") for key, df in datasets_df.items()}
    code_examples = create_code_examples()

    app.layout = dmc.MantineProvider(
        theme={"colorScheme": "light"},
        children=[
            dmc.Container(
                size="xl",
                children=[
                    # Header
                    dmc.Paper(
                        [
                            dmc.Title(
                                "🚀 Plotly Code Prototype", order=1, style={"textAlign": "center"}
                            ),
                            dmc.Text(
                                "Secure Python/Plotly code execution with real-time visualization",
                                style={"textAlign": "center"},
                                c="dimmed",
                            ),
                            dmc.Space(h=10),
                            dmc.Group(
                                [
                                    dmc.Badge("Python", color="blue", variant="filled"),
                                    dmc.Badge("Plotly", color="green", variant="filled"),
                                    dmc.Badge("Pandas", color="orange", variant="filled"),
                                    dmc.Badge("Secure", color="red", variant="filled"),
                                ],
                                justify="center",
                            ),
                        ],
                        p="md",
                        radius="md",
                        withBorder=True,
                        mb="md",
                    ),
                    # Controls Row
                    dmc.Group(
                        [
                            dmc.Stack(
                                [
                                    dmc.Select(
                                        id="dataset-selector",
                                        label="Select Dataset",
                                        value="scatter",
                                        data=[
                                            {"label": "Scatter Data", "value": "scatter"},
                                            {"label": "Time Series", "value": "timeseries"},
                                            {"label": "Bar Chart Data", "value": "bar"},
                                            {"label": "Histogram Data", "value": "histogram"},
                                        ],
                                        style={"marginBottom": "10px", "width": "300px"},
                                    ),
                                    dmc.Select(
                                        id="example-selector",
                                        label="Code Examples",
                                        placeholder="Select an example...",
                                        data=[
                                            {"label": k, "value": k} for k in code_examples.keys()
                                        ],
                                        style={"marginBottom": "10px", "width": "300px"},
                                    ),
                                ],
                                gap="xs",
                            ),
                            dmc.Stack(
                                [
                                    dmc.Button(
                                        "Execute Code",
                                        id="execute-btn",
                                        color="blue",
                                        leftSection="▶️",
                                        style={"marginBottom": "10px", "width": "200px"},
                                    ),
                                    dmc.Button(
                                        "Clear Code",
                                        id="clear-btn",
                                        color="gray",
                                        variant="outline",
                                        leftSection="🗑️",
                                        style={"width": "200px"},
                                    ),
                                ],
                                gap="xs",
                            ),
                        ],
                        justify="space-between",
                        grow=True,
                    ),
                    dmc.Space(h=20),
                    # Main Content - Full Width Layout
                    dmc.Stack(
                        [
                            # Top Row - Code Editor (Full Width)
                            dmc.Card(
                                [
                                    dmc.CardSection(
                                        [
                                            dmc.Group(
                                                [
                                                    dmc.Title("💻 Python Code Editor", order=3),
                                                    dmc.Group(
                                                        [
                                                            dmc.Text("Status:", size="sm", fw=500),
                                                            dmc.Text(
                                                                "Ready to execute code",
                                                                id="status-text",
                                                                size="sm",
                                                                c="green",
                                                            ),
                                                        ],
                                                        gap="xs",
                                                    ),
                                                ],
                                                justify="space-between",
                                            ),
                                            dmc.Space(h=10),
                                            # Enhanced Code Editor
                                            dmc.Paper(
                                                [
                                                    # Code editor header bar
                                                    dmc.Group(
                                                        [
                                                            dmc.Group(
                                                                [
                                                                    dmc.Box(
                                                                        style={
                                                                            "width": "12px",
                                                                            "height": "12px",
                                                                            "borderRadius": "50%",
                                                                            "backgroundColor": "#ff5f57",
                                                                        }
                                                                    ),
                                                                    dmc.Box(
                                                                        style={
                                                                            "width": "12px",
                                                                            "height": "12px",
                                                                            "borderRadius": "50%",
                                                                            "backgroundColor": "#ffbd2e",
                                                                        }
                                                                    ),
                                                                    dmc.Box(
                                                                        style={
                                                                            "width": "12px",
                                                                            "height": "12px",
                                                                            "borderRadius": "50%",
                                                                            "backgroundColor": "#28ca42",
                                                                        }
                                                                    ),
                                                                ],
                                                                gap="xs",
                                                            ),
                                                            dmc.Text(
                                                                "main.py",
                                                                size="sm",
                                                                c="dimmed",
                                                                style={"fontFamily": "monospace"},
                                                            ),
                                                            dmc.Group(
                                                                [
                                                                    dmc.Text(
                                                                        "Python",
                                                                        size="xs",
                                                                        c="dimmed",
                                                                    ),
                                                                    dmc.Text(
                                                                        "UTF-8",
                                                                        size="xs",
                                                                        c="dimmed",
                                                                    ),
                                                                ],
                                                                gap="md",
                                                            ),
                                                        ],
                                                        justify="space-between",
                                                        p="sm",
                                                        style={
                                                            "backgroundColor": "var(--mantine-color-gray-1, #f8f9fa)",
                                                            "borderBottom": "1px solid var(--mantine-color-gray-3, #dee2e6)",
                                                        },
                                                    ),
                                                    # Code input area with syntax highlighting
                                                    dmc.Box(
                                                        [
                                                            dash_ace.DashAceEditor(
                                                                id="code-input",
                                                                value='fig = px.scatter(df, x="x", y="y", color="category", size="size", title="Sample Scatter Plot")',
                                                                theme="github",
                                                                mode="python",
                                                                fontSize=15,
                                                                showGutter=True,
                                                                showPrintMargin=False,
                                                                highlightActiveLine=True,
                                                                setOptions={
                                                                    "enableBasicAutocompletion": True,
                                                                    "enableLiveAutocompletion": True,
                                                                    "enableSnippets": True,
                                                                    "tabSize": 4,
                                                                    "useSoftTabs": True,
                                                                    "wrap": False,
                                                                    "fontFamily": "Fira Code, JetBrains Mono, Monaco, Consolas, Courier New, monospace",
                                                                },
                                                                style={
                                                                    "width": "100%",
                                                                    "height": "100%",
                                                                    "borderRadius": "0 0 8px 8px",
                                                                },
                                                                placeholder="# Enter your Python/Plotly code here...\n# Available: df (DataFrame), px (plotly.express), go (plotly.graph_objects), pd (pandas), np (numpy)\n# Example:\nfig = px.scatter(df, x='x', y='y', color='category')",
                                                            ),
                                                            # Resize handle
                                                            dmc.Box(
                                                                style={
                                                                    "width": "100%",
                                                                    "height": "12px",
                                                                    "backgroundColor": "#e9ecef",
                                                                    "cursor": "ns-resize",
                                                                    "borderRadius": "0 0 8px 8px",
                                                                    "display": "flex",
                                                                    "alignItems": "center",
                                                                    "justifyContent": "center",
                                                                    "opacity": 0.7,
                                                                    "transition": "opacity 0.2s, backgroundColor 0.2s",
                                                                    "userSelect": "none",
                                                                },
                                                                children=[
                                                                    dmc.Group(
                                                                        [
                                                                            dmc.Box(
                                                                                style={
                                                                                    "width": "4px",
                                                                                    "height": "4px",
                                                                                    "backgroundColor": "#adb5bd",
                                                                                    "borderRadius": "50%",
                                                                                }
                                                                            ),
                                                                            dmc.Box(
                                                                                style={
                                                                                    "width": "4px",
                                                                                    "height": "4px",
                                                                                    "backgroundColor": "#adb5bd",
                                                                                    "borderRadius": "50%",
                                                                                }
                                                                            ),
                                                                            dmc.Box(
                                                                                style={
                                                                                    "width": "4px",
                                                                                    "height": "4px",
                                                                                    "backgroundColor": "#adb5bd",
                                                                                    "borderRadius": "50%",
                                                                                }
                                                                            ),
                                                                        ],
                                                                        gap="xs",
                                                                    ),
                                                                ],
                                                                id="resize-handle",
                                                            ),
                                                        ],
                                                        style={
                                                            "width": "100%",
                                                            "minHeight": "30px",
                                                            "height": "50px",
                                                            "resize": "vertical",
                                                            "overflow": "hidden",
                                                            "borderRadius": "0 0 8px 8px",
                                                        },
                                                        id="editor-container",
                                                    )
                                                    if ACE_AVAILABLE
                                                    else dmc.Textarea(
                                                        id="code-input",
                                                        placeholder="# Enter your Python/Plotly code here...\n# Available: df (DataFrame), px (plotly.express), go (plotly.graph_objects), pd (pandas), np (numpy)\n# Example:\nfig = px.scatter(df, x='x', y='y', color='category', size='size', title='Interactive Scatter Plot')",
                                                        value="fig = px.scatter(df, x='x', y='y', color='category', size='size', title='Sample Scatter Plot')",
                                                        minRows=20,
                                                        autosize=True,
                                                        style={
                                                            "fontFamily": "'Fira Code', 'JetBrains Mono', 'Monaco', 'Consolas', 'Courier New', monospace",
                                                            "fontSize": "15px",
                                                            "lineHeight": "1.6",
                                                            "backgroundColor": "#2d3748",
                                                            "color": "#e2e8f0",
                                                            "border": "none",
                                                            "borderRadius": "0 0 8px 8px",
                                                            "padding": "20px",
                                                            "resize": "vertical",
                                                            "minHeight": "200px",
                                                            "tabSize": "4",
                                                            "outline": "none",
                                                            "width": "100%",
                                                        },
                                                    ),
                                                ],
                                                radius="md",
                                                withBorder=True,
                                                style={
                                                    "backgroundColor": "#2d3748",
                                                    "overflow": "hidden",
                                                },
                                            ),
                                        ],
                                        p="lg",
                                    ),
                                ],
                                mb="xl",
                            ),
                            # Bottom Row - Visualization (Full Width)
                            dmc.Card(
                                [
                                    dmc.CardSection(
                                        [
                                            dmc.Title(
                                                "📈 Generated Visualization", order=3, mb="md"
                                            ),
                                            dcc.Graph(
                                                id="output-graph",
                                                style={"height": "700px", "width": "100%"},
                                                config={
                                                    "displayModeBar": True,
                                                    "displaylogo": False,
                                                    "modeBarButtonsToRemove": ["pan2d", "lasso2d"],
                                                },
                                            ),
                                        ],
                                        p="lg",
                                    ),
                                ]
                            ),
                            # Collapsible Dataset Info
                            dmc.Accordion(
                                [
                                    dmc.AccordionItem(
                                        [
                                            dmc.AccordionControl(
                                                [
                                                    dmc.Group(
                                                        [
                                                            dmc.Title(
                                                                "📊 Dataset Information", order=4
                                                            ),
                                                            dmc.Text(
                                                                id="dataset-info",
                                                                size="sm",
                                                                c="dimmed",
                                                            ),
                                                        ],
                                                        justify="space-between",
                                                    )
                                                ]
                                            ),
                                            dmc.AccordionPanel(
                                                [
                                                    dash_table.DataTable(
                                                        id="dataset-preview",
                                                        columns=[],
                                                        data=[],
                                                        style_table={
                                                            "overflowX": "auto",
                                                            "maxHeight": "300px",
                                                        },
                                                        style_cell={
                                                            "textAlign": "left",
                                                            "fontSize": "12px",
                                                            "padding": "8px",
                                                        },
                                                        style_header={
                                                            "backgroundColor": "rgb(230, 230, 230)",
                                                            "fontWeight": "bold",
                                                        },
                                                        page_size=10,
                                                    )
                                                ]
                                            ),
                                        ],
                                        value="dataset-info",
                                    )
                                ],
                                value=None,
                            ),  # Start collapsed
                        ],
                        gap="xl",
                    ),
                    dmc.Space(h=20),
                    # Footer with Security Info
                    dmc.Paper(
                        [
                            dmc.Title("🔒 Security Features", order=4, mb="xs"),
                            dmc.Group(
                                [
                                    dmc.Text(
                                        "✅ Only safe Python/Plotly operations allowed", size="sm"
                                    ),
                                    dmc.Text("✅ No file system access", size="sm"),
                                    dmc.Text("✅ No network operations", size="sm"),
                                    dmc.Text("✅ No code injection vulnerabilities", size="sm"),
                                    dmc.Text("✅ Restricted builtin functions", size="sm"),
                                    dmc.Text("✅ AST-based code validation", size="sm"),
                                ],
                                justify="space-evenly",
                            ),
                        ],
                        p="md",
                        radius="md",
                        withBorder=True,
                        style={"backgroundColor": "#f8f9fa"},
                    ),
                    # Store components
                    dcc.Store(id="datasets-store", data=datasets),
                    dcc.Store(id="examples-store", data=code_examples),
                ],
            )
        ],
    )

    # Callback for dataset selection
    @callback(
        [
            Output("dataset-info", "children"),
            Output("dataset-preview", "columns"),
            Output("dataset-preview", "data"),
        ],
        Input("dataset-selector", "value"),
        State("datasets-store", "data"),
    )
    def update_dataset_info(selected_dataset, datasets):
        if selected_dataset not in datasets:
            return "No dataset selected", [], []

        # Convert back to DataFrame
        df = pd.DataFrame(datasets[selected_dataset])

        # Dataset info
        info = f"Shape: {df.shape[0]} rows × {df.shape[1]} columns\\n"
        info += f"Columns: {', '.join(df.columns)}"

        # Preview data
        columns = [{"name": col, "id": col} for col in df.columns]
        data = df.head(10).to_dict("records")

        return info, columns, data

    # Callback for example selection
    @callback(
        Output("code-input", "value"),
        Input("example-selector", "value"),
        State("examples-store", "data"),
        prevent_initial_call=True,
    )
    def load_example(selected_example, examples):
        if selected_example and selected_example in examples:
            return examples[selected_example]
        return dash.no_update

    # Callback for clear button
    @callback(
        Output("code-input", "value", allow_duplicate=True),
        Input("clear-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def clear_code(n_clicks):
        if n_clicks:
            return ""
        return dash.no_update

    # Main execution callback
    @callback(
        [
            Output("output-graph", "figure"),
            Output("status-text", "children"),
            Output("status-text", "c"),
        ],
        Input("execute-btn", "n_clicks"),
        [
            State("code-input", "value"),
            State("dataset-selector", "value"),
            State("datasets-store", "data"),
        ],
        prevent_initial_call=False,
    )
    def execute_code(n_clicks, code, selected_dataset, datasets):
        if code is None or code.strip() == "":
            return {}, "No code provided", "orange"

        # Get the selected dataset
        if selected_dataset not in datasets:
            return {}, "Invalid dataset selected", "red"

        df = pd.DataFrame(datasets[selected_dataset])

        # Create secure executor
        executor = SecureCodeExecutor(df)

        # Execute the code
        success, result, error_msg = executor.execute_code(code)

        if success:
            return result, "Code executed successfully!", "green"
        else:
            return {}, f"Error: {error_msg}", "red"

    return app


def main():
    """Main function to run the app"""
    app = create_app()

    print("🚀 Enhanced Plotly Code Prototype App Created!")
    print("=" * 50)
    print("Features:")
    print("- 🔒 Secure code execution (only Plotly/Pandas allowed)")
    print("- 📊 Multiple sample datasets")
    print("- 💡 Code examples library")
    print("- 🎨 Real-time plot generation")
    print("- 🛡️ Comprehensive security validation")
    print("- 📱 Modern responsive UI")
    print("=" * 50)
    print("To run: python plotly_prototype_app.py")
    print("Then visit: http://127.0.0.1:8050")

    # Don't auto-run as requested
    return app


if __name__ == "__main__":
    app = main()
    # Uncomment the line below to run the app
    # app.run_server(debug=True)
