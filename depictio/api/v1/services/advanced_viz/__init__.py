"""Server-side support for advanced visualisations.

``data`` loads the tidy column payload every advanced viz is built from.
``figure_registry`` maps a ``viz_kind`` to a Python builder that turns that
payload into a Plotly spec — the piece that lets an advanced viz be exported as
JSON rather than only as an HTML embed running the TypeScript renderer.
"""
