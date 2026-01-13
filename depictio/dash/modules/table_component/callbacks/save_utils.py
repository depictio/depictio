"""
Shared save utilities for table components.

This module provides reusable functions for saving table component metadata
to dashboards, used by both add and edit workflows.
"""

import httpx

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger


def save_table_to_dashboard(
    dashboard_id: str, component_metadata: dict, token: str, app_prefix: str = "dashboard"
) -> str:
    """
    Save or update table component in dashboard.

    This function handles the complete API interaction for saving table metadata:
    1. Fetches current dashboard data
    2. Finds/updates component in stored_metadata array
    3. Posts updated dashboard back to API
    4. Returns appropriate redirect URL

    Args:
        dashboard_id: Target dashboard ID
        component_metadata: Complete component metadata dict with all table fields
        token: Authentication token
        app_prefix: URL prefix - "dashboard" for viewer, "dashboard-edit" for editor

    Returns:
        Redirect URL after successful save

    Raises:
        Exception: If API calls fail (logged but not re-raised)
    """
    component_id = component_metadata["index"]

    logger.info(f"💾 SAVE TABLE - Dashboard: {dashboard_id}, Component: {component_id}")
    logger.info(f"   Metadata keys: {list(component_metadata.keys())}")

    try:
        # 1. Fetch current dashboard data
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/get/{dashboard_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        response.raise_for_status()
        dashboard_data = response.json()

        # 2. Update component in stored_metadata
        existing_metadata = dashboard_data.get("stored_metadata", [])

        # Find and replace component, or append if new
        updated_metadata_list = []
        component_found = False

        for meta in existing_metadata:
            if str(meta.get("index")) == str(component_id):
                # Replace existing component
                updated_metadata_list.append(component_metadata)
                component_found = True
                logger.info(f"   ✓ Replaced component {component_id} in metadata")
            else:
                # Keep other components unchanged
                updated_metadata_list.append(meta)

        if not component_found:
            # Component not found - this is a new component (add flow)
            updated_metadata_list.append(component_metadata)
            logger.info(f"   ✓ Added new component {component_id} to metadata")

        # Update dashboard data with modified metadata
        dashboard_data["stored_metadata"] = updated_metadata_list

        # 3. Save dashboard via API
        update_response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/dashboards/save/{dashboard_id}",
            headers={"Authorization": f"Bearer {token}"},
            json=dashboard_data,
            timeout=30.0,
        )
        update_response.raise_for_status()

        logger.info(f"✅ SAVE TABLE SUCCESS - Component {component_id} saved")
        logger.info(f"   API Response status: {update_response.status_code}")

    except Exception as e:
        logger.error(f"❌ SAVE TABLE FAILED - Error: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
        import traceback

        logger.error(f"   Traceback: {traceback.format_exc()}")

    # 4. Return redirect URL (preserves app context)
    redirect_url = f"/{app_prefix}/{dashboard_id}"
    logger.info(f"🔄 Redirecting to {redirect_url}")
    return redirect_url
