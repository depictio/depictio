"""
Link management utilities for the CLI.

This module provides functions for managing DC links via the API,
including creating, listing, resolving, and deleting links between
data collections.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import validate_call

from depictio.cli.cli.utils.common import generate_api_headers
from depictio.cli.cli_logging import logger
from depictio.models.models.cli import CLIConfig


@validate_call
def api_get_project_links(project_id: str, CLI_config: CLIConfig) -> httpx.Response:
    """
    Get all DC links for a project.

    Args:
        project_id: Project ID to get links for.
        CLI_config: Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info(f"Getting links for project ID: {project_id}")

    url = f"{CLI_config.api_base_url}/depictio/api/v1/links/{project_id}"
    response = httpx.get(url, headers=generate_api_headers(CLI_config), timeout=30.0)
    return response


@validate_call
def api_get_links_for_target_dc(
    project_id: str, dc_id: str, CLI_config: CLIConfig
) -> httpx.Response:
    """
    Get all links where a specific DC is the target.

    Args:
        project_id: Project ID.
        dc_id: Data collection ID (target).
        CLI_config: Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info(f"Getting links targeting DC: {dc_id}")

    url = f"{CLI_config.api_base_url}/depictio/api/v1/links/{project_id}/target/{dc_id}"
    response = httpx.get(url, headers=generate_api_headers(CLI_config), timeout=30.0)
    return response


@validate_call
def api_get_links_for_source_dc(
    project_id: str, dc_id: str, CLI_config: CLIConfig
) -> httpx.Response:
    """
    Get all links where a specific DC is the source.

    Args:
        project_id: Project ID.
        dc_id: Data collection ID (source).
        CLI_config: Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info(f"Getting links from source DC: {dc_id}")

    url = f"{CLI_config.api_base_url}/depictio/api/v1/links/{project_id}/source/{dc_id}"
    response = httpx.get(url, headers=generate_api_headers(CLI_config), timeout=30.0)
    return response


@validate_call
def api_create_link(
    project_id: str, link_data: dict[str, Any], CLI_config: CLIConfig
) -> httpx.Response:
    """
    Create a new DC link for a project.

    Args:
        project_id: Project ID.
        link_data: Link configuration data.
        CLI_config: Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info(f"Creating link for project ID: {project_id}")
    logger.debug(f"Link data: {link_data}")

    url = f"{CLI_config.api_base_url}/depictio/api/v1/links/{project_id}"
    response = httpx.post(
        url, json=link_data, headers=generate_api_headers(CLI_config), timeout=30.0
    )
    return response


@validate_call
def api_update_link(
    project_id: str, link_id: str, link_data: dict[str, Any], CLI_config: CLIConfig
) -> httpx.Response:
    """
    Update an existing DC link.

    Args:
        project_id: Project ID.
        link_id: Link ID to update.
        link_data: Updated link configuration data.
        CLI_config: Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info(f"Updating link {link_id} for project ID: {project_id}")
    logger.debug(f"Link data: {link_data}")

    url = f"{CLI_config.api_base_url}/depictio/api/v1/links/{project_id}/{link_id}"
    response = httpx.put(
        url, json=link_data, headers=generate_api_headers(CLI_config), timeout=30.0
    )
    return response


@validate_call
def api_delete_link(project_id: str, link_id: str, CLI_config: CLIConfig) -> httpx.Response:
    """
    Delete a DC link.

    Args:
        project_id: Project ID.
        link_id: Link ID to delete.
        CLI_config: Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server.
    """
    logger.info(f"Deleting link {link_id} for project ID: {project_id}")

    url = f"{CLI_config.api_base_url}/depictio/api/v1/links/{project_id}/{link_id}"
    response = httpx.delete(url, headers=generate_api_headers(CLI_config), timeout=30.0)
    return response


@validate_call
def api_resolve_link(
    project_id: str,
    source_dc_id: str,
    source_column: str,
    filter_values: list[Any],
    target_dc_id: str,
    CLI_config: CLIConfig,
) -> httpx.Response:
    """
    Resolve filtered values from source DC to target DC via link.

    Args:
        project_id: Project ID.
        source_dc_id: Source data collection ID.
        source_column: Column in source DC to filter on.
        filter_values: Values to resolve.
        target_dc_id: Target data collection ID.
        CLI_config: Configuration object containing API base URL and credentials.

    Returns:
        httpx.Response: The response from the server containing resolved values.
    """
    logger.info(f"Resolving link from {source_dc_id} to {target_dc_id}")
    logger.debug(f"Filter values: {filter_values}")

    url = f"{CLI_config.api_base_url}/depictio/api/v1/links/{project_id}/resolve"
    payload = {
        "source_dc_id": source_dc_id,
        "source_column": source_column,
        "filter_values": filter_values,
        "target_dc_id": target_dc_id,
    }
    response = httpx.post(url, json=payload, headers=generate_api_headers(CLI_config), timeout=30.0)
    return response


def format_link_for_display(link: dict[str, Any]) -> dict[str, Any]:
    """
    Format a link for display in CLI output.

    Args:
        link: Link data from API response.

    Returns:
        dict: Formatted link data for display.
    """
    link_config = link.get("link_config", {})
    return {
        "id": link.get("id", "N/A"),
        "source_dc_id": link.get("source_dc_id", "N/A"),
        "source_column": link.get("source_column", "N/A"),
        "target_dc_id": link.get("target_dc_id", "N/A"),
        "target_type": link.get("target_type", "N/A"),
        "resolver": link_config.get("resolver", "direct"),
        "enabled": link.get("enabled", True),
        "description": link.get("description", ""),
    }
