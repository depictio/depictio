"""Per-sample Phylum-level relative abundance from sintax (--skip_qiime) outputs.

ITS / PacBio / IonTorrent runs use sintax (``--skip_qiime``) and produce NO QIIME2
relative-abundance table. They DO produce a DADA2 ASV count table
(``dada2/ASV_table.tsv``, ASV_ID + one count column per sample) and a sintax
per-ASV taxonomy table (``sintax/ASV_tax_sintax.<ref-db>.tsv``). Joining the two
and aggregating to Phylum level yields the same canonical schema as the QIIME2
``taxonomy_rel_abundance`` DC, so the Community & Diversity tab can render for
skip_qiime runs instead of degrading to MultiQC-only.

When a metadata DC is present, all metadata columns are joined generically (so
the parameterised dashboard's ``{GROUP_COL}`` faceting works just like the
QIIME2 path). Without metadata only the core columns are returned.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="asv", path="dada2/ASV_table.tsv", format="TSV"),
    # The sintax filename carries the reference-DB tag (e.g. `unite-fungi_8_2`),
    # so glob on it. The clean table's stem ends in the DB version digit
    # (`..._8_2.tsv`), so `*[0-9].tsv` matches it; the `.raw.tsv` variant always
    # has `raw` (no trailing digit) immediately before `.tsv`, so it never matches.
    RecipeSource(ref="tax", glob_pattern="sintax/ASV_tax_sintax.*[0-9].tsv", format="TSV"),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "taxonomy": pl.Utf8,
    "rel_abundance": pl.Float64,
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
}
# Metadata columns are user-defined; validated dynamically via OPTIONAL_SCHEMA = {}.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_UNCLASSIFIED = "Unclassified"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Join ASV counts with sintax taxonomy, aggregate to per-sample Phylum abundance."""
    asv = sources["asv"]
    tax = sources["tax"]

    sample_cols = [c for c in asv.columns if c != "ASV_ID"]
    long = (
        asv.with_columns(pl.col(sample_cols).cast(pl.Float64))
        .unpivot(on=sample_cols, index="ASV_ID", variable_name="sample", value_name="count")
        .filter(pl.col("count") > 0)
    )

    tax_slim = tax.select(
        "ASV_ID",
        pl.col("Kingdom").cast(pl.Utf8).fill_null(_UNCLASSIFIED),
        pl.col("Phylum").cast(pl.Utf8).fill_null(_UNCLASSIFIED),
    )
    long = long.join(tax_slim, on="ASV_ID", how="left").with_columns(
        pl.col("Kingdom").fill_null(_UNCLASSIFIED),
        pl.col("Phylum").fill_null(_UNCLASSIFIED),
    )

    # Aggregate ASV counts to Phylum level per sample, then normalise to per-sample
    # relative abundance.
    phylum = long.group_by(["sample", "Kingdom", "Phylum"]).agg(
        pl.col("count").sum().alias("count")
    )
    totals = phylum.group_by("sample").agg(pl.col("count").sum().alias("_total"))
    phylum = (
        phylum.join(totals, on="sample", how="left")
        .with_columns((pl.col("count") / pl.col("_total")).alias("rel_abundance"))
        .with_columns((pl.col("Kingdom") + ";" + pl.col("Phylum")).alias("taxonomy"))
        .filter(pl.col("rel_abundance") > 0)
    )

    df = phylum.select("sample", "taxonomy", "rel_abundance", "Kingdom", "Phylum")

    # Join ALL metadata columns generically when metadata is available.
    metadata = sources.get("metadata")
    if metadata is not None and metadata.height > 0:
        id_col = next((c for c in ("ID", "sample") if c in metadata.columns), metadata.columns[0])
        if id_col != "sample":
            metadata = metadata.rename({id_col: "sample"})
        df = df.join(metadata, on="sample", how="left")

    return df.sort(["sample", "Phylum"])
