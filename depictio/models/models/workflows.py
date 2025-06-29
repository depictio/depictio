import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from depictio.models.config import DEPICTIO_CONTEXT
from depictio.models.logging import logger
from depictio.models.models.base import DirectoryPath, MongoModel, PyObjectId
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.users import Permission


class WorkflowDataLocation(MongoModel):
    structure: str
    locations: list[str]
    runs_regex: str | None = None

    @field_validator("structure", mode="before")
    def validate_mode(cls, value):
        if value not in ["flat", "sequencing-runs"]:
            raise ValueError("structure must be either 'flat' or 'sequencing-runs'")
        return value

    @field_validator("locations", mode="after")
    def validate_and_recast_parent_runs_location(cls, value):
        if DEPICTIO_CONTEXT.lower() == "cli":
            # Recast to List[DirectoryPath] and validate

            env_var_pattern = re.compile(r"\{([A-Z0-9_]+)\}")

            expanded_paths = []
            for location in value:
                matches = env_var_pattern.findall(location)
                for match in matches:
                    env_value = os.environ.get(match)
                    logger.debug(f"Original path: {location}")
                    # logger.debug(f"Expanded path: {location.replace(f'{{{match}}}', env_value)}")

                    if not env_value:
                        raise ValueError(
                            f"Environment variable '{match}' is not set for path '{location}'."
                        )
                    # Replace the placeholder with the actual value
                    location = location.replace(f"{{{match}}}", env_value)
                expanded_paths.append(location)

            # Validate the expanded paths if in CLI context
            return [DirectoryPath(path=str(Path(location))).path for location in expanded_paths]
        else:
            return value

    @model_validator(mode="before")
    def validate_regex(cls, values):
        # only if mode is 'sequencing-runs' - check mode first
        if values["structure"] == "sequencing-runs":
            if "runs_regex" not in values or not values["runs_regex"]:
                raise ValueError("runs_regex is required when structure is 'sequencing-runs'")
            # just check if the regex is valid
            try:
                re.compile(values["runs_regex"])
                return values
            except re.error:
                raise ValueError("Invalid runs_regex pattern")
        return values


class WorkflowConfig(MongoModel):
    version: str | None = None
    workflow_parameters: dict | None = None


class WorkflowRunScan(BaseModel):
    stats: dict[str, int]
    files_id: dict[str, list[PyObjectId]]
    scan_time: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dc_stats: Optional[Dict[str, Dict[str, int]]] = None  # Per-data-collection stats


class WorkflowRun(MongoModel):
    workflow_id: PyObjectId
    run_tag: str
    files_id: list[PyObjectId] = []
    workflow_config_id: PyObjectId
    run_location: str
    creation_time: str
    last_modification_time: str
    registration_time: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_hash: str = ""
    scan_results: list[WorkflowRunScan] | None = []
    permissions: Permission
    _dc_stats_for_display: Optional[Dict[str, Dict[str, int]]] = None  # Per-data-collection stats

    @field_validator("run_location", mode="after")
    def validate_and_recast_parent_runs_location(cls, value):
        if DEPICTIO_CONTEXT == "CLI":
            # Recast to List[DirectoryPath] and validate
            env_var_pattern = re.compile(r"\{([A-Z0-9_]+)\}")

            expanded_paths = []
            location = value
            matches = env_var_pattern.findall(location)
            for match in matches:
                env_value = os.environ.get(match)
                logger.debug(f"Original path: {location}")
                logger.debug(f"Expanded path: {location.replace(f'{{{match}}}', env_value)}")

                if not env_value:
                    raise ValueError(
                        f"Environment variable '{match}' is not set for path '{location}'."
                    )
                # Replace the placeholder with the actual value
                location = location.replace(f"{{{match}}}", env_value)
            expanded_paths.append(location)

            # Validate the expanded paths if in CLI context
            return DirectoryPath(path=str(Path(location))).path
        else:
            return value

    @field_validator("run_hash", mode="before")
    def validate_hash(cls, value):
        # tolerate empty hash or hash of length 64
        if len(value) == 0 or len(value) == 64:
            return value

    @field_validator("files_id", mode="before")
    def validate_files(cls, value):
        if not isinstance(value, list):
            raise ValueError("files must be a list")
        return value

    @field_validator("workflow_config_id", mode="before")
    def validate_workflow_config(cls, value):
        if isinstance(value, PyObjectId):
            return value
        if isinstance(value, str):
            return PyObjectId(value)
        # if not isinstance(value, PyObjectId):
        #     raise ValueError("workflow_config_id must be a PyObjectId")
        return value

    @field_validator("creation_time", mode="before")
    def validate_creation_time(cls, value):
        # check if compliant with %Y-%m-%d %H:%M:%S" format
        if type(value) is not datetime:
            try:
                dt = datetime.fromisoformat(value)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError("Invalid datetime format")

    @field_validator("last_modification_time", mode="before")
    def validate_last_modification_time(cls, value):
        # check if compliant with %Y-%m-%d %H:%M:%S" format
        if type(value) is not datetime:
            try:
                dt = datetime.fromisoformat(value)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError("Invalid datetime format")

    @field_validator("registration_time", mode="before")
    def validate_registration_time(cls, value):
        # check if compliant with %Y-%m-%d %H:%M:%S" format
        if type(value) is not datetime:
            try:
                dt = datetime.fromisoformat(value)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError("Invalid datetime format")


class WorkflowEngine(BaseModel):
    name: str
    version: str | None = None

    class Config:
        extra = "forbid"  # Reject unexpected fields

    # @field_validator("name", mode="before")
    # def validate_workflow_engine_value(cls, value):
    #     allowed_values = [
    #         "snakemake",
    #         "nextflow",
    #         "toil",
    #         "cwltool",
    #         "arvados",
    #         "streamflow",
    #         "galaxy",
    #         "airflow",
    #         "dagster",
    #         "python",
    #         "shell",
    #         "r",
    #         "julia",
    #         "matlab",
    #         "perl",
    #         "java",
    #         "c",
    #         "c++",
    #         "go",
    #         "rust",
    #     ]
    #     if value not in allowed_values:
    #         raise ValueError(f"workflow_engine must be one of {allowed_values}")
    #     return value


class WorkflowCatalog(BaseModel):
    name: str | None
    url: str | None

    class Config:
        extra = "forbid"  # Reject unexpected fields

    @field_validator("url", mode="before")
    def validate_workflow_catalog_url(cls, value):
        if not re.match(r"^(https?|git)://", value):
            raise ValueError("Invalid URL")
        return value

    @field_validator("name", mode="before")
    def validate_workflow_catalog_name(cls, value):
        if value not in ["workflowhub", "nf-core", "smk-wf-catalog"]:
            raise ValueError("Invalid workflow catalog name")
        return value


class Workflow(MongoModel):
    name: str
    engine: WorkflowEngine
    version: str | None = None
    catalog: WorkflowCatalog | None = None
    workflow_tag: str | None = None
    # description: Optional[Description] = None
    repository_url: str | None = None
    data_collections: list[DataCollection]
    runs: dict[str, WorkflowRun] | None = dict()
    config: WorkflowConfig | None = Field(default_factory=WorkflowConfig)
    data_location: WorkflowDataLocation
    registration_time: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @field_validator("version", mode="before")
    def validate_version(cls, value):
        if not value:
            return None
        if not isinstance(value, str):
            raise ValueError("version must be a string")
        return value

    @model_validator(mode="before")
    @classmethod
    def generate_workflow_tag(cls, values):
        engine = values.get("engine", {})
        name = values.get("name")

        if not isinstance(engine, WorkflowEngine):
            values["workflow_tag"] = values.get("name", "")
            return values
        catalog = values.get("catalog")
        if not isinstance(catalog, WorkflowCatalog):
            catalog = None
        logger.debug(f"Engine: {engine}, Name: {name}, Catalog: {catalog}")
        values["workflow_tag"] = f"{engine.name}/{name}"
        if catalog:
            catalog_name = catalog.name
            if catalog_name == "nf-core":
                values["workflow_tag"] = f"{catalog_name}/{name}"
        return values

    def __eq__(self, other):
        if isinstance(other, Workflow):
            return all(
                getattr(self, field) == getattr(other, field)
                for field in self.model_fields.keys()
                if field not in ["id", "registration_time"]
            )
        return NotImplemented

    @field_validator("name", mode="before")
    def validate_name(cls, value):
        if not value:
            raise ValueError("name is required")
        return value

    @field_validator("engine", mode="before")
    def validate_engine(cls, value):
        if not value:
            raise ValueError("engine is required")
        return value

    # @field_validator("repository_url", mode="before")
    # def validate_repository(cls, value):
    #     if not value:
    #         return None
    #     if not re.match(r"^(https?|git)://", value):
    #         raise ValueError("Invalid repository URL")
    #     return value

    # @model_validator(mode="before")
    # def set_workflow_tag(cls, values):
    #     # print(f"Received values: {values}")

    #     engine = values.get("engine")
    #     name = values.get("name")
    #     if engine and name:
    #         values["workflow_tag"] = f"{engine}/{name}"
    #     return values

    @field_validator("data_collections", mode="before")
    def validate_data_collections(cls, value):
        if not isinstance(value, list):
            raise ValueError("data_collections must be a list")
        return value

    @field_validator("runs", mode="before")
    def validate_runs(cls, value):
        if not isinstance(value, dict):
            raise ValueError("runs must be a dictionary")
        return value
