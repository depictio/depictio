"""Single-component embeds and headless Plotly-figure extraction.

The viewer's ``/embed/{dashboard}/{component}`` route renders one component
with an analysis state carried in the URL hash. ``extract.py`` loads that page
in the worker's headless Chromium and reads the Plotly figure back, which is
how a React-rendered advanced visualisation becomes a ``go.Figure`` in a
notebook without porting its renderer to Python.
"""
