"""Depictio in a notebook: Jupyter, marimo or Quarto.

>>> from depictio.notebook import DepictioClient
>>> client = DepictioClient()                       # DEPICTIO_API_URL / DEPICTIO_API_TOKEN
>>> dash = "6824cb3b89d2b72169309738"
>>> client.component(dash, "Bill shape")            # a Plotly figure, rendered inline
>>> client.component(dash, "Raw data").data         # a polars DataFrame
>>> client.data("646b0f3c1e4a2d7f8e5b8ca1")         # a whole data collection

Every dashboard component is importable: figures, maps and MultiQC plots come
back as Plotly figures; advanced visualisations too (extracted from the real
renderer on the server); tables and filters as DataFrames; cards, text, image
galleries and JBrowse sessions as HTML. A component displays itself in all
three environments — Jupyter and Quarto through ``_repr_mimebundle_``, marimo
through ``_mime_`` — and exposes ``.figure``, ``.data`` and ``.html`` when you
want the object rather than the picture.

In a ``.qmd``::

    ```{python}
    from depictio.notebook import DepictioClient
    DepictioClient().component("6824cb3b89d2b72169309738", "Bill shape")
    ```

In marimo::

    import marimo as mo
    viz = DepictioClient().component("6824cb3b89d2b72169309738", "Bill shape")
    mo.ui.plotly(viz.figure)   # or just `viz`
"""

from .client import DepictioClient, DepictioClientError
from .components import DepictioComponent

__all__ = ["DepictioClient", "DepictioClientError", "DepictioComponent"]
