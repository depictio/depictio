#!/usr/bin/env python3
"""
Palmer Penguins Dataset Processor for Depictio
Downloads penguins data and splits it into separate files per species
"""

import os

import pandas as pd
import requests


def download_penguins_data():
    """Download the penguins dataset from GitHub"""
    url = "https://raw.githubusercontent.com/allisonhorst/palmerpenguins/master/inst/extdata/penguins.csv"

    print("📥 Downloading Palmer Penguins dataset...")
    try:
        response = requests.get(url)
        response.raise_for_status()

        # Save raw data
        with open("penguins_raw.csv", "w") as f:
            f.write(response.text)

        print("✅ Dataset downloaded successfully!")
        return pd.read_csv("penguins_raw.csv")

    except Exception as e:
        print(f"❌ Error downloading data: {e}")
        return None


def create_directory_structure():
    """Create the directory structure for Depictio"""
    base_dir = "depictio/api/v1/configs/penguins_dataset"

    # Create main directory
    os.makedirs(base_dir, exist_ok=True)

    # Create run directories for each species
    species_dirs = {
        "Adelie": f"{base_dir}/run_1_adelie",
        "Chinstrap": f"{base_dir}/run_2_chinstrap",
        "Gentoo": f"{base_dir}/run_3_gentoo",
    }

    for species, dir_path in species_dirs.items():
        os.makedirs(dir_path, exist_ok=True)
        print(f"📁 Created directory: {dir_path}")

    return base_dir, species_dirs


def add_depictio_metadata(df, species_name, run_id):
    """Keep data as-is, no additional columns needed"""
    # Just return the dataframe as-is, Depictio handles metadata automatically
    return df.copy()


def process_and_split_data(df, base_dir, species_dirs):
    """Process data and split by species into separate files"""

    print("\n🔄 Processing and splitting data by species...")

    # Get unique species
    species_list = df["species"].unique()
    print(f"Found species: {species_list}")

    for i, species in enumerate(species_list, 1):
        if pd.isna(species):
            continue

        print(f"\n📊 Processing {species} penguins...")

        # Filter data for this species
        species_data = df[df["species"] == species].copy()

        # Remove rows with missing critical data
        species_data = species_data.dropna(
            subset=["bill_length_mm", "bill_depth_mm", "flipper_length_mm"]
        )

        # Add individual ID column (row number within species with "ID" as prefix)
        # species_data['individual_id'] = range(1, len(species_data) + 1)
        species_data["individual_id"] = [f"ID_{i}" for i in range(1, len(species_data) + 1)]

        # Add metadata
        run_id = f"run_{i}_{species.lower()}"
        species_data = add_depictio_metadata(species_data, species, run_id)

        # Determine output directory
        species_key = species  # Adelie, Chinstrap, Gentoo
        if species_key in species_dirs:
            output_dir = species_dirs[species_key]
        else:
            # Fallback directory
            output_dir = f"{base_dir}/data/run_{i}_{species.lower()}"
            os.makedirs(output_dir, exist_ok=True)

        # Save main measurements file
        measurements_file = f"{output_dir}/penguin_measurements.csv"
        species_data.to_csv(measurements_file, index=False)
        print(f"  ✅ Saved measurements: {measurements_file} ({len(species_data)} records)")

        # Create additional files for multi-file structure

        # Create additional files for multi-file structure

        # 1. Physical characteristics only
        physical_cols = [
            "individual_id",
            "bill_length_mm",
            "bill_depth_mm",
            "flipper_length_mm",
            "body_mass_g",
        ]
        physical_data = species_data[physical_cols].copy()
        physical_file = f"{output_dir}/physical_features.csv"
        print(physical_data)
        physical_data.to_csv(physical_file, index=False)
        print(f"  ✅ Saved physical features: {physical_file}")

        # 2. Location and demographic data
        demo_cols = ["individual_id", "island", "sex", "year", "species"]
        demo_data = species_data[demo_cols].copy()
        demo_file = f"{output_dir}/demographic_data.csv"
        print(demo_data)
        demo_data.to_csv(demo_file, index=False)
        print(f"  ✅ Saved demographic data: {demo_file}")

    print("\n🎉 Data processing complete!")


def create_depictio_config(base_dir):
    """Note: Config is now in separate YAML file"""
    print("📝 Use the separate depictio_config.yaml file for configuration")


def main():
    """Main function to orchestrate the entire process"""

    print("🐧 Palmer Penguins Dataset Processor for Depictio")
    print("=" * 50)

    # Step 1: Download data
    df = download_penguins_data()
    if df is None:
        return

    print(f"📊 Dataset loaded: {len(df)} records, {len(df.columns)} columns")
    print(f"Species found: {df['species'].value_counts().to_dict()}")

    # Step 2: Create directory structure
    base_dir, species_dirs = create_directory_structure()

    # Step 3: Process and split data
    process_and_split_data(df, base_dir, species_dirs)

    # Step 4: Create Depictio configuration
    create_depictio_config(base_dir)

    # Step 5: Create summary
    print("\n📁 Final directory structure:")
    for root, dirs, files in os.walk(base_dir):
        level = root.replace(base_dir, "").count(os.sep)
        indent = " " * 2 * level
        print(f"{indent}{os.path.basename(root)}/")
        subindent = " " * 2 * (level + 1)
        for file in files:
            print(f"{subindent}{file}")

    print("\n✅ Setup complete!")
    print(f"🎯 Your Depictio project is ready in: {base_dir}/")
    print(f"📊 Data files: {base_dir}/")

    print("\n🚀 To use with Depictio:")
    print("   Use the separate depictio_config.yaml file")
    print("   Point it to: /app/depictio/api/v1/configs/penguins_dataset")


if __name__ == "__main__":
    main()
