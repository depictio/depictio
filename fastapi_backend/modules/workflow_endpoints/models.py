# from pathlib import Path
# from bson import ObjectId
# from pydantic import BaseModel, validator
# import os
# import bleach

    

# class Workflow(BaseModel):
#     workflow_name: str
#     description: str = None  # Optional description
#     workflow_engine: str
#     workflow_location: DirectoryPath
#     workflow_id: str = None
#     workflow_bid: ObjectIdStr = None

#     @validator("workflow_engine")
#     def validate_workflow_engine(cls, value):
#         allowed_values = [
#             "snakemake",
#             "nextflow",
#             "CWL",
#             "galaxy",
#             "smk",
#             "nf",
#             "nf-core",
#         ]
#         if value not in allowed_values:
#             raise ValueError(f"workflow_engine must be one of {allowed_values}")
#         return value

#     @validator("description", pre=True, always=True)
#     def sanitize_description(cls, value):
#         # Strip any HTML tags and attributes
#         sanitized = bleach.clean(value, tags=[], attributes={}, strip=True)
#         # Ensure it's not overly long
#         max_length = 500  # Set as per your needs
#         return sanitized[:max_length]

#     @validator("workflow_location", pre=True, always=True)
#     def validate_location_name(cls, value, values):
#         workflow_engine = values.get("workflow_engine")
#         workflow_name = values.get("workflow_name")
#         expected_name = f"{workflow_engine}--{workflow_name}"
#         actual_name = os.path.basename(value)

#         if actual_name != expected_name:
#             raise ValueError(
#                 f"Directory name should be in format '{expected_name}' but got '{actual_name}'."
#             )

#         return value

