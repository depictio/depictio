from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from depictio.models.models.base import MongoModel, PyObjectId
from depictio.models.models.users import UserBase


class DeltaTableColumn(BaseModel):
    name: str
    type: str
    description: str | None = None  # Optional description
    specs: dict | None = None

    class Config:
        extra = "forbid"  # Reject unexpected fields

    @field_validator("type")
    def validate_column_type(cls, v):
        allowed_values = [
            "string",
            "utf8",
            "object",
            "int64",
            "float64",
            "bool",
            "date",
            "datetime",
            "time",
            "category",
        ]
        normalized = v.lower()
        # pandas 3.0 reports string columns with a dedicated dtype whose
        # str(dtype) == "str" (pandas <3 used "object"). Treat any string-like
        # dtype as "object" so type metadata stays consistent across the bump.
        if normalized == "str" or normalized.startswith("string") or normalized == "large_string":
            return "object"
        if normalized not in allowed_values:
            raise ValueError(f"column_type must be one of {allowed_values}")
        return v


class Aggregation(MongoModel):
    aggregation_time: datetime = Field(default_factory=datetime.now)
    aggregation_by: UserBase
    #: Depictio's own counter, and — importantly — the salt for the API's
    #: DataFrame cache keys. Distinct from ``delta_version`` below, which is the
    #: physical Delta commit number. Do not conflate them.
    aggregation_version: int = 1
    aggregation_hash: str
    aggregation_columns_specs: list[DeltaTableColumn] = []

    # Delta Lake provenance. Every field is optional with a default so documents
    # written before this existed still validate: Aggregation inherits
    # MongoModel, which is extra="forbid", and from_mongo runs over historical
    # documents on every read.
    delta_version: int | None = None
    delta_commit_timestamp: datetime | None = None
    write_mode: str | None = None
    rows_total: int | None = None
    rows_added: int | None = None
    files_added: int | None = None
    run_tags: list[str] = []
    ingestion_run_id: str | None = None
    #: How the write was initiated: manual CLI run, watcher cycle, UI upload.
    trigger: str | None = None
    #: ``complete`` once ``aggregation_columns_specs`` describes the table.
    #: ``pending`` marks the window in which an offloaded job is still computing
    #: them, letting a reader tell "this table has no columns" apart from "the
    #: columns are not known yet". Defaults to ``complete``: every document the
    #: synchronous path ever wrote — i.e. all of them, before offloading
    #: existed — was complete by the time it was stored.
    aggregation_status: str = "complete"

    @field_validator("aggregation_version")
    def validate_version(cls, value):
        if not isinstance(value, int):
            raise ValueError("version must be an integer")
        return value


class FilterCondition(BaseModel):
    class Config:
        extra = "forbid"  # Reject unexpected fields

    above: int | float | str | None = None
    equal: int | float | str | None = None
    under: int | float | str | None = None


class DeltaTableQuery(MongoModel):
    columns: list[str]
    filters: dict[str, FilterCondition]
    sort: list[str] | None = []
    limit: int | None = None
    offset: int | None = None


class Test(BaseModel):
    test: str


class DeltaTableAggregated(MongoModel):
    data_collection_id: PyObjectId
    delta_table_location: str
    aggregation: list[Aggregation] = []


class UpsertDeltaTableAggregated(BaseModel):
    data_collection_id: PyObjectId
    delta_table_location: str
    update: bool = False
    deltatable_size_bytes: int | None = None

    # Delta provenance reported by the writer. All optional: an older CLI sends
    # none of it, and pydantic's default extra="ignore" means a newer CLI
    # talking to an older server simply has these dropped.
    delta_version: int | None = None
    delta_commit_timestamp: datetime | None = None
    write_mode: str | None = None
    rows_total: int | None = None
    rows_added: int | None = None
    files_added: int | None = None
    run_tags: list[str] = []
    ingestion_run_id: str | None = None
    trigger: str | None = None

    #: Ask the server to offload the expensive half of the upsert and return a
    #: ``job_id`` to poll. A *request*, not an instruction: the server also has
    #: to have offloading enabled, and MultiQC collections always run inline
    #: (there is no Delta table to read). An older server drops this field via
    #: extra="ignore" and answers synchronously — which is why the client
    #: contract is "no job_id means the work is already done" rather than a
    #: version check.
    async_mode: bool = False
