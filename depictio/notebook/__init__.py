"""Depictio in a Quarto document (or any Jupyter kernel).

>>> from depictio.notebook import DepictioClient
>>> client = DepictioClient()                       # DEPICTIO_API_URL / DEPICTIO_API_TOKEN
>>> dash = "6824cb3b89d2b72169309738"
>>> client.component(dash, "Bill shape")            # a Plotly figure, rendered inline
>>> client.component(dash, "Raw data").data         # a polars DataFrame
>>> client.data("646b0f3c1e4a2d7f8e5b8ca1")         # a whole data collection

Every dashboard component is importable: figures, maps and MultiQC plots come
back as Plotly figures; advanced visualisations too (built or extracted from
the real renderer on the server), and the ones the app draws without Plotly
are drawn here from their data (``depictio.notebook.native``: Plotly, py3Dmol,
SVG, HTML), with the server's snapshot as the fallback; tables and filters as
DataFrames; cards, text, image galleries and JBrowse sessions as HTML. A component displays itself through
the kernel's ``_repr_mimebundle_`` hook — which is what ``quarto render``
captures — and exposes ``.figure``, ``.data`` and ``.html`` when you want the
object rather than the picture.

In a ``.qmd``::

    ```{python}
    from depictio.notebook import DepictioClient
    DepictioClient().component("6824cb3b89d2b72169309738", "Bill shape")
    ```

"""

from .client import DepictioClient, DepictioClientError
from .components import (
    DepictioComponent,
    StaticCard,
    html_text,
    init_tables,
    set_static_width,
    show_table,
    static_card_row,
    static_figures,
    use_document_renderer,
)
from .funnel import funnel_rest, funnel_stage
from .native import use_native
from .text import fill_text
from .theme import use_theme

__all__ = [
    "DepictioClient",
    "DepictioClientError",
    "DepictioComponent",
    "fill_text",
    "funnel_rest",
    "html_text",
    "funnel_stage",
    "init_tables",
    "StaticCard",
    "set_static_width",
    "show_table",
    "static_card_row",
    "static_figures",
    "use_document_renderer",
    "use_native",
    "use_theme",
]
