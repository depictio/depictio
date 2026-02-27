"""
Template data validator for depictio-cli.

Validates that a user's data root directory matches the expected structure
defined in a template's metadata. Supports two validation levels:

- Level 1 (default): Check directory exists, expected files/directories present
- Level 2 (--deep):  Also read file headers to verify column names match

Usage:
    result = validate_data_root(template_metadata, "/path/to/data")
    result = validate_data_root(template_metadata, "/path/to/data", deep=True)
"""

from pathlib import Path

from pydantic import BaseModel, Field

from depictio.cli.cli_logging import logger
from depictio.models.models.templates import TemplateMetadata


class ValidationResult(BaseModel):
    """Result of validating user data against a template's expected structure."""

    valid: bool = Field(..., description="Whether validation passed")
    errors: list[str] = Field(
        default_factory=list, description="Critical errors that prevent usage"
    )
    warnings: list[str] = Field(default_factory=list, description="Non-critical warnings")


def validate_data_root(
    template_metadata: TemplateMetadata,
    data_root: str,
    deep: bool = False,
) -> ValidationResult:
    """Validate user's data root against template expectations.

    Level 1 (always):
    - data_root directory exists and is accessible
    - Expected files exist at their relative paths
    - Expected directories exist (with glob expansion for wildcard patterns)

    Level 2 (when deep=True):
    - Read TSV/CSV headers and check expected columns exist
    - Check parquet schema for expected columns

    Args:
        template_metadata: Template metadata with expected structure.
        data_root: Absolute path to user's data root directory.
        deep: Whether to enable Level 2 schema validation.

    Returns:
        ValidationResult with errors and warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []
    root = Path(data_root)

    # Level 1: Check data_root exists
    if not root.exists():
        errors.append(f"Data root directory does not exist: {data_root}")
        return ValidationResult(valid=False, errors=errors, warnings=warnings)

    if not root.is_dir():
        errors.append(f"Data root is not a directory: {data_root}")
        return ValidationResult(valid=False, errors=errors, warnings=warnings)

    # Level 1: Check expected files
    for expected_file in template_metadata.expected_files:
        file_path = root / expected_file.relative_path
        if not file_path.exists():
            errors.append(
                f"Expected file not found: {expected_file.relative_path} "
                f"({expected_file.description})"
            )
        elif not file_path.is_file():
            errors.append(f"Expected file is not a regular file: {expected_file.relative_path}")
        else:
            logger.debug(f"Found expected file: {expected_file.relative_path}")

    # Level 1: Check expected directories
    for expected_dir in template_metadata.expected_directories:
        if expected_dir.glob_pattern:
            # Use glob to find matching directories
            matches = list(root.glob(expected_dir.relative_path))
            if not matches:
                warnings.append(
                    f"No directories matching pattern '{expected_dir.relative_path}' found "
                    f"({expected_dir.description}). "
                    "This may be expected if no sequencing runs are available yet."
                )
            else:
                logger.debug(
                    f"Found {len(matches)} directories matching: {expected_dir.relative_path}"
                )
        else:
            dir_path = root / expected_dir.relative_path
            if not dir_path.exists():
                errors.append(
                    f"Expected directory not found: {expected_dir.relative_path} "
                    f"({expected_dir.description})"
                )
            elif not dir_path.is_dir():
                errors.append(
                    f"Expected directory is not a directory: {expected_dir.relative_path}"
                )

    # Level 2: Deep schema validation
    if deep:
        for expected_file in template_metadata.expected_files:
            if not expected_file.columns:
                continue

            file_path = root / expected_file.relative_path
            if not file_path.exists():
                continue  # Already reported in Level 1

            column_errors = _validate_file_columns(
                file_path=file_path,
                expected_columns=expected_file.columns,
                file_format=expected_file.format,
                relative_path=expected_file.relative_path,
            )
            errors.extend(column_errors)

    valid = len(errors) == 0
    return ValidationResult(valid=valid, errors=errors, warnings=warnings)


def _validate_file_columns(
    file_path: Path,
    expected_columns: list[str],
    file_format: str | None,
    relative_path: str,
) -> list[str]:
    """Validate that a file contains expected columns.

    Supports TSV, CSV, and Parquet formats.

    Args:
        file_path: Absolute path to the file.
        expected_columns: List of column names expected in the file.
        file_format: File format hint ('TSV', 'CSV', 'parquet').
        relative_path: Relative path for error messages.

    Returns:
        List of error strings (empty if all columns found).
    """
    errors: list[str] = []

    try:
        import polars as pl

        fmt = (file_format or "").upper()

        if fmt == "TSV":
            df = pl.read_csv(file_path, separator="\t", n_rows=0)
        elif fmt == "CSV":
            df = pl.read_csv(file_path, n_rows=0)
        elif fmt in ("PARQUET", ""):
            if file_path.suffix == ".parquet":
                df = pl.read_parquet(file_path, n_rows=0)
            elif file_path.suffix in (".tsv", ".txt"):
                df = pl.read_csv(file_path, separator="\t", n_rows=0)
            elif file_path.suffix == ".csv":
                df = pl.read_csv(file_path, n_rows=0)
            else:
                logger.warning(
                    f"Cannot determine format for {relative_path}, skipping column check"
                )
                return errors
        else:
            logger.warning(f"Unsupported format '{file_format}' for {relative_path}, skipping")
            return errors

        actual_columns = set(df.columns)
        missing = [col for col in expected_columns if col not in actual_columns]

        if missing:
            errors.append(
                f"File '{relative_path}' is missing expected columns: {', '.join(missing)}. "
                f"Found columns: {', '.join(sorted(actual_columns))}"
            )

    except ImportError:
        logger.warning("polars not available, skipping deep column validation")
    except Exception as e:
        errors.append(f"Error reading '{relative_path}' for column validation: {e}")

    return errors
