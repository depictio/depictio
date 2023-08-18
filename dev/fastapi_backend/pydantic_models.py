import re
from pydantic import BaseModel, validator
from typing import Dict, Optional, List, Any

class FileConfig(BaseModel):
    regex: str
    format: str
    pandas_kwargs: Optional[Dict[str, Any]] = {}
    keep_columns: Optional[List[str]] = []

    @validator("regex")
    def validate_regex(cls, v):
        try:
            re.compile(v)
            return v
        except re.error:
            raise ValueError("Invalid regex pattern")

class WorkflowConfig(BaseModel):
    location: str
    files: Dict[str, FileConfig]  # Dictionary of FileConfigs indexed by file type name (e.g., "mosaicatcher_stats")

class Config(BaseModel):
    workflows: Dict[str, WorkflowConfig]  # Dictionary of WorkflowConfigs indexed by workflow name (e.g., "snakemake--mosaicatcher-pipeline")
