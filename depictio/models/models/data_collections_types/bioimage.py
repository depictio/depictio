"""Data-collection config for bioimages (microscopy and spatial images).

A `bioimage` DC is file-backed, and its ``format`` says what the files are.
Only ``ome-zarr`` exists so far: each store is a directory named ``*.zarr``
under the project's data_location, registered by the scanner as ONE File
document (``file_location`` = the store directory). The CLI uploads every
file of the store to S3 under ``bioimage_s3_prefix(dc_id, store_name)``; the
backend then serves individual zarr keys (``.zattrs``, ``.zarray``, chunks)
via the /advanced_viz/bioimage/{dc_id}/{store}/{key} endpoint, falling back
to the registered directory on disk for reference-only DCs (``upload: false``).

For OME-Zarr, only NGFF 0.4 (zarr v2 layout) is supported for now.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

# Image formats a bioimage DC can hold. Add a format here (e.g. "ome-tiff",
# "spatialdata") together with its scanner, CLI upload and viewer support.
BioimageFormat = Literal["ome-zarr"]

OME_ZARR_STORE_SUFFIX = ".zarr"


def bioimage_s3_prefix(dc_id: str, store_name: str | None = None) -> str:
    """Bucket-relative prefix a bioimage DC's stores are uploaded to, and read from.

    ``bioimage/{dc_id}/`` for the whole DC, ``bioimage/{dc_id}/{store_name}/``
    for one store. Kept out of the ``<dc_id>/`` prefix delta tables use:
    orphan cleanup deletes any ObjectId-shaped top-level prefix with no
    deltatable or MultiQC document, and a bioimage DC has neither. Shared by
    the CLI upload, the API read and the project cascade delete.
    """
    if store_name is None:
        return f"bioimage/{dc_id}/"
    return f"bioimage/{dc_id}/{store_name}/"


def bioimage_sample_name(store_name: str) -> str:
    """Sample name of a store: its basename without the ``.zarr`` suffix."""
    return store_name.rstrip("/").removesuffix(OME_ZARR_STORE_SUFFIX)


class DCBioimageConfig(BaseModel):
    """Config for a bioimage data collection."""

    format: BioimageFormat = "ome-zarr"
    # OME-Zarr only: the NGFF version of the stores.
    ngff_version: Literal["0.4"] = "0.4"
    # False = reference-only: the CLI validates the stores but skips the S3
    # upload, and the API serves chunks from the registered directory on disk.
    upload: bool = True

    model_config = ConfigDict(extra="forbid")
