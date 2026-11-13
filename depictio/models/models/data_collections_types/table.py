import posixpath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SpatialDataCoordinates = Literal["auto", "obsm", "region"]


def _element_path(value: str, group: str, field: str) -> str:
    """Validated SpatialData element path ``<group>/<name>`` (relative, no ``..``)."""
    raw = value.strip()
    if not raw or raw.startswith("/") or "\\" in raw or "\x00" in raw or ".." in raw.split("/"):
        raise ValueError(f"{field} must be a relative path inside the store, got {value!r}")
    parts = posixpath.normpath(raw.rstrip("/")).split("/")
    if len(parts) != 2 or parts[0] != group or parts[1] in ("", "."):
        raise ValueError(f"{field} must be '{group}/<name>', got {value!r}")
    return "/".join(parts)


class SpatialDataTableSource(BaseModel):
    """Where a ``spatialdata`` table DC reads its rows inside a SpatialData store.

    The AnnData table at ``table`` becomes one row per observation: its obs
    columns, ``x`` / ``y`` coordinates when available and one column per gene
    in ``genes``, pulled from ``X`` (or ``layers/<layer>``).
    """

    # AnnData element, relative to the store root.
    table: str = "tables/table"
    # Optional image element: x / y are then expressed in its level-0 pixels.
    image: str | None = None
    # auto: obsm["spatial"] when present, else the annotated region geometries.
    coordinates: SpatialDataCoordinates = "auto"
    # var names pulled from X (or `layer`), one column each.
    genes: list[str] = []
    # layers/<name> instead of X.
    layer: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("table")
    @classmethod
    def _check_table(cls, v: str) -> str:
        return _element_path(v, "tables", "table")

    @field_validator("image")
    @classmethod
    def _check_image(cls, v: str | None) -> str | None:
        return None if v is None else _element_path(v, "images", "image")

    @field_validator("layer")
    @classmethod
    def _check_layer(cls, v: str | None) -> str | None:
        if v is None:
            return None
        name = v.strip()
        if not name or "/" in name or "\\" in name or "\x00" in name or name in (".", ".."):
            raise ValueError(f"layer must be a plain layer name, got {v!r}")
        return name

    @field_validator("genes")
    @classmethod
    def _check_genes(cls, v: list[str]) -> list[str]:
        if any(not g.strip() for g in v):
            raise ValueError("genes must not contain empty names")
        duplicates = sorted({g for g in v if v.count(g) > 1})
        if duplicates:
            raise ValueError(f"genes listed more than once: {', '.join(duplicates)}")
        return v


class DCTableConfig(BaseModel):
    format: str
    polars_kwargs: dict[str, Any] = {}
    keep_columns: list[str] | None = []
    columns_description: dict[str, str] | None = {}
    # format "spatialdata" only: the AnnData table to read from each store.
    # Left out of dumps when unset, so other formats serialise as before.
    spatialdata: SpatialDataTableSource | None = Field(default=None, exclude_if=lambda v: v is None)
    # TODO: validate than the columns are in the dataframe

    class Config:
        extra = "forbid"  # Reject unexpected fields

    @field_validator("format")
    def validate_format(cls, v):
        allowed_values = ["csv", "tsv", "parquet", "feather", "xls", "xlsx", "spatialdata"]
        if v.lower() not in allowed_values:
            raise ValueError(f"format must be one of {allowed_values}")

        return v.lower()

    @model_validator(mode="after")
    def _check_spatialdata(self):
        if self.format == "spatialdata" and self.spatialdata is None:
            raise ValueError(
                "format 'spatialdata' needs a spatialdata block (e.g. table: tables/table)"
            )
        if self.format != "spatialdata" and self.spatialdata is not None:
            raise ValueError("spatialdata only applies to format 'spatialdata'")
        return self

    # TODO : check that the columns to keep are in the dataframe
    # @field_validator("keep_columns")
    # def validate_keep_fields(cls, v):
    #     if v is not None:
    #         if not isinstance(v, list):
    #             raise ValidationError("keep_columns must be a list")
    #     return v

    # # TODO: check polars different arguments
    # @field_validator("polars_kwargs")
    # def validate_pandas_kwargs(cls, v):
