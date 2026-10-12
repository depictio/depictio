"""Component export — serving a single dashboard component to an external site.

Two output formats, with deliberately different coverage:

* ``json`` — a Plotly spec (``{data, layout, config}``) the consumer drops into
  its own plotly.js. Only available where a figure is built server-side.
* ``html`` — a self-contained offline page running the real React
  ``ComponentRenderer``. Covers every component type except ``jbrowse``,
  because the client-side TS renderers ship inside the bundle.

``capabilities`` is the single source of truth for which pairs are supported;
everything else in this package (and the export routes) reads from it.
"""
