# import os
# import re
# from pydantic import BaseModel, FilePath, validator
# from typing import Dict, Optional, List, Any
# import bleach
# import yaml


# class FileConfig(BaseModel):
#     regex: str
#     format: str
#     pandas_kwargs: Optional[Dict[str, Any]] = {}
#     keep_columns: Optional[List[str]] = []

#     @validator("regex")
#     def validate_regex(cls, v):
#         try:
#             re.compile(v)
#             return v
#         except re.error:
#             raise ValueError("Invalid regex pattern")


# class File(BaseModel):
#     file_type: str
#     location: FilePath
#     description: str = None  # Optional description
#     file_id: str = None
#     file_bid: str = None
#     config: FileConfig

#     @validator("description", pre=True, always=True)
#     def sanitize_description(cls, value):
#         # Strip any HTML tags and attributes
#         sanitized = bleach.clean(value, tags=[], attributes={}, strip=True)
#         return sanitized

#     @validator("location")
#     def validate_location(cls, value):
#         if not os.path.exists(value):
#             raise ValueError(f"The file '{value}' does not exist.")
#         if not os.path.isfile(value):
#             raise ValueError(f"'{value}' is not a file.")
#         if not os.access(value, os.R_OK):
#             raise ValueError(f"'{value}' is not readable.")
#         return value

#     # @validator("file_type")
#     # def validate_file_type(cls, value):
