"""
Template data validator for depictio-cli.

Validates that a user's data root directory matches the expected structure
defined in a template's metadata (pre-flight check at Step 0):

- data_root directory exists and is accessible
- expected_files are present at their declared relative paths
- expected_directories exist (with glob expansion for wildcard patterns)

Usage:
    result = validate_data_root(template_metadata, "/path/to/data")
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
) -> ValidationResult:
    """Validate user's data root against template expectations.

    Checks:
    - data_root directory exists and is accessible
    - Expected files exist at their relative paths
    - Expected directories exist (with glob expansion for wildcard patterns)

    Recipe source files are NOT checked here — they are validated automatically
    by the 4-checkpoint recipe pipeline during Step 5 (process).

    Args:
        template_metadata: Template metadata with expected structure.
        data_root: Absolute path to user's data root directory.

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

    valid = len(errors) == 0
    return ValidationResult(valid=valid, errors=errors, warnings=warnings)
