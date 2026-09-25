"""Fragment-ion annotation summary, one row per sample and peptidoform.

With ``--annotate_ions`` mhcquant runs pyOpenMS' ion annotator over the spectra
of the identified peptides and writes, per sample,
``intermediate_results/ion_annotations/<sample>_matching_ions.tsv``: one row per
fragment ion matched to a peak, with the ion name (``b2+``, ``y6++``, internal
and immonium ions), its charge, theoretical and experimental mass and the peak
intensity. The companion ``*_all_peaks.tsv`` lists every peak of every spectrum
and is not read.

The recipe counts the matched ions per peptide and per series and takes the
median absolute fragment mass error in ppm, which is what separates a
well-annotated identification from one resting on a handful of peaks.
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="ions",
        glob_pattern="intermediate_results/ion_annotations/*_matching_ions.tsv",
        format="tsv",
        read_kwargs={"infer_schema_length": 0},
        source_path="source_path",
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "peptide": pl.Utf8,
    "fragment_ions": pl.Int64,
    "b_ions": pl.Int64,
    "y_ions": pl.Int64,
    "other_ions": pl.Int64,
    "fragment_error_ppm": pl.Float64,
    "matched_intensity": pl.Float64,
}
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    ions = sources["ions"].filter(pl.col("Peptide").is_not_null())
    theo = pl.col("Theoretical_mass").cast(pl.Float64, strict=False)
    expt = pl.col("Experimental_mass").cast(pl.Float64, strict=False)
    series = pl.col("Ion_name").str.extract(r"^([a-z])", 1)
    return (
        ions.with_columns(
            pl.col("source_path")
            .str.split("/")
            .list.last()
            .str.replace(r"_matching_ions\.tsv$", "")
            .alias("sample"),
            ((expt - theo) / theo * 1e6).abs().alias("_err"),
            series.alias("_series"),
            pl.col("Intensity").cast(pl.Float64, strict=False).alias("_int"),
        )
        .group_by("sample", pl.col("Peptide").alias("peptide"))
        .agg(
            pl.len().cast(pl.Int64).alias("fragment_ions"),
            (pl.col("_series") == "b").sum().cast(pl.Int64).alias("b_ions"),
            (pl.col("_series") == "y").sum().cast(pl.Int64).alias("y_ions"),
            (~pl.col("_series").is_in(["b", "y"]).fill_null(False))
            .sum()
            .cast(pl.Int64)
            .alias("other_ions"),
            pl.col("_err").median().alias("fragment_error_ppm"),
            pl.col("_int").sum().alias("matched_intensity"),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "peptide"])
    )
