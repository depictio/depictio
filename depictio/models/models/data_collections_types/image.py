"""
Image Data Collection Type Configuration.

Image DCs work like Table DCs but with a mandatory image_column field that
specifies which column contains image paths. They create delta tables and
support all component types including the Image gallery component.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from depictio.models.config import DEPICTIO_CONTEXT

# Valid file formats for Image DC
VALID_FORMATS = ["csv", "tsv", "parquet", "feather", "xls", "xlsx", "mixed"]

# Default supported image extensions
DEFAULT_IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tiff"]


class DCImageConfig(BaseModel):
    """Configuration for Image data collection type.

    Image DCs extend Table DC functionality with a mandatory image column.
    They create delta tables and support all component types.
    """

    # Table DC fields (required for delta table creation)
    format: str = Field(description="File format: csv, tsv, parquet, feather, xls, xlsx, or mixed")
    polars_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional arguments for Polars read functions",
    )
    keep_columns: list[str] | None = Field(
        default=None,
        description="Columns to keep (None keeps all)",
    )
    columns_description: dict[str, str] | None = Field(
        default=None,
        description="Column descriptions",
    )

    # Image-specific fields
    image_column: str = Field(description="Column containing image paths (required)")
    s3_base_folder: str | None = Field(
        default=None,
        description="S3 base folder for images (paths in image_column are relative to this)",
    )
    local_images_path: str | None = Field(
        default=None,
        description=(
            "Local directory of the images, which `depictio ingest` uploads to "
            "s3_base_folder. A relative path is read from the current directory"
        ),
    )
    supported_formats: list[str] = Field(
        default_factory=lambda: DEFAULT_IMAGE_EXTENSIONS.copy(),
        description="Supported image file extensions",
    )
    thumbnail_size: int = Field(
        default=150,
        description="Default thumbnail size in pixels",
        ge=50,
        le=1000,
    )

    class Config:
        extra = "forbid"

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        """Validate and normalize the format field."""
        normalized = v.lower()
        if normalized not in VALID_FORMATS:
            raise ValueError(f"format must be one of {VALID_FORMATS}")
        return normalized

    @field_validator("image_column")
    @classmethod
    def validate_image_column(cls, v: str) -> str:
        """Ensure image_column is non-empty."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("image_column is required for Image DC type")
        return stripped

    @field_validator("supported_formats")
    @classmethod
    def validate_supported_formats(cls, v: list[str]) -> list[str]:
        """Normalize format extensions to lowercase with leading dot."""
        return [f".{fmt.lower().lstrip('.')}" for fmt in v]

    @field_validator("s3_base_folder")
    @classmethod
    def validate_s3_path(cls, v: str | None) -> str | None:
        """Validate S3 path format and ensure trailing slash."""
        if not v or not v.strip():
            return v
        if not v.startswith("s3://"):
            raise ValueError("s3_base_folder must start with 's3://'")
        return v if v.endswith("/") else f"{v}/"

    @model_validator(mode="after")
    def require_s3_base_folder_for_local_images(self) -> "DCImageConfig":
        """The CLI uploads local_images_path to s3_base_folder, and the dashboard reads
        the images from there, so one without the other has nowhere to go.

        Checked in the CLI only: the server never reads local_images_path, and must
        still load the collections stored before this rule.
        """
        if self.local_images_path and not self.s3_base_folder and DEPICTIO_CONTEXT.lower() == "cli":
            raise ValueError(
                "local_images_path is set but s3_base_folder is not: set s3_base_folder "
                "to the S3 folder the images are uploaded to and the paths in "
                f"'{self.image_column}' are relative to (e.g. s3://<bucket>/<project>/images/)"
            )
        return self
