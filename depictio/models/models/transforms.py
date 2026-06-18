"""Pydantic models for the recipe/transform system."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class RecipeSource(BaseModel):
    """Declares one input source for a recipe."""

    ref: str  # Name used as key in sources dict passed to transform()
    path: str | None = None  # Relative path under data_dir (for file-based sources)
    glob_pattern: str | None = None  # Glob pattern for multi-file sources (e.g. "dir/*.csv")
    dc_ref: str | None = None  # Reference another DC by tag (for joined sources)
    format: str = "CSV"  # CSV, TSV, Parquet
    read_kwargs: dict | None = None  # Extra kwargs passed to polars read function
    optional: bool = False  # If True and dc_ref not resolvable, passes None to transform()

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
    """Override a recipe source binding in project.yaml.

    Repoints a recipe source at a different file without editing the recipe — used
    by route conditionals (e.g. nanopore) to point the same recipe at a divergent
    sub-workflow's output layout. Set ``path`` for single-file sources or
    ``glob_pattern`` for multi-file (glob) sources; exactly one is required.
    """

    path: str | None = None
    glob_pattern: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _exactly_one(self) -> SourceOverride:
        # Match the `is not None` selection the consumers use (deltatables.py,
        # recipes.resolve_sources) so an empty-string path can't disagree.
        if (self.path is None) == (self.glob_pattern is None):
            raise ValueError("SourceOverride requires exactly one of 'path' or 'glob_pattern'")
        return self


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
