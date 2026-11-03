"""OptiType genotypes of nf-core/hlatyping with the sample's design columns.

The catalog recipe ``optitype/genotypes.py`` melts each sample's optimal
OptiType solution long: one row per sample, locus and haplotype, alleles
normalised to ``HLA-A*02:01``. This one writes the same rows and adds the
sample hub's columns (``seq_type``, ``input_format``, ``read_layout``, ``runs``
and any design column the samplesheet carries), joined on the sample, so the
allele grid can group its rows by them and a figure can colour by
``GROUP_COL`` like the rest of the dashboard. A sample the hub does not list
keeps its rows with empty design columns.

Sources:
    results  optitype/<sample>/<sample>_result.tsv
    samples  the sample hub (dc_ref), for the design columns

Output: the ten columns of ``optitype/genotypes.py`` (call_id, sample_id,
locus, haplotype, allele, allele_group, hla_class, zygosity, reads,
objective), then the hub's columns except ``sample`` and ``input_files``.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.optitype import best_calls, read_calls, with_call_annotations

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="results",
        input_schema={"source_path": pl.Utf8, "Reads": pl.Utf8, "Objective": pl.Utf8},
        glob_pattern="optitype/*/*_result.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
    RecipeSource(ref="samples", dc_ref="samples", input_schema={"sample": pl.Utf8}),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "call_id": pl.Utf8,
    "sample_id": pl.Utf8,
    "locus": pl.Utf8,
    "haplotype": pl.Int64,
    "allele": pl.Utf8,
    "allele_group": pl.Utf8,
    "hla_class": pl.Utf8,
    "zygosity": pl.Utf8,
    "reads": pl.Int64,
    "objective": pl.Float64,
}
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    calls = best_calls(read_calls(sources["results"]))
    if calls.is_empty():
        raise ValueError("OptiType results: no sample has a typed locus")
    genotypes = (
        with_call_annotations(calls)
        .with_columns(
            (
                pl.col("sample_id")
                + "|"
                + pl.col("locus")
                + "|"
                + pl.col("haplotype").cast(pl.Utf8)
            ).alias("call_id")
        )
        .select(list(OUTPUT_SCHEMA))
    )
    hub = sources["samples"]
    # The sample's design columns; its input file names stay on the hub.
    hub_cols = [
        c for c in hub.columns if c not in ("sample", "input_files") and c not in genotypes.columns
    ]
    out = genotypes.join(
        hub.select(["sample", *hub_cols]).unique(subset="sample", keep="first"),
        left_on="sample_id",
        right_on="sample",
        how="left",
    )
    lead = list(OUTPUT_SCHEMA)
    return out.select(lead + [c for c in out.columns if c not in lead]).sort(
        ["sample_id", "locus", "haplotype"]
    )
