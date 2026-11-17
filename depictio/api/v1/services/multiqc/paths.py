"""MultiQC data-path normalization (extracted from depictio.dash.modules.multiqc_component.callbacks.core).

Used by the prerender celery tasks to resolve S3 vs local filesystem locations
before reading parquet inputs.
"""

import os

from depictio.api.v1.configs.logging_init import logger
from depictio.models.storage import is_object_url


def normalize_multiqc_paths(locations: list[str]) -> list[str]:
    """Normalize MultiQC data paths, supporting both S3 URIs and local filesystem paths."""
    if not locations:
        return []

    normalized = []
    for location in locations:
        if not location:
            continue
        if is_object_url(location):
            normalized.append(location)
        elif location.startswith("/"):
            if not os.path.exists(location):
                logger.error(f"Local file path does not exist: {location}")
            normalized.append(location)
        else:
            normalized.append(os.path.abspath(location))
    return normalized
