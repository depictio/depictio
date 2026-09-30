"""One row per nf-core/molkart sample: the samplesheet, joined to the run's design.

molkart names every per-sample output after the samplesheet ``sample`` column
(``<sample>_<method>_filtered.tif``, ``cellxgene_<sample>_<method>.csv``,
``<sample>.<method>.spot_QC.csv``), so this hub is the samplesheet itself: the
id, the nuclear image, the spot table and the optional membrane image of each
sample. The samplesheet carries no design column, so the design comes from an
optional table declared through ``METADATA_FILE`` (the ampliseq convention):
sample id in a column named ``sample`` or else in the first column, every other
column a factor. Nothing is parsed out of the sample names.

The samplesheet is not published by the pipeline: it is the file ``--input``
named, fetched into ``input/`` next to the results (any ``samplesheet*.csv``
there; several are concatenated and de-duplicated on the sample).

Output schema:
    sample_id : Utf8        samplesheet sample name, the key every output uses
    nuclear_image : Utf8    nuclear stain image path/URL
    spot_table : Utf8       spot table path/URL
    membrane_image : Utf8   membrane image path/URL, empty when the sample has none
    has_membrane : Utf8     yes | no: whether segmentation saw a two-channel stack
    <design columns> : Utf8 one per factor of METADATA_FILE, when given
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samplesheet",
        glob_pattern="input/samplesheet*.csv",
        format="CSV",
        read_kwargs={"infer_schema_length": 0},
    ),
    RecipeSource(ref="design", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample_id": pl.Utf8,
    "nuclear_image": pl.Utf8,
    "spot_table": pl.Utf8,
    "membrane_image": pl.Utf8,
    "has_membrane": pl.Utf8,
}
# Design columns are run-dependent; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

SHEET_COLUMNS = ("nuclear_image", "spot_table", "membrane_image")
#: design-table columns that are never a factor
NON_FACTOR_COLUMNS = frozenset({"sample", "sample_id", *SHEET_COLUMNS})


def _design(design: pl.DataFrame | None) -> pl.DataFrame | None:
    """The design table keyed on ``sample_id``, factors as strings, in file order."""
    if design is None or design.is_empty() or design.width < 2:
        return None
    id_col = "sample" if "sample" in design.columns else design.columns[0]
    factors = [c for c in design.columns if c != id_col and c not in NON_FACTOR_COLUMNS]
    if not factors:
        return None
    return design.select(
        pl.col(id_col).cast(pl.Utf8).alias("sample_id"),
        *[pl.col(c).cast(pl.Utf8) for c in factors],
    ).unique(subset="sample_id", keep="first", maintain_order=True)


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """The samplesheet's sample and image / spot columns, plus the design factors."""
    sheet = sources["samplesheet"]
    if sheet is None or "sample" not in sheet.columns:
        columns = None if sheet is None else sheet.columns
        raise ValueError(f"molkart samples: samplesheet lacks a 'sample' column, got {columns}")

    hub = (
        sheet.select(
            pl.col("sample").cast(pl.Utf8).str.strip_chars().alias("sample_id"),
            *[
                (pl.col(c) if c in sheet.columns else pl.lit(None))
                .cast(pl.Utf8)
                .fill_null("")
                .alias(c)
                for c in SHEET_COLUMNS
            ],
        )
        .filter(pl.col("sample_id").is_not_null() & (pl.col("sample_id") != ""))
        .unique(subset="sample_id", keep="first", maintain_order=True)
        .with_columns(
            pl.when(pl.col("membrane_image").str.strip_chars() != "")
            .then(pl.lit("yes"))
            .otherwise(pl.lit("no"))
            .alias("has_membrane")
        )
    )
    design = _design(sources.get("design"))
    if design is not None:
        hub = hub.join(design, on="sample_id", how="left")
    return hub.sort("sample_id")
