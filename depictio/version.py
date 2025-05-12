"""
Version retrieval module.

This module provides a way to get the project version from pyproject.toml.
"""

from pathlib import Path

import tomli
from pydantic import validate_call

from depictio.api.v1.configs.custom_logging import logger


@validate_call(validate_return=True)  # noqa: F821
def get_version() -> str:
    """
    Retrieve the version from pyproject.toml.

    Returns:
        str: Project version
    """
    project_root = Path(__file__).parent.parent
    pyproject_path = project_root / "pyproject.toml"

    with open(pyproject_path, "rb") as f:
        pyproject_data = tomli.load(f)

    version = pyproject_data["project"]["version"]
    logger.debug(f"Project version: {version}")

    return version


@validate_call(validate_return=True)  # noqa: F821
def get_api_version() -> str:
    """
    Returns the API version prefix.

    Returns:
        str: API version prefix
    """
    version = get_version()
    major_version = version.split(".")[0]
    if major_version == "0":
        major_version = 1
    return f"v{major_version}"
