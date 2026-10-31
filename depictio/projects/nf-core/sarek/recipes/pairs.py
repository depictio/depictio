"""One row per tumour/normal pair of the samplesheet.

sarek pairs every tumour sample of a patient with the patient's normal sample
(status 1 against status 0) and names the pair's callers' files after it,
``<tumour>_vs_<normal>``. The pairs come from the sample hub, not from the
calls: a pair is a design fact, so it is listed whether or not a paired caller
ran on it.

A patient with no normal (tumour-only) or no tumour (germline only) has no pair.
A run whose samplesheet describes no pair at all has nothing to list, so the
recipe raises and the collection, being optional, is skipped: the tab that
compares a pair's somatic calls with its normal's germline calls does not appear.

Output schema:
    pair_id  : Utf8   `<tumour>_vs_<normal>`, the name sarek gives the pair's files
    patient  : Utf8   the patient both samples belong to
    tumour   : Utf8   the tumour sample (status 1)
    normal   : Utf8   the normal sample (status 0)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sarek_units import PAIR_SEP

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="hub",
        dc_ref="samples",
        input_schema={"sample_id": pl.Utf8, "patient": pl.Utf8, "status": pl.Int64},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "pair_id": pl.Utf8,
    "patient": pl.Utf8,
    "tumour": pl.Utf8,
    "normal": pl.Utf8,
}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Every tumour of a patient against every normal of the same patient."""
    hub = sources["hub"].filter(pl.col("patient").is_not_null())
    tumours = hub.filter(pl.col("status") == 1).select(
        "patient", pl.col("sample_id").alias("tumour")
    )
    normals = hub.filter(pl.col("status") == 0).select(
        "patient", pl.col("sample_id").alias("normal")
    )
    pairs = tumours.join(normals, on="patient", how="inner")
    if pairs.is_empty():
        raise ValueError(
            "sarek pairs: no patient has both a tumour (status 1) and a normal (status 0) "
            "sample, so the run has no tumour/normal pair"
        )
    return (
        pairs.with_columns(
            pl.concat_str([pl.col("tumour"), pl.lit(PAIR_SEP), pl.col("normal")]).alias("pair_id")
        )
        .select(list(OUTPUT_SCHEMA))
        .sort("pair_id")
    )
