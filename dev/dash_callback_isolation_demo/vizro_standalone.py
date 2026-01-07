"""
Standalone Vizro app for callback isolation demo.

Can be run standalone on port 8051 or imported and mounted via DispatcherMiddleware.
"""

import pandas as pd
import vizro.models as vm
import vizro.plotly.express as px
from dash import Dash, dcc
from vizro import Vizro
from vizro.managers import data_manager


class ScriptNameMiddleware:
    """
    WSGI middleware that sets SCRIPT_NAME for apps mounted via DispatcherMiddleware.
    This tells Dash where it's mounted so it generates correct asset URLs.
    """
    def __init__(self, app, script_name='/vizro'):
        self.app = app
        self.script_name = script_name

    def __call__(self, environ, start_response):
        # Set SCRIPT_NAME so Dash knows the mount prefix
        environ['SCRIPT_NAME'] = self.script_name
        # Adjust PATH_INFO to remove the prefix
        path_info = environ.get('PATH_INFO', '')
        if path_info.startswith(self.script_name):
            environ['PATH_INFO'] = path_info[len(self.script_name):]
        return self.app(environ, start_response)


def create_standalone_vizro_app(server=None):
    """
    Create standalone Vizro Dash app.

    Args:
        server: Optional Flask server to mount on. If None, creates standalone app at root.

    Returns:
        Vizro Dash app instance
    """
    # Load data into Vizro's data manager
    iris_df = pd.read_csv("https://raw.githubusercontent.com/plotly/datasets/master/iris.csv")
    data_manager["iris_data"] = iris_df

    # Create Vizro dashboard
    dashboard = vm.Dashboard(
        pages=[
            vm.Page(
                title="Iris Analysis",
                path="/",
                components=[
                    vm.Graph(
                        id="scatter_sepal",
                        figure=px.scatter(
                            data_frame="iris_data",
                            x="SepalLength",
                            y="SepalWidth",
                            color="Name",
                        ),
                    ),
                    vm.Graph(
                        id="scatter_petal",
                        figure=px.scatter(
                            data_frame="iris_data",
                            x="PetalLength",
                            y="PetalWidth",
                            color="Name",
                        ),
                    ),
                ],
                controls=[
                    vm.Filter(column="Name", selector=vm.Dropdown(title="Species")),
                ],
            ),
            vm.Page(
                title="Distribution",
                path="/distribution",
                components=[
                    vm.Graph(
                        id="histogram_sepal",
                        figure=px.histogram(
                            data_frame="iris_data",
                            x="SepalLength",
                            color="Name",
                        ),
                    ),
                    vm.Graph(
                        id="histogram_petal",
                        figure=px.histogram(
                            data_frame="iris_data",
                            x="PetalLength",
                            color="Name",
                        ),
                    ),
                ],
            ),
        ],
    )

    # Build Vizro with proper configuration
    if server:
        # WORKAROUND: First build WITHOUT server to get callbacks registered
        vizro_app = Vizro().build(dashboard)
        print(f"DEBUG: Vizro callbacks registered (standalone): {len(vizro_app.dash.callback_map)}")

        # Then manually set the server and update paths
        dash_app = vizro_app.dash
        dash_app.config.update({
            'url_base_pathname': '/vizro/',
            'requests_pathname_prefix': '/vizro/',
        })

        # Replace the Flask server
        from flask import Flask
        dash_app.server = server

        # Re-init to update routes with new server
        dash_app.init_app(dash_app)

        print("✅ Vizro app created and mounted at /vizro/")
        print(f"DEBUG: Final callback count: {len(dash_app.callback_map)}")
        print(f"DEBUG: Sample callbacks: {list(dash_app.callback_map.keys())[:3]}")
        return dash_app
    else:
        # Create standalone app at root
        vizro_app = Vizro().build(dashboard)
        print("✅ Vizro standalone app created at /")
        return vizro_app.dash


if __name__ == "__main__":
    app = create_standalone_vizro_app()
    print("=" * 80)
    print("📊 Vizro Standalone App")
    print("=" * 80)
    print("🌐 Running on: http://localhost:8051/")
    print("=" * 80)
    app.run(debug=True, port=8051)
