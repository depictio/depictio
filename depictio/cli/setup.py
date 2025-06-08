#!/usr/bin/env python
import os
import re

import tomli
from setuptools import setup


def get_version_from_main_pyproject():
    """Read the version from the main pyproject.toml file"""
    # Look for the pyproject.toml in the parent directory of the parent directory
    main_pyproject_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "pyproject.toml"
    )

    try:
        with open(main_pyproject_path, "rb") as f:
            pyproject_data = tomli.load(f)
            return pyproject_data.get("project", {}).get("version", "0.0.1")
    except Exception as e:
        print(f"Warning: Could not read version from main pyproject.toml: {e}")
        return "0.0.1"


# Update the version in the CLI's pyproject.toml
def update_cli_pyproject_version(version):
    """Update the version in the CLI's pyproject.toml file"""
    cli_pyproject_path = os.path.join(os.path.dirname(__file__), "pyproject.toml")

    try:
        # Read the current content
        with open(cli_pyproject_path) as f:
            content = f.read()

        # Replace the version
        updated_content = re.sub(r'version\s*=\s*"[^"]+"', f'version = "{version}"', content)

        # Write back the updated content
        with open(cli_pyproject_path, "w") as f:
            f.write(updated_content)

        print(f"Updated CLI pyproject.toml version to {version}")
    except Exception as e:
        print(f"Warning: Could not update CLI pyproject.toml version: {e}")


if __name__ == "__main__":
    version = get_version_from_main_pyproject()
    update_cli_pyproject_version(version)
    setup()
