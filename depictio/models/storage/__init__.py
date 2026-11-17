"""The instance's own object storage, behind one interface.

Everything the server and the CLI write for themselves (Delta tables, MultiQC
reports, images, GeoJSON, indexed files, caches) goes through a
:class:`StorageBackend`. Which backend serves an instance comes from its
configuration (:func:`instance_storage`); the stored locations carry the
backend's scheme (``s3://bucket/key``).

Adding a backend means one module here that registers itself with
:func:`register_backend`: callers outside this package never branch on the
backend, and the schemes the validators accept come from the registry.

Remote reads of user-supplied locations (run folders, project storage,
allowlisted buckets) are not this package's concern: see ``s3_access``.
"""

from depictio.models.storage.base import (
    ObjectInfo,
    StorageBackend,
    StorageError,
    StorageNotFound,
)
from depictio.models.storage.factory import instance_storage
from depictio.models.storage.registry import (
    backend_class,
    backend_names,
    object_schemes,
    register_backend,
)
from depictio.models.storage.s3 import S3Backend
from depictio.models.storage.uri import (
    ObjectURL,
    is_object_url,
    object_url,
    split_object_url,
)

__all__ = [
    "ObjectInfo",
    "ObjectURL",
    "S3Backend",
    "StorageBackend",
    "StorageError",
    "StorageNotFound",
    "backend_class",
    "backend_names",
    "instance_storage",
    "is_object_url",
    "object_schemes",
    "object_url",
    "register_backend",
    "split_object_url",
]
