"""
API utility functions for project-wise user management.

This module centralizes all API calls used by the project permissions UI,
providing consistent error handling and authentication.
"""

from typing import Any, Dict, List, Optional

import httpx

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.users import Permission

# -----------------------------------------------------------------------------
# User Management API Functions
# -----------------------------------------------------------------------------


def fetch_all_users(token: str) -> List[Dict[str, Any]]:
    """
    Fetch all users from API for user selection in permissions UI.

    Args:
        token (str): User's authentication token

    Returns:
        List[Dict]: List of user options for multiselect dropdown
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/auth/get_all_users",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        users_list = response.json()

        user_options = [
            {"value": user["id"], "label": user["email"], "is_admin": user.get("is_admin", False)}
            for user in users_list
        ]
        logger.debug(f"Fetched {len(user_options)} users for selection")
        return user_options
    except Exception as e:
        logger.error(f"Error fetching users data: {e}")
        return []


def fetch_all_users_detailed(token: str) -> Dict[str, Dict[str, Any]]:
    """
    Fetch all users from API and return as a lookup dictionary with detailed info.

    Args:
        token (str): User's authentication token

    Returns:
        Dict[str, Dict]: Dictionary mapping user IDs to user details
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/auth/get_all_users",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        users_list = response.json()

        users_lookup = {
            user["id"]: {
                "id": user["id"],
                "email": user["email"],
                "is_admin": user.get("is_admin", False),
            }
            for user in users_list
        }
        logger.debug(f"Fetched detailed data for {len(users_lookup)} users")
        return users_lookup
    except Exception as e:
        logger.error(f"Error fetching detailed users data: {e}")
        return {}


def fetch_user_details(user_id: str, token: str) -> Optional[Dict[str, Any]]:
    """
    Fetch detailed user information by ID using the user's own token.

    SECURITY: This enforces proper permission checking - only users with
    appropriate permissions can fetch user details.

    Args:
        user_id (str): User ID to fetch
        token (str): User's authentication token (NOT internal API key)

    Returns:
        Optional[Dict]: User details or None if error/unauthorized
    """
    try:
        # IMPORTANT: Use user's token so backend can enforce permissions
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/auth/fetch_user/from_id",
            params={"user_id": user_id},
            headers={"Authorization": f"Bearer {token}"},  # User token, not internal key
        )
        response.raise_for_status()
        user_data = response.json()
        logger.debug(f"Fetched details for user: {user_data.get('email', user_id)}")
        return user_data
    except Exception as e:
        logger.error(f"Error fetching user details for {user_id}: {e}")
        # This will fail if user doesn't have permission - which is correct behavior
        return None


def get_current_user_info(token: str) -> Optional[Dict[str, Any]]:
    """
    Get current user information from authentication token.

    Args:
        token (str): User's authentication token

    Returns:
        Optional[Dict]: Current user data or None if error
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        user_data = response.json()
        logger.debug(f"Current user: {user_data.get('email', 'unknown')}")
        return user_data
    except Exception as e:
        logger.error(f"Error fetching current user: {e}")
        return None


# -----------------------------------------------------------------------------
# Project Management API Functions
# -----------------------------------------------------------------------------


def fetch_project_data(project_id: str, token: str) -> Optional[Dict[str, Any]]:
    """
    Fetch project data including permissions.

    Args:
        project_id (str): Project ID
        token (str): User's authentication token

    Returns:
        Optional[Dict]: Project data or None if error
    """
    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/projects/get/from_id",
            params={"project_id": project_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        project_data = response.json()
        logger.debug(f"Fetched project: {project_data.get('name', project_id)}")
        return project_data
    except Exception as e:
        logger.error(f"Error fetching project {project_id}: {e}")
        return None


def update_project_permissions_api(
    project_id: str, permissions_data: List[Dict], token: str
) -> Dict[str, Any]:
    """
    Update project permissions via API.

    Args:
        project_id (str): Project ID
        permissions_data (List[Dict]): List of user permission objects
        token (str): User's authentication token

    Returns:
        Dict: API response with success status
    """
    try:
        # Organize users by permission type
        permissions_payload = {
            "owners": [
                {
                    "_id": user["id"],
                    "email": user["email"],
                    "is_admin": user["is_admin"],
                }
                for user in permissions_data
                if user["Owner"]
            ],
            "editors": [
                {
                    "_id": user["id"],
                    "email": user["email"],
                    "is_admin": user["is_admin"],
                }
                for user in permissions_data
                if user["Editor"]
            ],
            "viewers": [
                {
                    "_id": user["id"],
                    "email": user["email"],
                    "is_admin": user["is_admin"],
                }
                for user in permissions_data
                if user["Viewer"]
            ],
        }

        # Validate with Pydantic model
        permissions_payload_pydantic = Permission(**permissions_payload)
        logger.debug(f"Validated permissions payload: {permissions_payload_pydantic}")

        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/projects/update_project_permissions",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "project_id": project_id,
                "permissions": convert_objectid_to_str(permissions_payload),
            },
        )
        response.raise_for_status()

        logger.info(f"Successfully updated permissions for project {project_id}")
        return {"success": True, "data": response.json()}

    except Exception as e:
        logger.error(f"Error updating project permissions: {e}")
        return {"success": False, "message": str(e)}


def toggle_project_visibility_api(project_id: str, is_public: bool, token: str) -> Dict[str, Any]:
    """
    Toggle project visibility between public and private.

    Args:
        project_id (str): Project ID
        is_public (bool): Desired visibility state
        token (str): User's authentication token

    Returns:
        Dict: API response with success status
    """
    try:
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/projects/toggle_public_private/{project_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"is_public": is_public},
        )
        response.raise_for_status()

        logger.info(
            f"Successfully toggled project {project_id} visibility to {'public' if is_public else 'private'}"
        )
        return {"success": True, "message": response.json()}

    except Exception as e:
        logger.error(f"Error toggling project visibility: {e}")
        return {"success": False, "message": str(e)}


# -----------------------------------------------------------------------------
# Permission Processing Functions
# -----------------------------------------------------------------------------


def process_permission_users(users: List[Dict], token: str, permission_type: str) -> List[Dict]:
    """
    Process a list of users for a given permission type.

    Args:
        users (List[Dict]): List of user objects from project permissions
        token (str): User's authentication token
        permission_type (str): "Owner", "Editor", or "Viewer"

    Returns:
        List[Dict]: Processed user permission data for UI grid
    """
    processed_users = []

    for user in users:
        logger.debug(f"Processing user: {user} with ID {user['id']}")

        # Use the user data that's already available in the project permissions
        # This avoids the need for additional API calls that might fail due to permission restrictions

        # Extract group information from the user data (excluding default groups)
        # The user data in project permissions should already contain group information
        group_names = []
        if "groups" in user:
            group_names = [
                group.get("name", "")
                for group in user.get("groups", [])
                if isinstance(group, dict) and group.get("name") not in ["admin", "users"]
            ]
        groups_str = ", ".join(group_names)

        # Create permission flags
        permission_flags = {
            "Owner": permission_type == "Owner",
            "Editor": permission_type == "Editor",
            "Viewer": permission_type == "Viewer",
        }

        processed_users.append(
            {
                "id": user.get("id", user.get("_id")),  # Handle both id and _id keys
                "email": user.get("email", ""),
                "groups": groups_str,
                **permission_flags,
                "is_admin": user.get("is_admin", False),
                "groups_with_metadata": convert_objectid_to_str(user.get("groups", [])),
            }
        )

    return processed_users


def fetch_project_permissions(project_id: str, token: str) -> List[Dict]:
    """
    Fetch and format project permissions for display in the UI grid.

    Args:
        project_id (str): Project ID
        token (str): User's authentication token

    Returns:
        List[Dict]: Formatted permission data for AG Grid
    """
    logger.info(f"Fetching permissions for project ID: {project_id}")

    project_data = fetch_project_data(project_id, token)
    if not project_data:
        logger.error(f"Could not fetch project data for {project_id}")
        return []

    permissions_data = []

    if "permissions" in project_data:
        # Process each permission type
        for permission_type, users in [
            ("Owner", project_data["permissions"].get("owners", [])),
            ("Editor", project_data["permissions"].get("editors", [])),
            ("Viewer", project_data["permissions"].get("viewers", [])),
        ]:
            processed_users = process_permission_users(users, token, permission_type)
            permissions_data.extend(processed_users)

    logger.info(f"Retrieved {len(permissions_data)} permission entries for project {project_id}")
    return permissions_data


# -----------------------------------------------------------------------------
# User Permission Checking
# -----------------------------------------------------------------------------


def check_user_project_permissions(project_id: str, token: str) -> Dict[str, bool]:
    """
    Check current user's permissions for a specific project.

    Args:
        project_id (str): Project ID
        token (str): User's authentication token

    Returns:
        Dict[str, bool]: Dictionary with is_admin and is_owner flags
    """
    try:
        # Get current user info
        current_user = get_current_user_info(token)
        if not current_user:
            return {"is_admin": False, "is_owner": False}

        is_admin = current_user.get("is_admin", False)

        # Get project data to check ownership
        project_data = fetch_project_data(project_id, token)
        if not project_data:
            return {"is_admin": is_admin, "is_owner": False}

        # Check if user is project owner
        is_owner = False
        if "permissions" in project_data and "owners" in project_data["permissions"]:
            current_user_id = current_user.get("id")
            is_owner = any(
                str(owner.get("_id")) == str(current_user_id)
                for owner in project_data["permissions"].get("owners", [])
            )

        logger.debug(
            f"User {current_user.get('email')} permissions for project {project_id}: admin={is_admin}, owner={is_owner}"
        )
        return {"is_admin": is_admin, "is_owner": is_owner}

    except Exception as e:
        logger.error(f"Error checking user permissions for project {project_id}: {e}")
        return {"is_admin": False, "is_owner": False}


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------


def build_permissions_payload(rows: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Build the permissions payload from grid rows for API submission.

    Args:
        rows (List[Dict]): List of user permission dictionaries from grid

    Returns:
        Dict[str, List[Dict]]: Organized permissions payload
    """
    return {
        "owners": [
            {
                "_id": user["id"],
                "email": user["email"],
                "is_admin": user["is_admin"],
            }
            for user in rows
            if user["Owner"]
        ],
        "editors": [
            {
                "_id": user["id"],
                "email": user["email"],
                "is_admin": user["is_admin"],
            }
            for user in rows
            if user["Editor"]
        ],
        "viewers": [
            {
                "_id": user["id"],
                "email": user["email"],
                "is_admin": user["is_admin"],
            }
            for user in rows
            if user["Viewer"]
        ],
    }


def validate_and_update_permissions(rows: List[Dict], project_id: str, token: str) -> bool:
    """
    Validate and update project permissions via API.

    Args:
        rows (List[Dict]): Updated permission rows from grid
        project_id (str): Project ID
        token (str): User's authentication token

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        payload = build_permissions_payload(rows)
        logger.debug(f"Built permissions payload: {payload}")

        # Validate payload using Pydantic model
        permissions_payload_pydantic = Permission(**payload)
        logger.debug(f"Validated permissions: {permissions_payload_pydantic}")

        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/projects/update_project_permissions",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "project_id": project_id,
                "permissions": convert_objectid_to_str(payload),
            },
        )
        response.raise_for_status()

        logger.info(f"Successfully updated permissions for project {project_id}")
        return True

    except Exception as e:
        logger.error(f"Error updating permissions: {e}")
        return False
