#!/usr/bin/env python3
"""
Depictio Benchmark Dataset Generator
Creates scalable datasets for performance testing and stress analysis
"""

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


class BenchmarkType(Enum):
    LINEAR_SCALE = "linear_scale"
    WIDE_SCHEMA = "wide_schema"
    COMPLEX_JOIN = "complex_join"
    SPARSE_DATA = "sparse_data"


class DataSize(Enum):
    SMALL = "1mb"
    MEDIUM = "10mb"
    LARGE = "100mb"


@dataclass
class BenchmarkConfig:
    """Configuration for benchmark dataset generation"""

    benchmark_type: BenchmarkType
    data_size: DataSize
    target_rows: int
    runs_per_species: int
    species_distribution: Dict[str, float]
    additional_columns: Optional[Dict[str, List[str]]] = None
    missing_data_ratio: float = 0.0
    duplicate_ratio: float = 0.0


class BenchmarkDatasetGenerator:
    """Generates benchmark datasets for Depictio stress testing"""

    def __init__(self, output_base_dir: str = "benchmark_datasets"):
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(exist_ok=True)

        # Species characteristics for realistic data generation
        self.species_profiles = {
            "Adelie": {
                "bill_length_range": (32.1, 46.0),
                "bill_depth_range": (15.5, 21.5),
                "flipper_length_range": (172, 210),
                "body_mass_range": (2850, 4775),
                "islands": ["Torgersen", "Biscoe", "Dream"],
                "years": range(2007, 2024),
            },
            "Gentoo": {
                "bill_length_range": (40.9, 59.6),
                "bill_depth_range": (13.1, 17.3),
                "flipper_length_range": (203, 231),
                "body_mass_range": (3950, 6300),
                "islands": ["Biscoe"],
                "years": range(2007, 2024),
            },
            "Chinstrap": {
                "bill_length_range": (40.9, 58.0),
                "bill_depth_range": (16.4, 20.8),
                "flipper_length_range": (178, 212),
                "body_mass_range": (2700, 4800),
                "islands": ["Dream"],
                "years": range(2007, 2024),
            },
        }

    def generate_benchmark_suite(self):
        """Generate complete benchmark dataset suite"""
        print("🚀 Generating Depictio Benchmark Dataset Suite")
        print("=" * 60)

        # Generate all combinations
        configs = self._create_benchmark_configs()

        for config in configs:
            print(f"\n📊 Generating {config.benchmark_type.value}_{config.data_size.value}")
            self._generate_single_benchmark(config)

        self._generate_project_configs()
        print("\n✅ Benchmark suite generation complete!")

    def _create_benchmark_configs(self) -> List[BenchmarkConfig]:
        """Create all benchmark configurations"""
        configs = []

        # Row count targets (based on ~54 bytes per row)
        size_targets = {
            DataSize.SMALL: 19_526,  # ~1MB
            DataSize.MEDIUM: 195_265,  # ~10MB
            DataSize.LARGE: 1_952_655,  # ~100MB
        }

        species_dist = {"Adelie": 0.65, "Gentoo": 0.25, "Chinstrap": 0.10}

        for benchmark_type in BenchmarkType:
            for data_size in DataSize:
                target_rows = size_targets[data_size]
                runs_per_species = max(1, target_rows // (10_000 * len(species_dist)))

                config = BenchmarkConfig(
                    benchmark_type=benchmark_type,
                    data_size=data_size,
                    target_rows=target_rows,
                    runs_per_species=runs_per_species,
                    species_distribution=species_dist,
                )

                # Customize based on benchmark type
                if benchmark_type == BenchmarkType.WIDE_SCHEMA:
                    config.additional_columns = self._get_wide_schema_columns()
                elif benchmark_type == BenchmarkType.SPARSE_DATA:
                    config.missing_data_ratio = 0.25
                    config.duplicate_ratio = 0.05

                configs.append(config)

        return configs

    def _get_wide_schema_columns(self) -> Dict[str, List[str]]:
        """Define additional columns for wide schema benchmarks"""
        return {
            "physical_features": [
                "wing_span_mm",
                "tail_length_mm",
                "head_circumference_mm",
                "foot_length_mm",
                "beak_angle_deg",
                "weight_fat_ratio",
                "feather_density",
                "swim_speed_ms",
                "dive_depth_m",
                "metabolic_rate",
                "heart_rate_bpm",
                "body_temp_c",
            ],
            "demographic_data": [
                "nest_location_x",
                "nest_location_y",
                "clutch_size",
                "incubation_days",
                "fledging_success",
                "parent_id_male",
                "parent_id_female",
                "territory_size_m2",
                "mate_fidelity_score",
                "offspring_count",
                "breeding_experience_years",
                "dominance_rank",
            ],
        }

    def _generate_single_benchmark(self, config: BenchmarkConfig):
        """Generate a single benchmark dataset"""
        dataset_dir = (
            self.output_base_dir / f"{config.benchmark_type.value}_{config.data_size.value}"
        )
        dataset_dir.mkdir(exist_ok=True)

        # Calculate rows per species
        rows_per_species = {}
        for species, ratio in config.species_distribution.items():
            rows_per_species[species] = int(config.target_rows * ratio)

        # Generate data for each species
        for species, target_rows in rows_per_species.items():
            self._generate_species_runs(species, target_rows, config, dataset_dir)

    def _generate_species_runs(
        self, species: str, target_rows: int, config: BenchmarkConfig, dataset_dir: Path
    ):
        """Generate multiple runs for a species to reach target row count"""
        rows_per_run = max(1, target_rows // config.runs_per_species)

        for run_idx in range(config.runs_per_species):
            run_name = f"run_{run_idx + 1}_{species.lower()}"
            run_dir = dataset_dir / run_name
            run_dir.mkdir(exist_ok=True)

            # Determine actual rows for this run
            remaining_rows = target_rows - (run_idx * rows_per_run)
            actual_rows = min(rows_per_run, remaining_rows)

            if actual_rows <= 0:
                continue

            # Generate physical features
            physical_df = self._generate_physical_features(species, actual_rows, config, run_idx)

            # Generate demographic data
            demographic_df = self._generate_demographic_data(
                species, actual_rows, config, run_idx, physical_df["individual_id"]
            )

            # Apply data quality issues if needed
            if config.missing_data_ratio > 0:
                physical_df = self._introduce_missing_data(physical_df, config.missing_data_ratio)
                demographic_df = self._introduce_missing_data(
                    demographic_df, config.missing_data_ratio
                )

            # Save files
            physical_df.to_csv(run_dir / "physical_features.csv", index=False)
            demographic_df.to_csv(run_dir / "demographic_data.csv", index=False)

            print(f"  ✅ Generated {run_name}: {actual_rows} rows")

    def _generate_physical_features(
        self, species: str, num_rows: int, config: BenchmarkConfig, run_idx: int
    ) -> pd.DataFrame:
        """Generate physical features data for a species"""
        profile = self.species_profiles[species]

        # Base columns
        data = {
            "individual_id": [f"{species[:3].upper()}_{run_idx}_{i:06d}" for i in range(num_rows)]
        }

        # Generate realistic measurements with some variance
        np.random.seed(42 + run_idx)  # Reproducible but varied

        data["bill_length_mm"] = np.random.uniform(
            profile["bill_length_range"][0], profile["bill_length_range"][1], num_rows
        ).round(1)

        data["bill_depth_mm"] = np.random.uniform(
            profile["bill_depth_range"][0], profile["bill_depth_range"][1], num_rows
        ).round(1)

        data["flipper_length_mm"] = (
            np.random.uniform(
                profile["flipper_length_range"][0], profile["flipper_length_range"][1], num_rows
            )
            .round(0)
            .astype(int)
        )

        data["body_mass_g"] = (
            np.random.uniform(
                profile["body_mass_range"][0], profile["body_mass_range"][1], num_rows
            )
            .round(0)
            .astype(int)
        )

        # Add wide schema columns if needed
        if (
            config.benchmark_type == BenchmarkType.WIDE_SCHEMA
            and config.additional_columns
            and "physical_features" in config.additional_columns
        ):
            for col in config.additional_columns["physical_features"]:
                data[col] = self._generate_additional_column_data(col, num_rows)

        return pd.DataFrame(data)

    def _generate_demographic_data(
        self,
        species: str,
        num_rows: int,
        config: BenchmarkConfig,
        run_idx: int,
        individual_ids: List[str],
    ) -> pd.DataFrame:
        """Generate demographic data for a species"""
        profile = self.species_profiles[species]

        np.random.seed(42 + run_idx + 1000)  # Different seed than physical

        data = {"individual_id": list(individual_ids)}

        data["island"] = np.random.choice(profile["islands"], num_rows)
        data["sex"] = np.random.choice(["male", "female", ""], num_rows, p=[0.45, 0.45, 0.1])
        data["year"] = np.random.choice(list(profile["years"]), num_rows)
        data["species"] = [species] * num_rows

        # Add wide schema columns if needed
        if (
            config.benchmark_type == BenchmarkType.WIDE_SCHEMA
            and config.additional_columns
            and "demographic_data" in config.additional_columns
        ):
            for col in config.additional_columns["demographic_data"]:
                data[col] = self._generate_additional_column_data(col, num_rows)

        return pd.DataFrame(data)

    def _generate_additional_column_data(self, column_name: str, num_rows: int):
        """Generate synthetic data for additional columns"""
        # Pattern-based data generation
        if "mm" in column_name:
            return np.random.uniform(10, 200, num_rows).round(1)
        elif "ratio" in column_name:
            return np.random.uniform(0.1, 2.0, num_rows).round(3)
        elif "speed" in column_name:
            return np.random.uniform(0.5, 15.0, num_rows).round(2)
        elif "temp" in column_name:
            return np.random.uniform(35.0, 42.0, num_rows).round(1)
        elif "rate" in column_name:
            return np.random.uniform(80, 200, num_rows).round(0).astype(int)
        elif "success" in column_name:
            return np.random.choice([True, False], num_rows, p=[0.7, 0.3])
        elif "size" in column_name or "count" in column_name:
            return np.random.randint(1, 10, num_rows)
        elif "location" in column_name:
            return np.random.uniform(-180, 180, num_rows).round(6)
        elif "id" in column_name:
            return [f"REF_{i:08d}" for i in range(num_rows)]
        else:
            return np.random.uniform(0, 100, num_rows).round(2)

    def _introduce_missing_data(self, df: pd.DataFrame, missing_ratio: float) -> pd.DataFrame:
        """Introduce missing data patterns"""
        df_copy = df.copy()

        # Don't introduce missing data in ID columns
        id_columns = [col for col in df.columns if "id" in col.lower()]
        data_columns = [col for col in df.columns if col not in id_columns]

        # Randomly introduce NaN values
        for col in data_columns:
            mask = np.random.random(len(df)) < missing_ratio
            df_copy.loc[mask, col] = np.nan

        return df_copy

    def _generate_static_id(
        self, id_type: str, benchmark_type: str, data_size: Optional[str] = None
    ) -> str:
        """Generate a static, predictable ID for reusability across benchmark runs

        Note: data_size parameter is ignored to ensure same IDs across different sizes
        within the same benchmark category
        """
        import hashlib

        # Create a deterministic hash from benchmark type only (ignore data_size)
        input_string = f"benchmark_{id_type}_{benchmark_type}"
        hash_object = hashlib.md5(input_string.encode())
        hash_hex = hash_object.hexdigest()

        # Format as MongoDB ObjectId-like string (24 hex characters)
        static_id = hash_hex[:24]

        return static_id

    def _generate_project_configs(self):
        """Generate YAML configuration files for each benchmark"""
        print("\n📝 Generating project configuration files...")

        # Generate ID mapping for reference
        id_mapping = {}

        for benchmark_type in BenchmarkType:
            for data_size in DataSize:
                dataset_name = f"{benchmark_type.value}_{data_size.value}"

                # Generate IDs for this configuration
                project_id = self._generate_static_id(
                    "project", benchmark_type.value, data_size.value
                )
                workflow_id = self._generate_static_id(
                    "workflow", benchmark_type.value, data_size.value
                )
                physical_dc_id = self._generate_static_id(
                    "dc_physical", benchmark_type.value, data_size.value
                )
                demographic_dc_id = self._generate_static_id(
                    "dc_demo", benchmark_type.value, data_size.value
                )

                id_mapping[dataset_name] = {
                    "project_id": project_id,
                    "workflow_id": workflow_id,
                    "physical_dc_id": physical_dc_id,
                    "demographic_dc_id": demographic_dc_id,
                }

                self._create_project_yaml(benchmark_type, data_size)

        # Save ID mapping for reference
        self._save_id_mapping(id_mapping)

    def _save_id_mapping(self, id_mapping: Dict):
        """Save ID mapping to a JSON file for easy reference"""
        import json

        mapping_file = self.output_base_dir / "benchmark_id_mapping.json"
        with open(mapping_file, "w") as f:
            json.dump(id_mapping, f, indent=2)

        print(f"  ✅ Created ID mapping: {mapping_file}")
        print("\n📋 Static ID Summary:")
        for dataset, ids in id_mapping.items():
            print(f"  {dataset}:")
            print(f"    Project: {ids['project_id']}")
            print(f"    Workflow: {ids['workflow_id']}")
            print(f"    Physical DC: {ids['physical_dc_id']}")
            print(f"    Demo DC: {ids['demographic_dc_id']}")

    def _create_project_yaml(self, benchmark_type: BenchmarkType, data_size: DataSize):
        """Create a project YAML file for a benchmark"""
        dataset_name = f"{benchmark_type.value}_{data_size.value}"

        # Generate static IDs based on benchmark type and size for reusability
        project_id = self._generate_static_id("project", benchmark_type.value, data_size.value)
        workflow_id = self._generate_static_id("workflow", benchmark_type.value, data_size.value)
        physical_dc_id = self._generate_static_id(
            "dc_physical", benchmark_type.value, data_size.value
        )
        demographic_dc_id = self._generate_static_id(
            "dc_demo", benchmark_type.value, data_size.value
        )

        yaml_content = f'''# Depictio Benchmark Dataset: {dataset_name.title()}
name: "Depictio Benchmark - {dataset_name.replace("_", " ").title()}"
project_type: "advanced"
id: "{project_id}"
workflows:
  - name: "{dataset_name}_analysis"
    id: "{workflow_id}"
    engine:
      name: "python"
      version: "3.11"
    description: "Benchmark analysis for {dataset_name} - stress testing {data_size.value.upper()} data volumes"
    data_location:
      structure: "sequencing-runs"
      runs_regex: "run_*"
      locations:
        - ../api/v1/configs/benchmark_datasets/{dataset_name}
    data_collections:
      # Physical features dataset
      - data_collection_tag: "physical_features"
        id: "{physical_dc_id}"
        description: "Physical characteristics measurements - {benchmark_type.value} benchmark"
        config:
          type: "Table"
          metatype: "Aggregate"
          scan:
            mode: "recursive"
            scan_parameters:
              regex_config:
                pattern: "physical_features.csv"
          dc_specific_properties:
            format: "CSV"
            polars_kwargs:
              separator: ","
            columns_description:
              individual_id: "Unique individual penguin ID within species"
              bill_length_mm: "Bill length in millimeters"
              bill_depth_mm: "Bill depth in millimeters"
              flipper_length_mm: "Flipper length in millimeters"
              body_mass_g: "Body mass in grams"'''

        # Add wide schema column descriptions if applicable
        if benchmark_type == BenchmarkType.WIDE_SCHEMA:
            wide_cols = self._get_wide_schema_columns()["physical_features"]
            for col in wide_cols:
                yaml_content += f'''
              {col}: "Generated {col.replace("_", " ").title()}"'''

        yaml_content += f'''
          join:
            on_columns:
              - individual_id
            how: "inner"
            with_dc:
              - "demographic_data"

      # Demographic data
      - data_collection_tag: "demographic_data"
        data_collection_id: "{demographic_dc_id}"
        description: "Location and demographic information - {benchmark_type.value} benchmark"
        config:
          type: "Table"
          metatype: "Aggregate"
          scan:
            mode: "recursive"
            scan_parameters:
              regex_config:
                pattern: "demographic_data.csv"
          dc_specific_properties:
            format: "CSV"
            polars_kwargs:
              separator: ","
            columns_description:
              individual_id: "Unique individual penguin ID within species"
              island: "Island location"
              sex: "Penguin sex"
              year: "Observation year"
              species: "Species name"'''

        # Add wide schema column descriptions if applicable
        if benchmark_type == BenchmarkType.WIDE_SCHEMA:
            wide_cols = self._get_wide_schema_columns()["demographic_data"]
            for col in wide_cols:
                yaml_content += f'''
              {col}: "Generated {col.replace("_", " ").title()}"'''

        # Save YAML file
        yaml_path = self.output_base_dir / f"{dataset_name}_project.yaml"
        with open(yaml_path, "w") as f:
            f.write(yaml_content)

        print(f"  ✅ Created {yaml_path}")


def main():
    """Main execution function"""
    print("🐧 Depictio Benchmark Dataset Generator")
    print("=" * 50)

    if len(sys.argv) > 1:
        output_dir = sys.argv[1]
    else:
        output_dir = "benchmark_datasets"

    generator = BenchmarkDatasetGenerator(output_dir)
    generator.generate_benchmark_suite()

    print(f"\n🎯 Benchmark datasets generated in: {output_dir}/")
    print("\n📊 Generated benchmark scenarios:")
    print("  • Linear Scale: 1MB, 10MB, 100MB (volume testing)")
    print("  • Wide Schema: Extended columns (memory pressure)")
    print("  • Complex Join: Multi-table relationships (join complexity)")
    print("  • Sparse Data: Missing values and data quality issues")
    print("\n🚀 Ready for Depictio stress testing!")


if __name__ == "__main__":
    main()
