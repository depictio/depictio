"""
Version retrieval module.

This module provides a way to get the project version from VERSION file.
"""

from pathlib import Path

from pydantic import validate_call

from depictio.api.v1.configs.logging_init import logger


@validate_call(validate_return=True)  # noqa: F821
def get_version() -> str:
    """
    Retrieve the version from VERSION file.

    Returns:
        str: Project version
    """
    project_root = Path(__file__).parent.parent
    version_path = project_root / "VERSION"

    with open(version_path, "r") as f:
        version = f.read().strip()

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
