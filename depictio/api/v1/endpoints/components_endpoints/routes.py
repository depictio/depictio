"""
Component metadata API endpoints for CRUD operations on component metadata.
Provides RESTful API for managing component-level metadata.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo import DESCENDING

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import components_collection, dashboards_collection, projects_collection
from depictio.api.v1.endpoints.user_endpoints.routes import get_current_user, get_user_or_anonymous
from depictio.models.models.base import PyObjectId
from depictio.models.models.components import (
    ComponentMetadataCreateRequest,
    ComponentMetadataData,
    ComponentMetadataListResponse,
    ComponentMetadataResponse,
    ComponentMetadataUpdateRequest,
    ComponentStatus,
    ComponentType,
)
from depictio.models.models.users import User

components_endpoint_router = APIRouter()


def _convert_component_metadata_to_response(doc: dict) -> ComponentMetadataResponse:
    """Convert MongoDB document to response model."""
    return ComponentMetadataResponse(
        id=str(doc["_id"]),
        component_id=doc["component_id"],
        dashboard_id=str(doc["dashboard_id"]),
        component_type=doc["component_type"],
        title=doc.get("title"),
        description=doc.get("description"),
        status=doc["status"],
        position=doc.get("position", {}),
        config=doc.get("config", {}),
        data_collection_ids=[str(dc_id) for dc_id in doc.get("data_collection_ids", [])],
        created_by=str(doc["created_by"]),
        project_id=str(doc["project_id"]),
        tags=doc.get("tags", []),
        custom_metadata=doc.get("custom_metadata", {}),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@components_endpoint_router.post(
    "/",
    response_model=ComponentMetadataResponse,
    summary="Create component metadata",
    description="Create metadata for a dashboard component",
)
async def create_component_metadata(
    request: ComponentMetadataCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """Create new component metadata."""
    try:
        # Validate dashboard exists and user has access
        dashboard_oid = PyObjectId.validate(request.dashboard_id)
        dashboard = dashboards_collection.find_one({"dashboard_id": dashboard_oid})
        if not dashboard:
            raise HTTPException(status_code=404, detail="Dashboard not found")

        # Validate project exists and user has access
        project_oid = PyObjectId.validate(request.project_id)
        project = projects_collection.find_one({"_id": project_oid})
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Check for duplicate component_id within the same dashboard
        existing = components_collection.find_one(
            {"component_id": request.component_id, "dashboard_id": dashboard_oid}
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Component with ID '{request.component_id}' already exists in this dashboard",
            )

        # Convert data collection IDs
        data_collection_ids = []
        for dc_id in request.data_collection_ids:
            try:
                data_collection_ids.append(PyObjectId.validate(dc_id))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid data collection ID: {dc_id}")

        # Create component metadata
        component_data = ComponentMetadataData(
            component_id=request.component_id,
            dashboard_id=dashboard_oid,
            component_type=request.component_type,
            title=request.title,
            description=request.description,
            status=request.status,
            position=request.position,
            config=request.config,
            data_collection_ids=data_collection_ids,
            created_by=PyObjectId.validate(str(current_user.id)),
            project_id=project_oid,
            tags=request.tags,
            custom_metadata=request.custom_metadata,
        )

        # Insert into database
        mongo_doc = component_data.mongo()
        result = components_collection.insert_one(mongo_doc)

        # Retrieve and return created document
        created_doc = components_collection.find_one({"_id": result.inserted_id})
        logger.info(f"Created component metadata: {request.component_id}")

        return _convert_component_metadata_to_response(created_doc)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating component metadata: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@components_endpoint_router.get(
    "/{component_id}",
    response_model=ComponentMetadataResponse,
    summary="Get component metadata",
    description="Retrieve metadata for a specific component",
)
async def get_component_metadata(
    component_id: str,
    current_user: User = Depends(get_user_or_anonymous),
    dashboard_id: str = Query(..., description="Dashboard ID containing the component"),
):
    """Get component metadata by component_id and dashboard_id."""
    try:
        # Validate dashboard ID
        dashboard_oid = PyObjectId.validate(dashboard_id)

        # Find component
        component_doc = components_collection.find_one(
            {"component_id": component_id, "dashboard_id": dashboard_oid}
        )

        if not component_doc:
            raise HTTPException(status_code=404, detail="Component metadata not found")

        return _convert_component_metadata_to_response(component_doc)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error retrieving component metadata: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@components_endpoint_router.put(
    "/{component_id}",
    response_model=ComponentMetadataResponse,
    summary="Update component metadata",
    description="Update metadata for a specific component",
)
async def update_component_metadata(
    component_id: str,
    request: ComponentMetadataUpdateRequest,
    current_user: User = Depends(get_current_user),
    dashboard_id: str = Query(..., description="Dashboard ID containing the component"),
):
    """Update component metadata."""
    try:
        # Validate dashboard ID
        dashboard_oid = PyObjectId.validate(dashboard_id)

        # Find existing component
        existing_doc = components_collection.find_one(
            {"component_id": component_id, "dashboard_id": dashboard_oid}
        )

        if not existing_doc:
            raise HTTPException(status_code=404, detail="Component metadata not found")

        # Prepare update data
        update_data = {"updated_at": datetime.now().isoformat()}

        # Update fields if provided
        if request.title is not None:
            update_data["title"] = request.title
        if request.description is not None:
            update_data["description"] = request.description
        if request.status is not None:
            update_data["status"] = request.status
        if request.position is not None:
            update_data["position"] = request.position
        if request.config is not None:
            update_data["config"] = request.config
        if request.data_collection_ids is not None:
            # Convert data collection IDs
            data_collection_ids = []
            for dc_id in request.data_collection_ids:
                try:
                    data_collection_ids.append(PyObjectId.validate(dc_id))
                except ValueError:
                    raise HTTPException(
                        status_code=400, detail=f"Invalid data collection ID: {dc_id}"
                    )
            update_data["data_collection_ids"] = data_collection_ids
        if request.tags is not None:
            update_data["tags"] = request.tags
        if request.custom_metadata is not None:
            update_data["custom_metadata"] = request.custom_metadata

        # Update document
        components_collection.update_one(
            {"component_id": component_id, "dashboard_id": dashboard_oid}, {"$set": update_data}
        )

        # Retrieve and return updated document
        updated_doc = components_collection.find_one(
            {"component_id": component_id, "dashboard_id": dashboard_oid}
        )

        logger.info(f"Updated component metadata: {component_id}")
        return _convert_component_metadata_to_response(updated_doc)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating component metadata: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@components_endpoint_router.delete(
    "/{component_id}",
    summary="Delete component metadata",
    description="Delete metadata for a specific component",
)
async def delete_component_metadata(
    component_id: str,
    current_user: User = Depends(get_current_user),
    dashboard_id: str = Query(..., description="Dashboard ID containing the component"),
):
    """Delete component metadata."""
    try:
        # Validate dashboard ID
        dashboard_oid = PyObjectId.validate(dashboard_id)

        # Check if component exists
        existing_doc = components_collection.find_one(
            {"component_id": component_id, "dashboard_id": dashboard_oid}
        )

        if not existing_doc:
            raise HTTPException(status_code=404, detail="Component metadata not found")

        # Delete component
        result = components_collection.delete_one(
            {"component_id": component_id, "dashboard_id": dashboard_oid}
        )

        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Component metadata not found")

        logger.info(f"Deleted component metadata: {component_id}")
        return {"message": "Component metadata deleted successfully"}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting component metadata: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@components_endpoint_router.get(
    "/dashboard/{dashboard_id}",
    response_model=ComponentMetadataListResponse,
    summary="List components in dashboard",
    description="List all component metadata for a specific dashboard",
)
async def list_dashboard_components(
    dashboard_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Number of items per page"),
    component_type: Optional[ComponentType] = Query(None, description="Filter by component type"),
    status: Optional[ComponentStatus] = Query(None, description="Filter by component status"),
    tags: Optional[List[str]] = Query(None, description="Filter by tags (AND operation)"),
    current_user: User = Depends(get_user_or_anonymous),
):
    """List component metadata for a dashboard with pagination and filtering."""
    try:
        # Validate dashboard ID
        dashboard_oid = PyObjectId.validate(dashboard_id)

        # Build query
        query = {"dashboard_id": dashboard_oid}

        if component_type:
            query["component_type"] = component_type
        if status:
            query["status"] = status
        if tags:
            query["tags"] = {"$all": tags}

        # Count total documents
        total = components_collection.count_documents(query)

        # Calculate pagination
        skip = (page - 1) * page_size

        # Retrieve documents with pagination
        cursor = (
            components_collection.find(query)
            .sort([("created_at", DESCENDING)])
            .skip(skip)
            .limit(page_size)
        )

        components = [_convert_component_metadata_to_response(doc) for doc in cursor]

        return ComponentMetadataListResponse(
            total=total, components=components, page=page, page_size=page_size
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error listing dashboard components: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@components_endpoint_router.get(
    "/project/{project_id}",
    response_model=ComponentMetadataListResponse,
    summary="List components in project",
    description="List all component metadata for a specific project",
)
async def list_project_components(
    project_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Number of items per page"),
    component_type: Optional[ComponentType] = Query(None, description="Filter by component type"),
    status: Optional[ComponentStatus] = Query(None, description="Filter by component status"),
    current_user: User = Depends(get_user_or_anonymous),
):
    """List component metadata for a project with pagination and filtering."""
    try:
        # Validate project ID
        project_oid = PyObjectId.validate(project_id)

        # Build query
        query = {"project_id": project_oid}

        if component_type:
            query["component_type"] = component_type
        if status:
            query["status"] = status

        # Count total documents
        total = components_collection.count_documents(query)

        # Calculate pagination
        skip = (page - 1) * page_size

        # Retrieve documents with pagination
        cursor = (
            components_collection.find(query)
            .sort([("created_at", DESCENDING)])
            .skip(skip)
            .limit(page_size)
        )

        components = [_convert_component_metadata_to_response(doc) for doc in cursor]

        return ComponentMetadataListResponse(
            total=total, components=components, page=page, page_size=page_size
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error listing project components: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")