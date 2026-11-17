"""The contract every instance storage backend fulfils."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable


@dataclass(frozen=True)
class ObjectInfo:
    """One stored object, as a listing or a ``head`` reports it."""

    key: str
    size: int
    etag: str = ""
    last_modified: datetime | None = None


class StorageError(Exception):
    """A storage operation failed.

    ``code`` is the backend's own error code when it gave one (``AccessDenied``,
    ``SlowDown``, ...), for logs; callers must not branch on it.
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class StorageNotFound(StorageError, FileNotFoundError):
    """The object (or the bucket) does not exist.

    Also a ``FileNotFoundError``, as ``DataRoot.read_bytes`` raises, so code that
    reads either a data root or the instance store handles one exception.
    """


@runtime_checkable
class StorageBackend(Protocol):
    """The instance's own bucket.

    Keys are relative to the bucket, without a leading slash. Method names
    follow ``DataRoot`` (``cli/cli/utils/data_root.py``) where they overlap.
    """

    name: ClassVar[str]
    """Configuration name: the value of ``DEPICTIO_STORAGE_BACKEND``."""

    scheme: ClassVar[str]
    """URL scheme of the locations this backend stores (``s3``, ``gs``)."""

    bucket: str

    def __init__(self, config: Any, *, fail_fast: bool = False) -> None:
        """Build from the backend's configuration section (``settings.<name>`` /
        ``CLIConfig.<name>_storage``). ``fail_fast``: short timeouts, few retries."""
        ...

    # -- addresses ---------------------------------------------------------

    def url(self, key: str = "") -> str:
        """The stored location of ``key``: ``<scheme>://<bucket>/<key>``."""
        ...

    def key_of(self, location: str) -> str | None:
        """The key of ``location`` when it lies in this bucket, else None."""
        ...

    # -- reads -------------------------------------------------------------

    def list_objects(self, prefix: str = "") -> Iterator[ObjectInfo]:
        """Every object whose key starts with ``prefix``, paginated lazily."""
        ...

    def head(self, key: str) -> ObjectInfo | None:
        """Metadata of ``key``, or None when it does not exist."""
        ...

    def read_bytes(self, key: str) -> bytes:
        """Contents of ``key``; :class:`StorageNotFound` when it is absent."""
        ...

    def read_range(self, key: str, start: int, end: int) -> bytes:
        """Bytes ``[start, end)`` of ``key``."""
        ...

    # -- writes ------------------------------------------------------------

    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None: ...

    def upload_file(self, key: str, path: str | Path, *, content_type: str | None = None) -> None:
        """Upload a local file (multipart when the backend needs it)."""
        ...

    def delete_keys(self, keys: Iterable[str]) -> list[Any]:
        """Delete ``keys``; return the per-key errors the store reported."""
        ...

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object under ``prefix``; return how many were listed."""
        ...

    # -- bucket ------------------------------------------------------------

    def bucket_exists(self) -> bool: ...

    def ensure_bucket(self) -> bool:
        """Make sure the bucket exists; True when this call created it."""
        ...

    # -- handing the store to other libraries ------------------------------

    def presign_get(self, key: str, expires_in: int) -> str:
        """A GET URL for ``key`` that a browser can use for ``expires_in`` seconds."""
        ...

    def storage_options(self) -> dict[str, str]:
        """Options for Polars and delta-rs (``storage_options=``) on this store."""
        ...

    def filesystem(self) -> Any:
        """An fsspec filesystem on this store, for libraries that need one."""
        ...
