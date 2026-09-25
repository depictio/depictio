"""Contact probability against genomic distance, one row per distance bin.

``hicPlotDistVsCounts --outFileData`` writes ``<sample>_distcount.txt``: how
average contact frequency falls off with genomic distance, pooled across the
matrix (``Chromosome`` is the literal string ``"all"`` in every megatest row;
a per-chromosome run would carry one series per chromosome). The curve is the
classic Hi-C QC signature, a smooth, monotonic decay is a clean library, a
plateau or a bump is trans-contamination or a large structural artefact, and
it is small enough (one row per distance bin the matrix was binned at) that no
decimation is needed for the `profile` kind.

The file's own header carries an unlabelled leading index column (polars reads
it as an empty-string column, ``""``); the recipe drops it rather than reading
it as text and casting, which is why the raw scan is declared with
``has_header: true`` and no explicit ``new_columns``.

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*_distcount\\.txt$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          include_file_paths: source_path
          infer_schema_length: 0

Output schema:
    sample : Utf8         sample the matrix was dumped for
    resolution : Int64     bin size in bp, read off the Matrix column
    chromosome : Utf8      "all" (pooled) or a single chromosome
    distance : Int64        genomic distance in bp
    contacts : Float64     mean contact frequency at that distance
    number_bins : Int64     bin pairs averaged into this row
    scale_factor : Float64  matrix-wide normalisation factor hicexplorer applied
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads. A template reusing this recipe must
#: scan the per-sample distcount files into a DC with this tag (see module docstring).
RAW_DC_TAG = "hicexplorer_distance_decay_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="decay", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "resolution": pl.Int64,
    "chromosome": pl.Utf8,
    "distance": pl.Int64,
    "contacts": pl.Float64,
    "number_bins": pl.Int64,
    "scale_factor": pl.Float64,
}

#: The `Matrix` column: `<sample>.<resolution>_balanced.cool`
_MATRIX_RE = r"([^/\\]+)\.(\d+)_balanced\.cool$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Cast the raw text columns and split sample / resolution out of `Matrix`."""
    df = sources["decay"]
    df = df.with_columns(
        pl.col("Matrix").str.extract(_MATRIX_RE, 1).alias("sample"),
        pl.col("Matrix").str.extract(_MATRIX_RE, 2).cast(pl.Int64).alias("resolution"),
        pl.col("Chromosome").cast(pl.Utf8).alias("chromosome"),
        pl.col("Distance").cast(pl.Int64, strict=False).alias("distance"),
        pl.col("Contacts").cast(pl.Float64, strict=False).alias("contacts"),
        pl.col("Number_bins").cast(pl.Int64, strict=False).alias("number_bins"),
        pl.col("Scale_factor").cast(pl.Float64, strict=False).alias("scale_factor"),
    )
    return df.select(list(EXPECTED_SCHEMA)).sort(["sample", "resolution", "chromosome", "distance"])
