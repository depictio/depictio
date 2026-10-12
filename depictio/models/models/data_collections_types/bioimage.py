"""Data-collection config for bioimages (microscopy and spatial images).

A `bioimage` DC is file-backed, and its ``format`` says what each store is:

* ``ome-zarr``: a directory named ``*.zarr`` holding one NGFF image. Keys
  (``.zattrs`` / ``zarr.json``, chunks, shards) are served as they are on
  disk, with HTTP Range for sharded (zarr v3) arrays.
* ``spatialdata``: a SpatialData store (a ``*.zarr`` directory). Only the
  image element at ``image_path`` (e.g. ``images/he``) is shown, and it is an
  NGFF image itself, so it is served like an OME-Zarr store rooted at
  ``<store>/<image_path>``. The CLI uploads that subtree only.
* ``ome-tiff``: one pyramidal ``*.ome.tif(f)`` (or plain ``*.tif(f)``) file, read by the
  viewer with HTTP Range requests.
* ``tiff``: one plain ``*.tif`` / ``*.tiff`` segmentation mask (``kind:
  labels`` only), the form most segmentation tools write. The CLI converts it
  at ingest to a multiscale OME-Zarr (NGFF 0.4) labels image and uploads that
  under the store's S3 prefix, so the API serves it as a key tree named after
  the TIFF (``<sample>_mask.tif/.zattrs``). Upload is required: there is no
  converted copy on disk for the API to fall back to.

``kind`` says what the pixels are: ``image`` (intensities, the default) or
``labels`` (a segmentation mask: one integer per cell, 0 = background). A
labels store is drawn over the image store of the same sample, so both DCs
must name their stores so that they yield the same sample name; that is what
``sample_pattern`` is for (``^(.+?)_mask\\.tif$``).

Where a store lives:

* Local stores are registered by the scanner, ONE File document per store
  (``file_location`` = the store directory or TIFF file). The CLI uploads them
  to S3 (``bioimage_s3_prefix`` for key trees, ``bioimage_s3_object_key`` for
  a TIFF); the backend serves them from there, falling back to the registered
  path on disk for reference-only DCs (``upload: false``).
* ``remote_stores`` are read in place, never copied: ``s3://bucket/...`` on
  the server's own S3 endpoint, or ``https://host/...``. Both are off until
  the operator allow-lists the bucket or host (``settings.bioimage``); the API
  proxies every read, so the browser only ever talks to Depictio.

OME-Zarr and SpatialData images may be NGFF 0.4 (zarr v2: ``.zattrs``,
``.zarray``) or NGFF 0.5 (zarr v3: ``zarr.json`` with the metadata under
``attributes.ome``, chunks possibly sharded).
"""

from __future__ import annotations

import posixpath
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

BioimageFormat = Literal["ome-zarr", "ome-tiff", "spatialdata", "tiff"]
# ``image`` stores are shown as pixels; ``labels`` stores are segmentation masks
# (one integer per cell, 0 = background) drawn over the image of the same sample.
BioimageKind = Literal["image", "labels"]

OME_ZARR_STORE_SUFFIX = ".zarr"
OME_TIFF_SUFFIXES = (".ome.tiff", ".ome.tif")
TIFF_SUFFIXES = (".tiff", ".tif")
# Formats a labels DC accepts: an NGFF labels image, or a plain mask TIFF
# converted to one at ingest.
LABELS_FORMATS = ("tiff", "ome-zarr")

# Schemes a remote store URL may use; the host / bucket allow-list is a server
# setting, checked at read time (see ``settings.bioimage``).
REMOTE_STORE_SCHEMES = ("s3", "https")


def bioimage_store_suffixes(fmt: str) -> tuple[str, ...]:
    """Name suffixes a store of ``fmt`` must carry.

    An OME-TIFF may be named plain ``*.tif(f)`` (nf-core molkart writes its
    CLAHE pyramid so): ingest checks the OME-XML header, not the name.
    """
    if fmt == "ome-tiff":
        return (*OME_TIFF_SUFFIXES, *TIFF_SUFFIXES)
    if fmt == "tiff":
        return TIFF_SUFFIXES
    return (OME_ZARR_STORE_SUFFIX,)


def is_bioimage_store_name(name: str, fmt: str = "ome-zarr") -> bool:
    """A single path segment named like a store of ``fmt`` (no separators, no dot-dot)."""
    if not name or "/" in name or "\\" in name or "\x00" in name or ".." in name:
        return False
    return any(name.endswith(s) and name != s for s in bioimage_store_suffixes(fmt))


def is_single_file_format(fmt: str) -> bool:
    """Whether a store of ``fmt`` is served as one file (with Range) rather than a key tree.

    A ``tiff`` mask is one file on disk but a key tree once converted, so it
    is not: see ``is_file_store_format`` for the on-disk shape.
    """
    return fmt == "ome-tiff"


def is_file_store_format(fmt: str) -> bool:
    """Whether a local store of ``fmt`` is one file on disk (OME-TIFF, mask TIFF)
    rather than a ``*.zarr`` directory: what the scanner and the folder listing look for."""
    return fmt in ("ome-tiff", "tiff")


def bioimage_s3_prefix(dc_id: str, store_name: str | None = None) -> str:
    """Bucket-relative prefix a bioimage DC's stores are uploaded to, and read from.

    ``bioimage/{dc_id}/`` for the whole DC, ``bioimage/{dc_id}/{store_name}/``
    for one key-tree store (OME-Zarr, or a SpatialData image subtree). Kept out
    of the ``<dc_id>/`` prefix delta tables use: orphan cleanup deletes any
    ObjectId-shaped top-level prefix with no deltatable or MultiQC document,
    and a bioimage DC has neither. Shared by the CLI upload, the API read and
    the project cascade delete.
    """
    if store_name is None:
        return f"bioimage/{dc_id}/"
    return f"bioimage/{dc_id}/{store_name}/"


def bioimage_s3_object_key(dc_id: str, store_name: str) -> str:
    """Object key of a single-file store (OME-TIFF): ``bioimage/{dc_id}/{store_name}``."""
    return f"bioimage/{dc_id}/{store_name}"


def check_sample_pattern(pattern: str) -> str:
    """``pattern`` if it compiles with exactly one capture group, else a ValueError."""
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"sample_pattern {pattern!r} is not a valid regex: {e}") from e
    if compiled.groups != 1:
        raise ValueError(
            f"sample_pattern {pattern!r} must have exactly one capture group "
            f"(the sample name), found {compiled.groups}"
        )
    return pattern


def bioimage_sample_name(store_name: str, sample_pattern: str | None = None) -> str:
    """Sample name of a store.

    With ``sample_pattern``, its capture group searched in the store name
    (e.g. ``^(.+?)_mask\\.tif$`` turns ``s1_mask.tif`` into ``s1``); a name
    the pattern does not match, or an empty capture, falls back to the default.
    The default is the name without its store suffix (``.zarr``,
    ``.ome.tif(f)``, ``.tif(f)``).
    """
    name = store_name.rstrip("/")
    if sample_pattern:
        match = re.search(sample_pattern, name)
        if match and match.group(1):
            return match.group(1)
    for suffix in (*OME_TIFF_SUFFIXES, OME_ZARR_STORE_SUFFIX, *TIFF_SUFFIXES):
        if name.endswith(suffix) and name != suffix:
            return name[: -len(suffix)]
    return name


def duplicate_samples(
    store_names: list[str], sample_pattern: str | None = None
) -> dict[str, list[str]]:
    """Samples named by more than one store, with those stores.

    The viewer pairs an image with its labels, and a store with the points of
    its sample, by sample name, so two stores of one DC giving the same sample
    (``a.ome.tif`` and ``a.ome.tiff``, or two files the ``sample_pattern``
    folds together) are ambiguous.
    """
    by_sample: dict[str, list[str]] = {}
    for name in store_names:
        by_sample.setdefault(bioimage_sample_name(name, sample_pattern), []).append(name)
    return {sample: names for sample, names in by_sample.items() if len(set(names)) > 1}


def remote_store_name(url: str) -> str:
    """Store name of a remote store URL: the last path segment."""
    return posixpath.basename(urlparse(url).path.rstrip("/"))


def normalize_image_path(path: str) -> str:
    """Validated, store-relative SpatialData element path (``images/<name>``)."""
    raw = path.strip()
    if not raw or raw.startswith("/") or "\\" in raw or "\x00" in raw or ".." in raw.split("/"):
        raise ValueError(f"image_path must be a relative path inside the store, got {path!r}")
    normalized = posixpath.normpath(raw.rstrip("/"))
    if normalized in (".", ".."):
        raise ValueError(f"image_path must be a relative path inside the store, got {path!r}")
    return normalized


class DCBioimageConfig(BaseModel):
    """Config for a bioimage data collection."""

    format: BioimageFormat = "ome-zarr"
    kind: BioimageKind = "image"
    # Regex with one capture group applied to the store name, giving the sample
    # name when the file name carries more than the sample id (e.g.
    # ``^(.+?)_mask\\.tif$``). None: the store name without its suffix.
    sample_pattern: str | None = None
    # OME-Zarr and SpatialData images: the NGFF version the stores must have
    # ("0.4" = zarr v2, "0.5" = zarr v3). None accepts either, per store.
    ngff_version: Literal["0.4", "0.5"] | None = None
    # False = reference-only: the CLI validates the stores but skips the S3
    # upload, and the API serves them from the registered path on disk.
    upload: bool = True
    # SpatialData only: the image element to show, relative to the store root.
    image_path: str | None = None
    # Stores read in place (``s3://bucket/key`` or ``https://host/path``); the
    # last path segment is the store name, so it carries the format's suffix.
    remote_stores: list[str] = []

    model_config = ConfigDict(extra="forbid")

    @field_validator("sample_pattern")
    @classmethod
    def _check_sample_pattern(cls, v: str | None) -> str | None:
        return None if v is None else check_sample_pattern(v)

    @field_validator("image_path")
    @classmethod
    def _check_image_path(cls, v: str | None) -> str | None:
        return None if v is None else normalize_image_path(v)

    @field_validator("remote_stores")
    @classmethod
    def _check_remote_urls(cls, v: list[str]) -> list[str]:
        for url in v:
            parsed = urlparse(url)
            if parsed.scheme not in REMOTE_STORE_SCHEMES or not parsed.hostname:
                raise ValueError(
                    f"remote store {url!r} must be an s3:// or https:// URL with a bucket or host"
                )
            if parsed.query or parsed.fragment or parsed.username or parsed.password:
                raise ValueError(
                    f"remote store {url!r} must not carry credentials, a query or a fragment"
                )
            if ".." in parsed.path.split("/"):
                raise ValueError(f"remote store {url!r} must not contain '..'")
        return v

    @model_validator(mode="after")
    def _check_format_fields(self) -> DCBioimageConfig:
        if self.format == "spatialdata" and not self.image_path:
            raise ValueError("format 'spatialdata' needs image_path (e.g. 'images/<name>')")
        if self.format != "spatialdata" and self.image_path is not None:
            raise ValueError("image_path only applies to format 'spatialdata'")
        if self.kind == "labels" and self.format not in LABELS_FORMATS:
            raise ValueError(
                f"kind 'labels' takes format 'tiff' or 'ome-zarr', not {self.format!r}"
            )
        if self.format == "tiff":
            if self.kind != "labels":
                raise ValueError(
                    "format 'tiff' is for segmentation masks: set kind 'labels' "
                    "(images use 'ome-tiff' or 'ome-zarr')"
                )
            if not self.upload:
                raise ValueError(
                    "format 'tiff' needs upload: a mask TIFF is converted to OME-Zarr "
                    "at ingest and served from S3, so it cannot be reference-only"
                )
            if self.remote_stores:
                raise ValueError(
                    "format 'tiff' cannot use remote_stores: a mask TIFF is converted "
                    "at ingest, and remote stores are read in place"
                )
        names = [remote_store_name(url) for url in self.remote_stores]
        for url, name in zip(self.remote_stores, names):
            if not is_bioimage_store_name(name, self.format):
                suffixes = " or ".join(bioimage_store_suffixes(self.format))
                raise ValueError(
                    f"remote store {url!r} must end in {suffixes} for format {self.format!r}"
                )
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"remote stores share a name: {', '.join(duplicates)}")
        shared = duplicate_samples(names, self.sample_pattern)
        if shared:
            raise ValueError(f"remote stores share a sample: {', '.join(sorted(shared))}")
        return self
