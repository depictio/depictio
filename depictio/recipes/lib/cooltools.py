"""Column casts shared by the cooltools recipes.

cooltools writes its per-bin tables (insulation, boundary strength, the
eigenvector tracks) with the numeric fields spelled as text, masked bins as
``nan`` and blacklisted bins as empty fields, so the raw data collections read
every column as text (``infer_schema_length: 0``) and the recipes cast. Two of
them cast the same way and recipes may not import each other, so the cast
lives here.
"""

from __future__ import annotations

import polars as pl


def float_col(name: str) -> pl.Expr:
    """A numeric text column ("nan" on masked bins) as a nullable Float64."""
    return pl.col(name).replace("nan", None).cast(pl.Float64, strict=False).alias(name)
