"""Empty output frames shared by the recipes.

A recipe whose sources hold nothing usable returns a frame with its declared
schema and no rows, so the data collection stays well typed. The hicpro and
cooltools recipes all do exactly that, and recipes may not import each other, so
the constructor lives here.
"""

from __future__ import annotations

import polars as pl


def empty_frame(schema: dict[str, type[pl.DataType]]) -> pl.DataFrame:
    """A zero-row frame carrying ``schema``."""
    return pl.DataFrame(schema=schema)
