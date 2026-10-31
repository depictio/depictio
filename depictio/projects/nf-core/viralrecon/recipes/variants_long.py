"""viralrecon's variant calls, with a ranking column for the call the dashboard opens on.

The catalog recipe ``ivar/variants_long.py`` cleans the pipeline's
``variants_long_table.csv``; this one keeps its transform and adds ``call_score``,
the number the genome browser sorts on (``locus_from.sort_by``) and the Gene tab
ranks its genes by (``default_by``).

Sorting on the allele frequency alone is arbitrary: most calls of a run sit at 1.0,
so the first of them was whichever the table listed first, and it could be an
intergenic call (snpEff names its gene ``<left gene>-<right gene>``, or
``CHR_START-<gene>`` before the first one), which carries no protein change and
would also set the Gene picker's default. The score ranks, in this order:

1. calls inside a gene before intergenic ones (those are shifted far below);
2. the allele frequency (to three decimals);
3. the read depth, which breaks the ties at a frequency of 1.0.

Higher is better, so a plain descending sort or a ``max`` per gene reads it.

Output schema: the catalog ``ivar/variants_long.py`` columns plus
    call_score : Float64   support rank of the call (higher = better supported)
"""

from __future__ import annotations

import polars as pl

from depictio.catalog.ivar.variants_long import OUTPUT_SCHEMA as _CATALOG_SCHEMA
from depictio.catalog.ivar.variants_long import SOURCES
from depictio.catalog.ivar.variants_long import transform as _catalog_transform

# INPUT SCHEMA: the catalog recipe's (the same raw scan).
__all__ = ["OUTPUT_SCHEMA", "SOURCES", "transform"]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {**_CATALOG_SCHEMA, "call_score": pl.Float64}

# snpEff effects that sit outside a gene body, and the pseudo-genes it names them with.
_OUTSIDE_EFFECT = r"(?i)intergenic|upstream_gene|downstream_gene"
_OUTSIDE_GENE = r"(?i)^unknown$|^chr_(start|end)|-"
# A depth past this adds nothing to the ranking and would overflow the AF digits.
_MAX_DEPTH = 9_999_999
# Calls outside a gene sort below every call inside one (the largest in-gene score is 1e10).
_OUTSIDE_OFFSET = 1e11


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """The catalog's variant table plus ``call_score``."""
    df = _catalog_transform(sources)
    outside = pl.lit(False)
    if "EFFECT" in df.columns:
        outside = outside | pl.col("EFFECT").str.contains(_OUTSIDE_EFFECT)
    if "GENE" in df.columns:
        outside = outside | pl.col("GENE").str.contains(_OUTSIDE_GENE)
    af = pl.col("AF").fill_null(0.0) if "AF" in df.columns else pl.lit(0.0)
    depth = (
        pl.col("DP").fill_null(0).clip(0, _MAX_DEPTH).cast(pl.Float64)
        if "DP" in df.columns
        else pl.lit(0.0)
    )
    score = (af * 1000).round(0) * 1e7 + depth
    return df.with_columns(
        pl.when(outside).then(score - _OUTSIDE_OFFSET).otherwise(score).alias("call_score")
    )
