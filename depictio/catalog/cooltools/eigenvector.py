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

Output schema:
    sample : Utf8        sample the compartments were called for
    resolution : Int64    bin size in bp
    chrom : Utf8          chromosome
    start : Int64          bin start
    end : Int64             bin end
    weight : Float64      cooler balancing weight for the bin (null on blacklisted bins)
    E1 : Float64          first eigenvector, the A/B compartment track
    E2 : Float64          second eigenvector
    E3 : Float64          third eigenvector
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

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
    "E2": pl.Float64,
    "E3": pl.Float64,
}

#: `<sample>.<resolution>_compartments.cis.vecs.tsv`
_PATH_RE = r"([^/\\]+)\.(\d+)_compartments\.cis\.vecs\.tsv$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Cast the raw text columns and stamp sample / resolution from the file path."""
    df = sources["vecs"]
    df = df.with_columns(
        pl.col("source_path").str.extract(_PATH_RE, 1).alias("sample"),
        pl.col("source_path").str.extract(_PATH_RE, 2).cast(pl.Int64).alias("resolution"),
        pl.col("start").cast(pl.Int64, strict=False),
        pl.col("end").cast(pl.Int64, strict=False),
        pl.col("weight").cast(pl.Float64, strict=False),
        pl.col("E1").cast(pl.Float64, strict=False),
        pl.col("E2").cast(pl.Float64, strict=False),
        pl.col("E3").cast(pl.Float64, strict=False),
    )
    return df.select(list(EXPECTED_SCHEMA)).sort(["chrom", "start"])
