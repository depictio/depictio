#!/usr/bin/env python
"""
MultiQC Metadata Loader
Extracts metadata from the MultiQC metadata JSON for proper table configuration
"""

import collections
import json
import re
from typing import Any, Callable, Dict, Optional

import pandas as pd
import yaml


def load_multiqc_config_defaults():
    """Load default config values from MultiQC config_defaults.yaml"""
    config_defaults_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/multiqc_latest/multiqc/config_defaults.yaml"

    default_config = {}

    try:
        with open(config_defaults_path, "r") as f:
            default_config = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Warning: Could not load config defaults from YAML: {e}")

    return default_config


def resolve_config_expressions(title: str, config: Dict[str, Any] = None) -> str:
    """Resolve f-string config expressions in metadata titles"""
    if config is None:
        config = load_multiqc_config_defaults()

    # Handle f-string expressions like f'{config.base_count_prefix} Q30 bases'
    if "f'" in title and "config." in title:
        # More precise regex to extract the content inside f-strings
        f_string_pattern = r"f'([^']*?)'"
        match = re.search(f_string_pattern, title)

        if match:
            f_string_content = match.group(1)

            # Extract config variable and surrounding text
            config_pattern = r"(.*?)\{config\.([a-zA-Z_]+)\}(.*)"
            config_match = re.search(config_pattern, f_string_content)

            if config_match:
                prefix_text = config_match.group(1)
                config_var = config_match.group(2)
                suffix_text = config_match.group(3)
                config_value = config.get(config_var, "")

                # If config value is None or empty, use just the suffix text
                if config_value is None or config_value == "":
                    resolved_content = suffix_text.strip()
                else:
                    resolved_content = f"{prefix_text}{config_value}{suffix_text}".strip()

                # Replace the entire f-string with the resolved content
                title = title.replace(match.group(0), resolved_content)

    # Remove any remaining braces and clean up
    title = re.sub(r"[{}]", "", title)
    title = title.strip()

    return title


def apply_modify_function(value, modify_str: str, config: Dict[str, Any] = None):
    """Apply a modify function from metadata to a value.

    Args:
        value: The value to modify
        modify_str: The modify function as a string (e.g., "lambda x: x * 100.0")
        config: Config values to use in the lambda function

    Returns:
        Modified value
    """
    if not modify_str or value is None or pd.isna(value):
        return value

    if config is None:
        config = load_multiqc_config_defaults()

    try:
        # Create a safe namespace with config values
        namespace = {"config": type('Config', (), config), "pd": pd}
        # Evaluate the lambda function
        modify_func = eval(modify_str, namespace)
        # Apply to the value
        return modify_func(value)
    except Exception as e:
        print(f"Warning: Could not apply modify function '{modify_str}': {e}")
        return value


class MultiQCMetadataLoader:
    """Load and process MultiQC metadata for table configuration."""

    def __init__(self, metadata_path: str):
        """Initialize with metadata JSON file path."""
        self.metadata_path = metadata_path
        self.metadata = None
        self.load_metadata()

    def load_metadata(self) -> None:
        """Load metadata from JSON file."""
        with open(self.metadata_path, "r") as f:
            self.metadata = json.load(f)

    def get_all_module_headers(self) -> Dict[str, Dict[str, Any]]:
        """Extract all module general stats headers from metadata."""
        all_headers = collections.defaultdict(dict)
        if not self.metadata:
            return all_headers

        # Iterate through all modules
        for module_name, module_data in self.metadata.items():
            if "general_stats_calls" in module_data and module_data["general_stats_calls"]:
                # Get headers from the first general stats call
                first_call = module_data["general_stats_calls"][0]
                headers = first_call.get("headers", {})
                # Add all headers from this module
                for key, config in headers.items():
                    # Skip if config is not a dictionary (some entries might be strings)
                    if isinstance(config, dict):
                        all_headers[module_name][key] = config

        return all_headers

    def get_column_config(self, column_key: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific column."""
        headers = self.get_all_module_headers()
        return headers.get(column_key, {})

    def get_column_title(self, column_key: str) -> str:
        """Get display title for a column."""
        config = self.get_column_config(column_key)
        return config.get("title", column_key)

    def get_column_description(self, column_key: str) -> str:
        """Get description for a column."""
        config = self.get_column_config(column_key)
        return config.get("description", "")

    def get_column_scale(self, column_key: str) -> str:
        """Get color scale for a column."""
        config = self.get_column_config(column_key)
        return config.get("scale", "Blues")

    def get_column_format(self, column_key: str) -> str:
        """Get format string for a column."""
        config = self.get_column_config(column_key)
        return config.get("format", "{:,.0f}")

    def get_column_suffix(self, column_key: str) -> str:
        """Get suffix for a column."""
        config = self.get_column_config(column_key)
        return config.get("suffix", "")

    def get_column_min_max(self, column_key: str) -> tuple:
        """Get min/max values for a column."""
        config = self.get_column_config(column_key)
        min_val = config.get("min", None)
        max_val = config.get("max", None)
        return (min_val, max_val)

    def is_column_hidden(self, column_key: str) -> bool:
        """Check if column should be hidden by default."""
        config = self.get_column_config(column_key)
        return config.get("hidden", False)

    def get_all_column_mappings(self) -> Dict[str, Dict[str, Any]]:
        """Get complete column mappings with all metadata."""
        headers = self.get_all_module_headers()

        mappings = collections.defaultdict(dict)
        for module_name, module_headers in headers.items():
            # Process all modules, not just fastp
            for column_key, config in module_headers.items():

                    # Resolve config expressions in title
                    title = config.get("title", column_key)
                    resolved_title = resolve_config_expressions(title)

                    # Include modify function if present
                    modify_str = config.get("modify", None)

                    mappings[module_name][column_key] = {
                        "title": resolved_title,
                        "description": config.get("description", ""),
                        "scale": config.get("scale", "Blues"),
                        "format": config.get("format", "{:,.0f}"),
                        "suffix": config.get("suffix", ""),
                        "min": config.get("min", None),
                        "max": config.get("max", None),
                        "hidden": config.get("hidden", False),
                        "modify": modify_str,  # Store modify function as string
                    }
        return mappings



if __name__ == "__main__":
    # Test the metadata loader
    metadata_path = "/Users/tweber/Gits/workspaces/depictio-workspace/depictio/dev/dev-multiqc-parquet/multiqc_metadata_extraction.json"

    loader = MultiQCMetadataLoader(metadata_path)

    mappings = loader.get_all_column_mappings()
    # for key, config in mappings.items():
    #     print(f"{key}: {config}")
