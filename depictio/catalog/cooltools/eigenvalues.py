"""A/B compartment eigenvalues, one row per chromosome.

``cooltools eigs-cis`` writes ``<sample>.<resolution>_compartments.cis.lam.txt``
next to the per-bin ``.vecs.tsv``: one row per chromosome with the eigenvalue
of each of the first three eigenvectors (``eigval1``/2/3), i.e. how much of the
intra-chromosomal correlation structure each eigenvector explains. It is the
per-chromosome QC companion to ``cooltools/eigenvector``'s per-bin ``E1`` track.

The file has a header but no sample column, so it is read through a **scan**
data collection whose `include_file_paths` carries the file path into the
frame, and the recipe reads it through `dc_ref`::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*\\.cis\\.lam\\.txt$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          include_file_paths: source_path
          infer_schema_length: 0

Output schema:
    sample : Utf8        sample the compartments were called for
    resolution : Int64    bin size in bp
    chrom : Utf8          chromosome (`name` in the raw file)
    eigval1 : Float64     eigenvalue of E1, the A/B compartment track
    eigval2 : Float64     eigenvalue of E2
    eigval3 : Float64     eigenvalue of E3
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Data-collection tag the recipe reads. A template reusing this recipe must
#: scan the per-sample lam files into a DC with this tag (see module docstring).
RAW_DC_TAG = "cooltools_eigenvalues_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="lam", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "resolution": pl.Int64,
    "chrom": pl.Utf8,
    "eigval1": pl.Float64,
    "eigval2": pl.Float64,
    "eigval3": pl.Float64,
}

#: `<sample>.<resolution>_compartments.cis.lam.txt`
_PATH_RE = r"([^/\\]+)\.(\d+)_compartments\.cis\.lam\.txt$"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Cast the raw text columns and stamp sample / resolution from the file path."""
    df = sources["lam"]
    df = df.with_columns(
        pl.col("source_path").str.extract(_PATH_RE, 1).alias("sample"),
        pl.col("source_path").str.extract(_PATH_RE, 2).cast(pl.Int64).alias("resolution"),
        pl.col("name").cast(pl.Utf8).alias("chrom"),
        pl.col("eigval1").cast(pl.Float64, strict=False),
        pl.col("eigval2").cast(pl.Float64, strict=False),
        pl.col("eigval3").cast(pl.Float64, strict=False),
    )
    return df.select(list(EXPECTED_SCHEMA)).sort(["chrom"])
