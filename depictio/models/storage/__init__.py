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
from depictio.models.storage.factory import (
    BackendStorageOptions,
    check_instance_storage,
    cli_storage_fields,
    instance_polars_options,
    instance_storage,
    require_s3_instance,
)
from depictio.models.storage.gcs import GCSBackend
from depictio.models.storage.obstore_backend import ObstoreBackend
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
    "BackendStorageOptions",
    "ObjectInfo",
    "GCSBackend",
    "ObjectURL",
    "ObstoreBackend",
    "S3Backend",
    "StorageBackend",
    "StorageError",
    "StorageNotFound",
    "backend_class",
    "backend_names",
    "check_instance_storage",
    "cli_storage_fields",
    "instance_polars_options",
    "instance_storage",
    "is_object_url",
    "object_schemes",
    "object_url",
    "register_backend",
    "require_s3_instance",
    "split_object_url",
]
