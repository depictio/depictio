"""Process ampliseq source data into dashboard-ready TSV files.

Fixes 3 data issues identified by Daniel Straub (nf-core/ampliseq lead):
1. Alpha diversity: use per-sample values instead of rarefaction data
2. Taxonomy: use relative abundance instead of raw counts
3. Differential abundance: use ANCOM-BC instead of ANCOM
"""

import math
from pathlib import Path

import polars as pl

SOURCE_DIR = Path(
    "/Users/tweber/Data/ampliseq-testdata/"
    "results-9c52c22f17179b9bd5cb2621c05ec3a931adcb02/qiime2"
)
OUTPUT_DIR = Path(__file__).parent
METADATA_PATH = Path(__file__).parents[2] / "depictio/projects/reference/ampliseq/merged_metadata.tsv"


def process_alpha_diversity() -> pl.DataFrame:
    """Extract per-sample Faith PD from alpha diversity vector.

    Source: diversity/alpha_diversity/faith_pd_vector/metadata.tsv
    Output: sample, habitat, faith_pd (one row per sample)
    """
    src = SOURCE_DIR / "diversity/alpha_diversity/faith_pd_vector/metadata.tsv"
    df = pl.read_csv(src, separator="\t")
    # Skip the #q2:types annotation row
    df = df.filter(~pl.col("id").str.starts_with("#"))
    df = df.select(
        pl.col("id").alias("sample"),
        pl.col("habitat"),
        pl.col("faith_pd").cast(pl.Float64),
    )
    return df


def process_taxonomy_rel_abundance() -> pl.DataFrame:
    """Melt relative abundance table from wide to long format.

    Source: rel_abundance_tables/rel-table-2.tsv (phylum level)
    Output: sample, taxonomy, rel_abundance, habitat, Kingdom, Phylum
    """
    src = SOURCE_DIR / "rel_abundance_tables/rel-table-2.tsv"
    # Read skipping the comment line
    df = pl.read_csv(src, separator="\t", comment_prefix="#", has_header=False)

    # First row after comment is the header with #OTU ID
    # Re-read properly: skip 1 line (the comment), use next as header
    with open(src) as f:
        lines = f.readlines()
    # lines[0] is "# Constructed from biom file"
    # lines[1] is "#OTU ID\tSRR...\t..."
    header = lines[1].strip().split("\t")
    header[0] = "taxonomy"  # rename #OTU ID
    data_lines = [line.strip().split("\t") for line in lines[2:] if line.strip()]

    df = pl.DataFrame(
        {header[i]: [row[i] for row in data_lines] for i in range(len(header))}
    )

    # Cast sample columns to float
    sample_cols = [c for c in df.columns if c != "taxonomy"]
    df = df.with_columns([pl.col(c).cast(pl.Float64) for c in sample_cols])

    # Melt wide to long
    df_long = df.unpivot(
        on=sample_cols,
        index="taxonomy",
        variable_name="sample",
        value_name="rel_abundance",
    )

    # Filter out zero/null
    df_long = df_long.filter(
        pl.col("rel_abundance").is_not_null() & (pl.col("rel_abundance") > 0)
    )

    # Parse Kingdom and Phylum from taxonomy string
    # Label empty phylum as "Unclassified" so per-sample bars sum to 1
    df_long = df_long.with_columns(
        pl.col("taxonomy").str.split(";").list.get(0).alias("Kingdom"),
        pl.when(
            (pl.col("taxonomy").str.split(";").list.get(1).is_null())
            | (pl.col("taxonomy").str.split(";").list.get(1) == "")
        )
        .then(pl.lit("Unclassified"))
        .otherwise(pl.col("taxonomy").str.split(";").list.get(1))
        .alias("Phylum"),
    )

    # Join with metadata for habitat
    metadata = pl.read_csv(METADATA_PATH, separator="\t").select("sample", "habitat")
    df_long = df_long.join(metadata, on="sample", how="left")

    return df_long.select("sample", "taxonomy", "rel_abundance", "habitat", "Kingdom", "Phylum")


def process_ancombc() -> pl.DataFrame:
    """Merge ANCOM-BC result slices into a single long-format table.

    Source: ancombc/differentials/Category-habitat-level-2/*.csv
    Output: id, contrast, lfc, p_val, q_val, w, se, Kingdom, Phylum, neg_log10_qval, significant
    """
    src_dir = SOURCE_DIR / "ancombc/differentials/Category-habitat-level-2"

    slices = {}
    for name in ["lfc", "p_val", "q_val", "w", "se"]:
        slices[name] = pl.read_csv(src_dir / f"{name}_slice.csv")

    # Identify contrast columns (all except 'id' and '(Intercept)')
    all_cols = slices["lfc"].columns
    contrast_cols = [c for c in all_cols if c not in ("id", "(Intercept)")]

    # Melt each slice to long format
    melted = {}
    for name, df in slices.items():
        m = df.select("id", *contrast_cols).unpivot(
            on=contrast_cols,
            index="id",
            variable_name="contrast",
            value_name=name,
        )
        melted[name] = m

    # Merge all slices
    result = melted["lfc"]
    for name in ["p_val", "q_val", "w", "se"]:
        result = result.join(melted[name], on=["id", "contrast"], how="left")

    # Cast numeric columns
    for col in ["lfc", "p_val", "q_val", "w", "se"]:
        result = result.with_columns(pl.col(col).cast(pl.Float64))

    # Parse Kingdom and Phylum (label empty as "Unclassified")
    result = result.with_columns(
        pl.col("id").str.split(";").list.get(0).alias("Kingdom"),
        pl.when(
            (pl.col("id").str.split(";").list.get(1).is_null())
            | (pl.col("id").str.split(";").list.get(1) == "")
        )
        .then(pl.lit("Unclassified"))
        .otherwise(pl.col("id").str.split(";").list.get(1))
        .alias("Phylum"),
    )

    # Compute -log10(q_val) and significance
    result = result.with_columns(
        pl.col("q_val")
        .map_elements(
            lambda x: -math.log10(x) if x is not None and x > 0 else 0.0,
            return_dtype=pl.Float64,
        )
        .alias("neg_log10_qval"),
        (pl.col("q_val") < 0.05).alias("significant"),
    )

    return result.select(
        "id", "contrast", "lfc", "p_val", "q_val", "w", "se",
        "Kingdom", "Phylum", "neg_log10_qval", "significant",
    )


if __name__ == "__main__":
    print("Processing alpha diversity...")
    alpha = process_alpha_diversity()
    alpha.write_csv(OUTPUT_DIR / "alpha_diversity.tsv", separator="\t")
    print(f"  -> {alpha.shape[0]} rows, columns: {alpha.columns}")

    print("Processing taxonomy relative abundance...")
    tax = process_taxonomy_rel_abundance()
    tax.write_csv(OUTPUT_DIR / "taxonomy_rel_abundance_long.tsv", separator="\t")
    print(f"  -> {tax.shape[0]} rows, columns: {tax.columns}")

    print("Processing ANCOM-BC...")
    ancombc = process_ancombc()
    ancombc.write_csv(OUTPUT_DIR / "ancombc_habitat_level2.tsv", separator="\t")
    print(f"  -> {ancombc.shape[0]} rows, columns: {ancombc.columns}")

    print("Done!")
