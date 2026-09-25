"""A/B compartment eigenvector track, one row per genomic bin.

``cooltools eigs-cis`` writes ``<sample>.<resolution>_compartments.cis.vecs.tsv``:
a per-bin table (``chrom``, ``start``, ``end``, ``weight``, ``E1``, ``E2``,
``E3``) of the first three eigenvectors of the intra-chromosomal correlation
matrix. ``E1`` is the compartment track: its sign, not magnitude, marks the two
compartments (conventionally "A" positive / GC-rich / gene-dense and "B"
negative), and its zero-crossings are compartment boundaries. Unmappable /
blacklisted bins carry empty numeric fields, which is why every value column is
read as text and cast with ``strict=False`` rather than inferred.

The file has a header but no sample column, so it is read through a **scan**
data collection whose `include_file_paths` carries the file path into the
frame, and the recipe reads it through `dc_ref`::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*\\.cis\\.vecs\\.tsv$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          include_file_paths: source_path
          infer_schema_length: 0

**E1 is phased here.** An eigenvector's sign is arbitrary: ``eigs-cis`` run
without a ``--phasing-track`` (nf-core/hic 2.0.0 passes none) returns each
chromosome's E1 with whatever sign the solver lands on, independently per
chromosome and per resolution, so "A" at 250 kb can be "B" at 500 kb on the
same bins. The recipe fixes the sign per (sample, resolution, chromosome):
when the run supplies no GC or gene track, it orients E1 so that it correlates
positively with the bin's contact coverage, read as ``1 / weight`` (cooler's
balancing weight is the inverse of a bin's raw coverage). The A compartment is
the open, gene-dense, well-mappable one and collects more contacts, so higher
coverage marks A; the rule depends on the data only, not on an assembly, and it
gives every resolution the same orientation because they share one coverage
profile. A chromosome whose E1 does not correlate with coverage at all (a
near-zero correlation, typical of chrY) keeps the solver's sign. E2 and E3 are
left as written.

``compartment`` turns that sign into a category ("A" / "B", null on a bin with
no E1), because the sign is what a reader groups and colours by: a continuous
E1 column can be plotted but it cannot fill a donut, drive a Select filter or
colour a track by compartment, and re-deriving ``E1 > 0`` in every tile is how
two tiles end up disagreeing about a bin exactly at zero.

Output schema:
    sample : Utf8        sample the compartments were called for
    resolution : Int64    bin size in bp
    chrom : Utf8          chromosome
    start : Int64          bin start
    end : Int64             bin end
    weight : Float64      cooler balancing weight for the bin (null on blacklisted bins)
    E1 : Float64          first eigenvector, the A/B compartment track, phased (A positive)
    compartment : Utf8    "A" where E1 is positive, "B" where it is negative, null on a bin with no E1
    E2 : Float64          second eigenvector
    E3 : Float64          third eigenvector
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.cooltools import float_col

#: Data-collection tag the recipe reads. A template reusing this recipe must
#: scan the per-sample vecs files into a DC with this tag (see module docstring).
RAW_DC_TAG = "cooltools_eigenvector_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="vecs", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "resolution": pl.Int64,
    "chrom": pl.Utf8,
    "start": pl.Int64,
    "end": pl.Int64,
    "weight": pl.Float64,
    "E1": pl.Float64,
    "compartment": pl.Utf8,
    "E2": pl.Float64,
    "E3": pl.Float64,
}

#: Sign of E1 -> compartment label. Exactly zero is treated as no call rather
#: than as A, so the two labels never overlap.
COMPARTMENT_LABELS = ("A", "B")

#: Grouping inside which the E1 sign is fixed: the solver picks one sign per
#: chromosome of one eigs-cis call.
PHASE_GROUP = ["sample", "resolution", "chrom"]

#: `<sample>.<resolution>_compartments.cis.vecs.tsv`
_PATH_RE = r"([^/\\]+)\.(\d+)_compartments\.cis\.vecs\.tsv$"


def phase_by_coverage(df: pl.DataFrame) -> pl.DataFrame:
    """Flip E1 per chromosome so it correlates positively with bin coverage.

    Coverage is ``1 / weight`` (the balancing weight is the inverse of a bin's
    raw coverage). A group with no usable bin, or a correlation that is null or
    exactly zero, keeps its sign.
    """
    coverage = pl.when(pl.col("weight") > 0).then(1.0 / pl.col("weight")).otherwise(None)
    signs = (
        df.with_columns(coverage.alias("_coverage"))
        .filter(pl.col("E1").is_not_null() & pl.col("_coverage").is_not_null())
        .group_by(PHASE_GROUP)
        .agg(pl.corr("E1", "_coverage").alias("_corr"))
        .with_columns(pl.when(pl.col("_corr") < 0).then(-1.0).otherwise(1.0).alias("_sign"))
        .select([*PHASE_GROUP, "_sign"])
    )
    return (
        df.join(signs, on=PHASE_GROUP, how="left")
        .with_columns((pl.col("E1") * pl.col("_sign").fill_null(1.0)).alias("E1"))
        .drop("_sign")
    )


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Cast the raw text columns and stamp sample / resolution from the file path."""
    df = sources["vecs"]
    df = df.with_columns(
        pl.col("source_path").str.extract(_PATH_RE, 1).alias("sample"),
        pl.col("source_path").str.extract(_PATH_RE, 2).cast(pl.Int64).alias("resolution"),
        pl.col("start").cast(pl.Int64, strict=False),
        pl.col("end").cast(pl.Int64, strict=False),
        float_col("weight"),
        float_col("E1"),
        float_col("E2"),
        float_col("E3"),
    )
    df = phase_by_coverage(df).with_columns(
        pl.when(pl.col("E1") > 0)
        .then(pl.lit(COMPARTMENT_LABELS[0], dtype=pl.Utf8))
        .when(pl.col("E1") < 0)
        .then(pl.lit(COMPARTMENT_LABELS[1], dtype=pl.Utf8))
        .otherwise(None)
        .alias("compartment")
    )
    return df.select(list(EXPECTED_SCHEMA)).sort(["sample", "resolution", "chrom", "start"])
