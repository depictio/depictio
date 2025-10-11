"""
Workflow logo overlay component for dashboard visualization.
Displays workflow branding (e.g., nf-core logos) in bottom-right corner.
"""

import os
from typing import Optional

import dash_mantine_components as dmc
from dash import html

from depictio.api.v1.configs.logging_init import logger


def get_workflow_logo_path(workflow_tag: str, theme: str = "light") -> Optional[str]:
    """
    Convert workflow tag to logo asset path.

    Args:
        workflow_tag: Workflow identifier (e.g., "nf-core/ampliseq")
        theme: Theme name ("light" or "dark")

    Returns:
        Asset path string if logo exists, None otherwise
    """
    if not workflow_tag:
        return None

    # Extract workflow name from tag (handle "nf-core/ampliseq" format)
    # Convert to filename format: "nf-core/ampliseq" → "nf-core-ampliseq"
    logo_name = workflow_tag.replace("/", "-")

    # Check for theme-specific variant first, fallback to base logo
    theme_logo = f"{logo_name}_{theme}.png"
    base_logo = f"{logo_name}.png"

    # Construct asset paths
    assets_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "assets", "images", "workflows"
    )

    # Check if theme-specific logo exists
    theme_path = os.path.join(assets_dir, theme_logo)
    if os.path.exists(theme_path):
        return f"/assets/images/workflows/{theme_logo}"

    # Check if base logo exists
    base_path = os.path.join(assets_dir, base_logo)
    if os.path.exists(base_path):
        return f"/assets/images/workflows/{base_logo}"

    logger.debug(f"No logo found for workflow: {workflow_tag}")
    return None


def create_workflow_logo_overlay(
    project_data: Optional[dict] = None, theme: str = "light"
) -> html.Div:
    """
    Create workflow logo overlay component for dashboard.

    Displays workflow branding logo in bottom-right corner of dashboard.
    Returns empty div if no valid workflow logo is found.

    Args:
        project_data: Project data dictionary containing workflows
        theme: Theme name ("light" or "dark")

    Returns:
        Dash html.Div containing logo image or empty div
    """
    logger.info(f"🎨 LOGO OVERLAY: Called with project_data type: {type(project_data)}")

    if not project_data or not isinstance(project_data, dict):
        logger.warning("🎨 LOGO OVERLAY: No project_data or not a dict")
        return html.Div()

    # Extract workflows from project data
    workflows = project_data.get("workflows", [])
    logger.info(f"🎨 LOGO OVERLAY: Found {len(workflows) if workflows else 0} workflows")

    if not workflows or not isinstance(workflows, list):
        logger.warning("🎨 LOGO OVERLAY: No workflows or not a list")
        return html.Div()

    # Get first workflow (dashboards typically associated with single workflow)
    first_workflow = workflows[0] if workflows else None
    if not first_workflow or not isinstance(first_workflow, dict):
        logger.warning("🎨 LOGO OVERLAY: No first_workflow or not a dict")
        return html.Div()

    # Get workflow tag
    workflow_tag = first_workflow.get("workflow_tag")
    logger.info(f"🎨 LOGO OVERLAY: Extracted workflow_tag: {workflow_tag}")

    if not workflow_tag:
        logger.warning("🎨 LOGO OVERLAY: No workflow_tag found")
        return html.Div()

    # Get logo path
    logo_path = get_workflow_logo_path(workflow_tag, theme)
    logger.info(f"🎨 LOGO OVERLAY: Logo path resolved to: {logo_path}")

    if not logo_path:
        logger.warning(f"🎨 LOGO OVERLAY: No logo path for workflow_tag: {workflow_tag}")
        return html.Div()

    logger.info(
        f"✅ LOGO OVERLAY: Creating overlay for {workflow_tag} (theme: {theme}) at path: {logo_path}"
    )

    # Create overlay with DMC Image component
    return html.Div(
        dmc.Image(
            src=logo_path,
            alt=f"{workflow_tag} logo",
            className="workflow-logo-overlay",
            style={
                "maxWidth": "200px",
                "maxHeight": "80px",
                "objectFit": "contain",
            },
        ),
        style={
            "position": "fixed",
            "bottom": "20px",
            "right": "20px",
            "zIndex": "100",
            "pointerEvents": "none",
        },
    )
