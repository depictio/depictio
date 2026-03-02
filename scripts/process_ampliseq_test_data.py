#!/usr/bin/env python3
"""
Process AmpliseQ test data for depictio demo dataset.

This script generates the processed TSV files needed for the ampliseq project:
- faith_pd_long.tsv: Alpha diversity rarefaction data
- taxonomy_long.tsv: Taxonomic composition at Phylum level
- ancom_volcano.tsv: Differential abundance results
- taxonomy_heatmap.tsv: Wide-format taxonomy matrix for ComplexHeatmap
- merged_metadata.tsv: Updated with fictitious lat/lon coordinates
"""

import numpy as np
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
OUTPUT_DIR = Path("depictio/projects/nf-core/ampliseq/2.14.0")

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


def process_taxonomy_heatmap(output_dir: Path) -> pd.DataFrame:
    """Pivot long-format taxonomy_rel_abundance into wide format for ComplexHeatmap.

    Reads taxonomy_rel_abundance_long.tsv (already generated), pivots to:
    rows = Phylum, columns = sample IDs, values = mean rel_abundance.
    Keeps Kingdom column as row annotation.
    Filters out Unclassified phyla and zero-sum rows.
    """
    input_file = output_dir / "taxonomy_rel_abundance_long.tsv"
    df = pd.read_csv(input_file, sep="\t")

    # Filter out Unclassified phyla and empty values
    df = df[
        (df["Phylum"].notna())
        & (df["Phylum"].str.strip() != "")
        & (df["Phylum"] != "Unclassified")
    ].copy()

    # Aggregate: mean rel_abundance per sample × Phylum
    df_agg = df.groupby(["Phylum", "Kingdom", "sample"])["rel_abundance"].mean().reset_index()

    # Pivot to wide format: Phylum rows × sample columns
    df_wide = df_agg.pivot(index="Phylum", columns="sample", values="rel_abundance").fillna(0)

    # Get Kingdom annotation per Phylum
    kingdom_map = df_agg.drop_duplicates("Phylum").set_index("Phylum")["Kingdom"]
    df_wide.insert(0, "Kingdom", df_wide.index.map(kingdom_map))

    # Filter out zero-sum rows
    sample_cols = [c for c in df_wide.columns if c != "Kingdom"]
    row_sums = df_wide[sample_cols].sum(axis=1)
    df_wide = df_wide[row_sums > 0]

    # Reset index so Phylum is a column
    df_wide = df_wide.reset_index()

    output_file = output_dir / "taxonomy_heatmap.tsv"
    df_wide.to_csv(output_file, sep="\t", index=False)
    print(f"✓ Saved taxonomy heatmap data: {output_file}")
    print(f"  Shape: {df_wide.shape} (Phyla × samples)")

    return df_wide


def add_coordinates_to_metadata(output_dir: Path) -> pd.DataFrame:
    """Add fictitious lat/lon coordinates and city to merged_metadata.tsv.

    Assigns each sample to a German city with coordinates. Different habitat
    types are spread across multiple cities (not 1:1 habitat→city mapping).
    """
    metadata_file = output_dir / "merged_metadata.tsv"
    df = pd.read_csv(metadata_file, sep="\t")

    # City coordinates (German environmental sampling sites)
    city_coords = {
        "Frankfurt": (50.11, 8.68),
        "Munich": (48.14, 11.58),
        "Cuxhaven": (53.87, 8.70),
        "Berlin": (52.52, 13.40),
        "Hamburg": (53.55, 9.99),
        "Cologne": (50.94, 6.96),
    }

    # Per-sample city assignment: habitats are spread across cities
    # (not same habitat → same city)
    sample_city = {
        "SRR10070130": "Frankfurt",   # Riverwater
        "SRR10070131": "Hamburg",      # Riverwater
        "SRR10070132": "Munich",       # Groundwater
        "SRR10070133": "Berlin",       # Groundwater
        "SRR10070134": "Cologne",      # Riverwater
        "SRR10070141": "Frankfurt",    # Groundwater
        "SRR10070149": "Cuxhaven",     # Sediment
        "SRR10070150": "Hamburg",      # Sediment
        "SRR10070151": "Berlin",       # Sediment
        "SRR10102392": "Munich",       # Soil
        "SRR10102393": "Cologne",      # Soil
        "SRR10102394": "Cuxhaven",     # Soil
    }

    # Use fixed seed for reproducibility
    rng = np.random.default_rng(seed=42)

    cities = []
    latitudes = []
    longitudes = []
    for _, row in df.iterrows():
        city = sample_city.get(row["sample"], "Berlin")
        base_lat, base_lon = city_coords[city]
        # ±0.03° jitter (~3km) for visual separation
        lat = base_lat + rng.uniform(-0.03, 0.03)
        lon = base_lon + rng.uniform(-0.03, 0.03)
        cities.append(city)
        latitudes.append(round(lat, 6))
        longitudes.append(round(lon, 6))

    df["city"] = cities
    df["latitude"] = latitudes
    df["longitude"] = longitudes

    df.to_csv(metadata_file, sep="\t", index=False)
    print(f"✓ Updated metadata with coordinates: {metadata_file}")
    print(f"  Added columns: city, latitude, longitude")

    return df


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

    print("\n4. Processing taxonomy heatmap (wide format)...")
    df_heatmap = process_taxonomy_heatmap(OUTPUT_DIR)

    print("\n5. Adding coordinates to metadata...")
    df_metadata = add_coordinates_to_metadata(OUTPUT_DIR)

    print("\n" + "=" * 60)
    print("Processing complete! Generated files:")
    for f in sorted(OUTPUT_DIR.glob("*.tsv")):
        size_kb = f.stat().st_size / 1024
        print(f"  - {f.name} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
