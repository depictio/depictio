"""The server's handles on its own bucket.

``instance_backend`` is the :class:`~depictio.models.storage.StorageBackend` of
the instance (``DEPICTIO_STORAGE_BACKEND``); new code uses it. The two module
attributes below predate it and are derived from it:

- ``polars_s3_config``: the backend's Polars / delta-rs storage options.
- ``s3_client``: the S3 backend's boto3 client, for the callers not yet moved
  onto the backend's methods (#1358).
"""

from depictio.api.v1.configs.config import settings
from depictio.models.storage import instance_storage

instance_backend = instance_storage(settings)

polars_s3_config = instance_backend.storage_options()

s3_client = instance_backend.client  # type: ignore[attr-defined]
