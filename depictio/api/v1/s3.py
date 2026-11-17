"""The server's handles on its own bucket.

``instance_backend`` is the :class:`~depictio.models.storage.StorageBackend` of
the instance (``DEPICTIO_STORAGE_BACKEND``): every read and write of the
instance's own objects goes through it. ``polars_s3_config`` predates it: the
backend's Polars / delta-rs storage options, whatever the backend (#1358).
"""

from depictio.api.v1.configs.config import settings
from depictio.models.storage import instance_storage

instance_backend = instance_storage(settings)

polars_s3_config = instance_backend.storage_options()
