#!/usr/bin/env python3
"""
Depictio Example Project Generator

This script creates an example Depictio project with a minimal configuration
and sample data files. It demonstrates how to set up a project with a single
workflow and a single data collection.
"""

import os
import json
import argparse
import random
import csv
from pathlib import Path
import shutil


def create_directory_structure(base_dir):
    """Create the directory structure for the example project."""
    print(f"Creating directory structure in {base_dir}...")

    # Create main directories
    os.makedirs(os.path.join(base_dir, "data", "example_workflow"), exist_ok=True)

    # Create a runs directory with a sample run
    run_dir = os.path.join(base_dir, "data", "example_workflow", "run1")
    os.makedirs(run_dir, exist_ok=True)

    return run_dir


def create_sample_data(run_dir):
    """Create sample TSV files for the example workflow."""
    print(f"Creating sample data files in {run_dir}...")

    # Create a few sample stats TSV files
    sample_files = ["sample1.stats.tsv", "sample2.stats.tsv", "sample3.stats.tsv"]

    # Sample headers and data for stats files
    headers = ["metric", "value", "description"]
    metrics = [
        ["total_reads", random.randint(1000000, 10000000), "Total number of reads"],
        ["mapped_reads", random.randint(800000, 9000000), "Number of mapped reads"],
        ["unmapped_reads", random.randint(10000, 1000000), "Number of unmapped reads"],
        ["duplicate_reads", random.randint(5000, 500000), "Number of duplicate reads"],
        ["average_quality", round(random.uniform(30, 40), 2), "Average base quality"],
        ["gc_content", round(random.uniform(0.4, 0.6), 2), "GC content"],
        ["average_read_length", random.randint(100, 150), "Average read length"],
    ]

    # Create each sample file
    for sample_file in sample_files:
        file_path = os.path.join(run_dir, sample_file)
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(headers)
            for metric in metrics:
                # Add some variation to the values for each sample
                varied_metric = [
                    metric[0],
                    metric[1] * random.uniform(0.9, 1.1)
                    if isinstance(metric[1], (int, float))
                    else metric[1],
                    metric[2],
                ]
                writer.writerow(varied_metric)

    return sample_files


def create_config_file(base_dir, user_home_dir=None):
    """Create the Depictio project configuration file."""
    print(f"Creating project configuration file...")

    # Use the user's home directory if provided, otherwise use a placeholder
    if user_home_dir:
        data_path = os.path.join(user_home_dir, "data", "example_workflow")
    else:
        data_path = "/home/user/data/example_workflow"

    # Create the configuration dictionary
    config = {
        "name": "Example project",
        "workflows": [
            {
                "name": "example_workflow",
                "engine": {"name": "python"},
                "config": {"parent_runs_location": [data_path], "runs_regex": ".*"},
                "data_collections": [
                    {
                        "data_collection_tag": "example_data_collection",
                        "config": {
                            "type": "Table",
                            "metatype": "Aggregate",
                            "scan": {
                                "mode": "recursive",
                                "scan_parameters": {"regex_config": {"pattern": "*.stats.tsv"}},
                            },
                            "dc_specific_properties": {
                                "format": "TSV",
                                "polars_kwargs": {"separator": "\t"},
                            },
                        },
                    }
                ],
            }
        ],
    }

    # Write the configuration to a YAML file
    config_path = os.path.join(base_dir, "depictio_config.yaml")

    # Convert the config to YAML format manually
    yaml_content = f"""name: "{config["name"]}"
# Workflows section
workflows:
  - name: "{config["workflows"][0]["name"]}"
    engine:
      name: "{config["workflows"][0]["engine"]["name"]}"
    config:
      parent_runs_location:
        - "{config["workflows"][0]["config"]["parent_runs_location"][0]}"
      runs_regex: "{config["workflows"][0]["config"]["runs_regex"]}"
    # Data collections section
    data_collections:
      - data_collection_tag: "{config["workflows"][0]["data_collections"][0]["data_collection_tag"]}"
        config:
          type: "{config["workflows"][0]["data_collections"][0]["config"]["type"]}"
          metatype: "{config["workflows"][0]["data_collections"][0]["config"]["metatype"]}"
          scan:
            mode: {config["workflows"][0]["data_collections"][0]["config"]["scan"]["mode"]}
            scan_parameters:
              regex_config:
                pattern: "{config["workflows"][0]["data_collections"][0]["config"]["scan"]["scan_parameters"]["regex_config"]["pattern"]}"
          dc_specific_properties:
            format: "{config["workflows"][0]["data_collections"][0]["config"]["dc_specific_properties"]["format"]}"
            polars_kwargs:
              separator: "{config["workflows"][0]["data_collections"][0]["config"]["dc_specific_properties"]["polars_kwargs"]["separator"]}"
"""

    with open(config_path, "w") as f:
        f.write(yaml_content)

    return config_path


def create_readme(base_dir, config_path):
    """Create a README file with instructions."""
    print(f"Creating README file...")

    readme_content = f"""# Depictio Example Project

This is an example project for Depictio, demonstrating a minimal configuration with a single workflow and data collection.

## Project Structure

```
.
├── data/
│   └── example_workflow/
│       └── run1/
│           ├── sample1.stats.tsv
│           ├── sample2.stats.tsv
│           └── sample3.stats.tsv
├── depictio_config.yaml
└── README.md
```

## Configuration

The project configuration is defined in `depictio_config.yaml`. It includes:

- A project name
- A single workflow named "example_workflow"
- A single data collection that processes TSV files matching the pattern "*.stats.tsv"

## Using with Depictio CLI

To use this project with Depictio CLI, follow these steps:

1. Make sure you have Depictio CLI installed and configured
2. Run the following command to register the project:

```bash
depictio config create --cli-config /path/to/cli_config.yaml --project-config {os.path.basename(config_path)}
```

3. Once registered, you can access the project through the Depictio web interface

## Data Collection

The example data collection is configured to:

- Scan recursively for files matching the pattern "*.stats.tsv"
- Parse them as TSV files with tab separators
- Aggregate the data for analysis

## Customizing

You can customize this example by:

1. Adding more sample data files
2. Modifying the configuration to include additional workflows or data collections
3. Changing the scan pattern to match different file types
"""

    readme_path = os.path.join(base_dir, "README.md")
    with open(readme_path, "w") as f:
        f.write(readme_content)

    return readme_path


def main():
    """Main function to create the example project."""
    parser = argparse.ArgumentParser(description="Create an example Depictio project")
    parser.add_argument(
        "--output",
        "-o",
        default="depictio_example_project",
        help="Output directory for the example project",
    )
    parser.add_argument(
        "--home", default=None, help="User home directory to use in the configuration"
    )
    args = parser.parse_args()

    # Create the base directory
    base_dir = os.path.abspath(args.output)
    if os.path.exists(base_dir):
        print(f"Warning: Directory {base_dir} already exists. Files may be overwritten.")
    else:
        os.makedirs(base_dir)

    # Create the project structure and files
    run_dir = create_directory_structure(base_dir)
    sample_files = create_sample_data(run_dir)
    config_path = create_config_file(base_dir, args.home)
    readme_path = create_readme(base_dir, config_path)

    print("\nExample project created successfully!")
    print(f"Project directory: {base_dir}")
    print(f"Configuration file: {config_path}")
    print(f"Sample data files: {', '.join(sample_files)}")
    print(f"README: {readme_path}")
    print("\nTo use this project with Depictio CLI, follow the instructions in the README.md file.")


if __name__ == "__main__":
    main()
