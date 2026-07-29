import os
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from depictio.models.config import DEPICTIO_CONTEXT
from depictio.models.models.base import MongoModel, PyObjectId
from depictio.models.models.data_collections import WildcardRegexBase
from depictio.models.models.users import Permission

#: Outcomes a single file can have during a scan.
#:
#: ``skipped`` predates hash-based detection and is kept so older scan results
#: still validate; new scans emit ``unchanged``/``changed`` instead.
ALLOWED_SCAN_REASONS = frozenset({"added", "skipped", "updated", "failed", "unchanged", "changed"})

#: Reasons that mean "this file is already registered and was not re-uploaded".
#: Counted as skipped rather than as a genuine failure.
NOT_UPLOADED_SCAN_REASONS = frozenset({"skipped", "unchanged", "changed"})


class WildcardRegex(WildcardRegexBase):
    value: str


class File(MongoModel):
    file_location: str
    filename: str
    creation_time: str
    modification_time: str
    run_id: PyObjectId | str | None = None
    run_tag: str | None = None
    data_collection_id: PyObjectId
    registration_time: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    #: When this file left the data collection, or ``None`` while it is present.
    #:
    #: A tombstone rather than a hard delete, because "which files backed this
    #: data collection at time T" cannot be answered from records that no
    #: longer exist. ``--sync-files`` used to remove the documents outright, so
    #: a dashboard version saved before a cleanup could name a file set that was
    #: unreconstructable a minute later.
    #:
    #: Absent on every document written before this existed, and Mongo treats a
    #: missing field as equal to ``None``, so ``{"deleted_at": None}`` selects
    #: live files across both shapes with no migration.
    deleted_at: str | None = None

    file_hash: str
    filesize: int
    permissions: Permission

    # id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    # id: Optional[PyObjectId] = None
    # TODO: Add S3 support
    # S3_location: Optional[str] = None
    # S3_key_hash: Optional[str] = None
    # trackId: Optional[str] = None

    @field_validator("filename")
    def validate_filename(cls, v):
        if not v:
            raise ValueError("Filename cannot be empty")
        return v

    @field_validator("filesize")
    def validate_size(cls, v):
        if v < 0:
            raise ValueError("File size cannot be negative")
        if v == 0:
            raise ValueError("File size cannot be zero")
        return v

    @field_validator("file_hash")
    def validate_hash(cls, v):
        if not v:
            raise ValueError("Hash cannot be empty")
        if len(v) != 64:
            raise ValueError("Invalid hash value, must be 32 characters long")
        return v

    @field_validator("creation_time", mode="before")
    def validate_creation_time(cls, value):
        if type(value) is not datetime:
            try:
                dt = datetime.fromisoformat(value)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError("Invalid datetime format")
        else:
            return value.strftime("%Y-%m-%d %H:%M:%S")

    @field_validator("modification_time", mode="before")
    def validate_modification_time(cls, value):
        if type(value) is not datetime:
            try:
                dt = datetime.fromisoformat(value)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError("Invalid datetime format")
        else:
            return value.strftime("%Y-%m-%d %H:%M:%S")

    @field_validator("file_location")
    def validate_location(cls, value):
        if DEPICTIO_CONTEXT.lower() == "cli":
            if not os.path.exists(value):
                raise ValueError(f"The file '{value}' does not exist.")
            if not os.path.isfile(value):
                raise ValueError(f"'{value}' is not a file.")
            if not os.access(value, os.R_OK):
                raise ValueError(f"'{value}' is not readable.")
            return value
        else:
            if not value:
                raise ValueError("File location cannot be empty")
            return value


class FileScanResult(BaseModel):
    file: File
    scan_result: dict[str, str]
    scan_time: str

    class Config:
        extra = "forbid"
        populate_by_name = False

    @field_validator("scan_result")
    def validate_scan_result(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Scan result must be a dictionary")

        # value must contain following keys: "result", "reason"
        if "result" not in value:
            raise ValueError("Scan result must contain 'result' key")
        if "reason" not in value:
            raise ValueError("Scan result must contain 'reason' key")
        if value["result"] not in ["success", "failure"]:
            raise ValueError("Scan result must be one of ['success', 'failure']")
        # ``unchanged``/``changed`` split what used to be a single ``skipped``
        # bucket: the scanner has always computed a metadata hash per file, but
        # only logged the comparison. ``result`` still says whether the file gets
        # uploaded, so ``changed`` appears as a failure until --sync-changed (or
        # --sync-files) opts into acting on it.
        if value["reason"] not in ALLOWED_SCAN_REASONS:
            raise ValueError(f"Scan reason must be one of {sorted(ALLOWED_SCAN_REASONS)}")
        return value

    @field_validator("scan_time", mode="before")
    def validate_modification_time(cls, value):
        if type(value) is not datetime:
            try:
                dt = datetime.fromisoformat(value)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError("Invalid datetime format")
        else:
            return value.strftime("%Y-%m-%d %H:%M:%S")
