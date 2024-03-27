import collections
from datetime import datetime
import hashlib
import os
from pprint import pprint
import shutil
from bson import ObjectId
from fastapi import HTTPException, Depends, APIRouter
import deltalake
import polars as pl
import numpy as np

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import db, workflows_collection, files_collection, users_collection, deltatables_collection
from depictio.api.v1.endpoints.dashboards_endpoints.models import DashboardData
from depictio.api.v1.s3 import s3_client
from depictio.api.v1.endpoints.deltatables_endpoints.models import Aggregation, DeltaTableAggregated
from depictio.api.v1.endpoints.files_endpoints.models import File
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user
from depictio.api.v1.endpoints.user_endpoints.models import User
from depictio.api.v1.endpoints.validators import validate_workflow_and_collection
from depictio.api.v1.models.base import convert_objectid_to_str


from depictio.api.v1.utils import (
    # decode_token,
    # public_key_path,
    numpy_to_python,
    serialize_for_mongo,
    agg_functions,
)


dashboards_endpoint_router = APIRouter()


@dashboards_endpoint_router.get("/get/{dashboard_id}")
# @datacollections_endpoint_router.get("/files/{workflow_id}/{data_collection_id}", response_model=List[GridFSFileInfo])
async def list_versions(
    dashboard_id: str,
    # current_user: str = Depends(get_current_user),
):
    """
    Fetch all entries related to a dashboard ID
    """
    dashboard_id = ObjectId(dashboard_id)
    # Get all entries related to a dashboard ID
    entries = deltatables_collection.find({"dashboard_id": dashboard_id})
    entries = [convert_objectid_to_str(entry) for entry in entries]
    return entries


@dashboards_endpoint_router.get("/save/{dashboard_id}")
# @datacollections_endpoint_router.get("/files/{workflow_id}/{data_collection_id}", response_model=List[GridFSFileInfo])
async def save_dashboard(
    dashboard_id: str,
    data: DashboardData,
    # current_user: str = Depends(get_current_user),
):
    """
    Fetch all entries related to a dashboard ID
    """
    dashboard_id = ObjectId(dashboard_id)
    # Get all entries related to a dashboard ID
    entries = deltatables_collection.find({"dashboard_id": dashboard_id})
    entries = [convert_objectid_to_str(entry) for entry in entries]
    return entries


 