"""Pydantic models for the recipe/transform system."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class RecipeSource(BaseModel):
    """Declares one input source for a recipe."""

    ref: str  # Name used as key in sources dict passed to transform()
    path: str | None = None  # Relative path under data_dir (for file-based sources)
    dc_ref: str | None = None  # Reference another DC by tag (for joined sources)
    format: str = "CSV"  # CSV, TSV, Parquet
    read_kwargs: dict | None = None  # Extra kwargs passed to polars read function

    model_config = ConfigDict(extra="forbid")

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        allowed = {"csv", "tsv", "parquet"}
        if v.lower() not in allowed:
            raise ValueError(f"format must be one of {sorted(allowed)}, got {v!r}")
        return v.lower()

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, v: str) -> str:
        if not v:
            raise ValueError("ref cannot be empty")
        return v


class SourceOverride(BaseModel):
    """Override a recipe source path in project.yaml."""

    path: str

    model_config = ConfigDict(extra="forbid")


class TransformConfig(BaseModel):
    """Config for a transformed data collection in project.yaml."""

    recipe: str  # Recipe name, e.g. "nf-core/ampliseq/alpha_diversity.py"
    source_overrides: dict[str, SourceOverride] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("recipe")
    @classmethod
    def validate_recipe(cls, v: str) -> str:
        if not v:
            raise ValueError("recipe path cannot be empty")
        if not v.endswith(".py"):
            raise ValueError("recipe must be a .py file")
        return v
