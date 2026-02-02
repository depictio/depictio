#!/usr/bin/env python3
"""
Process AmpliseQ test data for depictio demo dataset.

This script generates the processed TSV files needed for the ampliseq project:
- faith_pd_long.tsv: Alpha diversity rarefaction data
- taxonomy_long.tsv: Taxonomic composition at Phylum level
- ancom_volcano.tsv: Differential abundance results
"""

import pandas as pd
from pathlib import Path
from typing import Optional

# ============================================
# CONFIGURATION
# ============================================

# Use the test dataset (12 samples)
INPUT_DIR = Path(
    "/Users/tweber/Data/ampliseq-testdata/results-9c52c22f17179b9bd5cb2621c05ec3a931adcb02"
)
OUTPUT_DIR = Path("depictio/projects/reference/ampliseq")

# Create output directory if it doesn't exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Use all samples from test dataset (no filtering)
SAMPLE_FILTER = None

# Use habitat as condition column (based on ANCOM category)
CONDITION_COLUMN_NAME = "habitat"


def process_faith_pd(
    input_dir: Path, output_dir: Path, sample_filter: Optional[list[str]] = None
) -> pd.DataFrame:
    """Process Faith PD alpha diversity data from wide to long format."""
    input_file = input_dir / "qiime2/alpha-rarefaction/faith_pd.csv"
    df = pd.read_csv(input_file)

    if sample_filter is not None:
        df = df[df["sample-id"].isin(sample_filter)]

    df_long = df.melt(id_vars=["sample-id"], var_name="iteration", value_name="faith_pd")

    df_long["depth"] = df_long["iteration"].str.extract(r"depth-(\d+)")[0].astype("Int64")
    df_long["iter"] = df_long["iteration"].str.extract(r"iter-(\d+)")[0].astype("Int64")

    df_modified = df_long.rename(columns={"sample-id": "sample"})
    df_modified = df_modified[["sample", "depth", "iter", "faith_pd"]].dropna()

    output_file = output_dir / "faith_pd_long.tsv"
    df_modified.to_csv(output_file, sep="\t", index=False)
    print(f"✓ Saved Faith PD data: {output_file}")
    print(f"  Shape: {df_modified.shape}, Samples: {df_modified['sample'].nunique()}")

    return df_modified


def process_taxonomy_barplot(
    input_dir: Path,
    output_dir: Path,
    level: int = 2,
    sample_filter: Optional[list[str]] = None,
    condition_col_name: str = "auto",
) -> pd.DataFrame:
    """Process taxonomy barplot data from wide to long format."""
    input_file = input_dir / f"qiime2/barplot/level-{level}.csv"
    df = pd.read_csv(input_file)

    if sample_filter is not None:
        df = df[df["index"].isin(sample_filter)]

    sample_col = df.columns[0]

    metadata_candidates = ["name", "condition_binary", "cycle", "condition", "bio_rep", "habitat"]
    metadata_cols = [col for col in df.columns if col in metadata_candidates]
    n_metadata = len(metadata_cols)

    if n_metadata > 0:
        taxonomy_cols = df.columns[1 : len(df.columns) - n_metadata]
    else:
        taxonomy_cols = df.columns[1:]

    print(f"  Detected {n_metadata} metadata columns: {metadata_cols}")
    print(f"  Detected {len(taxonomy_cols)} taxonomy columns")

    df_samples = df[[sample_col] + list(taxonomy_cols)]

    df_modified = df_samples.melt(id_vars=[sample_col], var_name="taxonomy", value_name="count")

    original_count = len(df_modified)
    df_modified = df_modified.rename(columns={sample_col: "sample"})

    if condition_col_name == "auto":
        condition_col = (
            "condition"
            if "condition" in df.columns
            else ("habitat" if "habitat" in df.columns else None)
        )
    else:
        condition_col = condition_col_name if condition_col_name in df.columns else None

    if condition_col:
        sample_to_condition = df.set_index(sample_col)[condition_col].to_dict()
        df_modified[condition_col] = df_modified["sample"].map(sample_to_condition)
        print(f"  Using '{condition_col}' column for sample grouping")
    else:
        df_modified["habitat"] = None
        print(f"  Warning: Condition column '{condition_col_name}' not found")

    df_modified["Kingdom"] = df_modified["taxonomy"].str.split(";").str[0]
    df_modified["Phylum"] = df_modified["taxonomy"].str.split(";").str[1]

    # Convert count to numeric, handling non-numeric values
    df_modified["count"] = pd.to_numeric(df_modified["count"], errors="coerce")

    metadata_names = set(metadata_candidates)
    df_modified = df_modified[
        (df_modified["taxonomy"].notna())
        & (df_modified["taxonomy"].str.strip() != "")
        & (df_modified["taxonomy"].str.strip() != ";")
        & (df_modified["Kingdom"].notna())
        & (df_modified["Kingdom"].str.strip() != "")
        & (~df_modified["Kingdom"].isin(metadata_names))
        & (df_modified["count"].notna())
        & (df_modified["count"] > 0)
    ].copy()

    filtered_count = original_count - len(df_modified)
    if filtered_count > 0:
        print(f"  Filtered out {filtered_count} invalid taxonomy entries")

    output_file = output_dir / "taxonomy_long.tsv"
    df_modified.to_csv(output_file, sep="\t", index=False)
    print(f"✓ Saved taxonomy data: {output_file}")
    print(f"  Shape: {df_modified.shape}, Samples: {df_modified['sample'].nunique()}")

    return df_modified


def process_ancom_volcano(
    input_dir: Path,
    output_dir: Path,
    category: str = "habitat",
    level: str = "ASV",
    sample_filter: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Process ANCOM results and merge with taxonomy data."""
    ancom_file = input_dir / f"qiime2/ancom/Category-{category}-{level}/data.tsv"
    df_ancom = pd.read_csv(ancom_file, sep="\t")

    tax_file = input_dir / f"qiime2/rel_abundance_tables/rel-table-{level}_with-DADA2-tax.tsv"
    df_tax = pd.read_csv(tax_file, sep="\t")

    if sample_filter is not None:
        metadata_cols = ["ID", "Kingdom", "Phylum", "Class", "Order", "Family", "Genus", "Species"]
        cols_to_keep = [col for col in metadata_cols if col in df_tax.columns]
        cols_to_keep += [col for col in df_tax.columns if col in sample_filter]
        df_tax = df_tax[cols_to_keep]

    df_tax["taxonomy"] = df_tax["Kingdom"] + ";" + df_tax["Phylum"]

    df_modified = df_ancom.merge(
        df_tax[["ID", "taxonomy", "Kingdom", "Phylum"]], left_on="id", right_on="ID", how="left"
    )

    df_modified = df_modified[["id", "taxonomy", "Kingdom", "Phylum", "W", "clr"]].dropna()

    output_file = output_dir / "ancom_volcano.tsv"
    df_modified.to_csv(output_file, sep="\t", index=False)
    print(f"✓ Saved ANCOM volcano data: {output_file}")
    print(f"  Shape: {df_modified.shape}, ASVs: {df_modified['id'].nunique()}")

    return df_modified


def main():
    """Generate all processed TSV files."""
    print(f"Processing AmpliseQ test data from: {INPUT_DIR}")
    print(f"Output directory: {OUTPUT_DIR}\n")

    print("1. Processing Faith PD alpha diversity...")
    df_faith = process_faith_pd(INPUT_DIR, OUTPUT_DIR, SAMPLE_FILTER)

    print("\n2. Processing taxonomy composition...")
    df_taxonomy = process_taxonomy_barplot(
        INPUT_DIR,
        OUTPUT_DIR,
        level=2,
        sample_filter=SAMPLE_FILTER,
        condition_col_name=CONDITION_COLUMN_NAME,
    )

    print("\n3. Processing ANCOM differential abundance...")
    df_ancom = process_ancom_volcano(
        INPUT_DIR, OUTPUT_DIR, category="habitat", level="ASV", sample_filter=SAMPLE_FILTER
    )

    print("\n" + "=" * 60)
    print("Processing complete! Generated files:")
    for f in sorted(OUTPUT_DIR.glob("*.tsv")):
        size_kb = f.stat().st_size / 1024
        print(f"  - {f.name} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
