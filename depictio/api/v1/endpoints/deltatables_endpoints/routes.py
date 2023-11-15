import collections
from datetime import datetime
from io import BytesIO
import json
import os
from pathlib import PosixPath
import re
from bson import ObjectId
from deltalake import DeltaTable
from fastapi import HTTPException, Depends, APIRouter
from typing import List

import pandas as pd
import polars as pl
import numpy as np
from pydantic import BaseModel

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import db, grid_fs
from depictio.api.v1.endpoints.user_endpoints.auth import get_current_user
from depictio.api.v1.models.base import convert_objectid_to_str


from depictio.api.v1.models.pydantic_models import (
    Aggregation,
    DeltaTableAggregated,
    User,
    Workflow,
    File,
    DataCollection,
    WorkflowRun,
)
from depictio.api.v1.models.pydantic_models import GridFSFileInfo
from depictio.api.v1.utils import (
    # decode_token,
    # public_key_path,
    numpy_to_python,
    scan_runs,
    serialize_for_mongo,
    agg_functions,
)


deltatables_endpoint_router = APIRouter()

data_collections_collection = db[settings.collections.data_collection]
workflows_collection = db[settings.collections.workflow_collection]
runs_collection = db[settings.collections.runs_collection]
files_collection = db[settings.collections.files_collection]
users_collection = db["users"]
