"""Backends on ``obstore``: the Rust ``object_store`` that Polars and delta-rs embed.

One implementation of the whole :class:`StorageBackend` contract for any store
``obstore`` speaks (GCS today; Azure, or S3 itself, later). A subclass only says
how to build its store and how Polars / delta-rs must be configured to reach the
same bucket: :meth:`ObstoreBackend._make_store` and :meth:`storage_options`.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any, ClassVar, cast

from depictio.models.storage.base import ObjectInfo, StorageError, StorageNotFound
from depictio.models.storage.uri import object_url, split_object_url


def _not_found(exc: Exception) -> bool:
    """obstore raises the builtin ``FileNotFoundError`` for a missing object."""
    return isinstance(exc, FileNotFoundError)


def _wrap(exc: Exception, what: str) -> StorageError:
    cls = StorageNotFound if _not_found(exc) else StorageError
    return cls(f"{what}: {exc}", code=type(exc).__name__)


def _info(meta: Any) -> ObjectInfo:
    return ObjectInfo(
        key=meta["path"],
        size=int(meta.get("size") or 0),
        etag=(meta.get("e_tag") or "").strip('"'),
        last_modified=meta.get("last_modified"),
    )


class ObstoreBackend:
    """Shared ``obstore`` implementation; subclasses set ``name``, ``scheme`` and the store."""

    name: ClassVar[str]
    scheme: ClassVar[str]

    #: obstore's ``fsspec`` protocol name for this store (``gs``, ``az``, ...).
    fsspec_protocol: ClassVar[str]

    def __init__(self, config: Any, *, fail_fast: bool = False) -> None:
        self.config = config
        self.bucket: str = config.bucket
        self.fail_fast = fail_fast
        self._lock = threading.Lock()
        self._store: Any = None

    def __repr__(self) -> str:
        return f"{type(self).__name__}(bucket={self.bucket!r})"

    # -- what a subclass provides -------------------------------------------

    def _store_config(self) -> dict[str, Any]:
        """Config keys of the obstore store (the subclass's spelling, no prefix)."""
        raise NotImplementedError

    def _make_store(self) -> Any:
        raise NotImplementedError

    def _client_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if self.fail_fast:
            options.update(connect_timeout="3s", timeout="10s")
        return options

    def _retry_config(self) -> dict[str, Any] | None:
        if self.fail_fast:
            return {"max_retries": 1, "retry_timeout": timedelta(seconds=10)}
        return None

    @property
    def store(self) -> Any:
        """The ``obstore`` store, built once."""
        with self._lock:
            if self._store is None:
                self._store = self._make_store()
            return self._store

    # -- addresses -----------------------------------------------------------

    def url(self, key: str = "") -> str:
        return object_url(self.scheme, self.bucket, key)

    def key_of(self, location: str) -> str | None:
        try:
            parts = split_object_url(location, (self.scheme,))
        except ValueError:
            return None
        return parts.key if parts.bucket == self.bucket else None

    # -- reads ---------------------------------------------------------------

    def list_objects(self, prefix: str = "") -> Iterator[ObjectInfo]:
        """Objects whose key starts with ``prefix``, as S3's ``Prefix`` reads it.

        ``object_store`` lists by path segment (``a/b`` means the folder
        ``a/b/``), so a prefix that ends mid-name lists its folder and filters.
        """
        import obstore

        folder = prefix if prefix.endswith("/") or not prefix else prefix.rpartition("/")[0]
        try:
            for page in obstore.list(self.store, prefix=folder.rstrip("/") or None):
                for meta in page:
                    if meta["path"].startswith(prefix):
                        yield _info(meta)
        except Exception as exc:
            raise _wrap(exc, f"listing {self.url(prefix)}") from exc

    def list_folders(self, prefix: str = "") -> list[str]:
        import obstore

        try:
            listing = obstore.list_with_delimiter(self.store, prefix.rstrip("/") or None)
        except Exception as exc:
            raise _wrap(exc, f"listing folders of {self.url(prefix)}") from exc
        return [str(folder).rstrip("/") for folder in listing["common_prefixes"]]

    def head(self, key: str) -> ObjectInfo | None:
        import obstore

        try:
            return _info(obstore.head(self.store, key))
        except Exception as exc:
            if _not_found(exc):
                return None
            raise _wrap(exc, f"head {self.url(key)}") from exc

    def read_bytes(self, key: str) -> bytes:
        import obstore

        try:
            return bytes(obstore.get(self.store, key).bytes())
        except Exception as exc:
            raise _wrap(exc, f"reading {self.url(key)}") from exc

    def read_range(self, key: str, start: int, end: int) -> bytes:
        import obstore

        if end <= start:
            return b""
        try:
            return bytes(obstore.get_range(self.store, key, start=start, end=end))
        except Exception as exc:
            raise _wrap(exc, f"reading {self.url(key)}") from exc

    def iter_chunks(
        self,
        key: str,
        chunk_size: int = 1 << 16,
        *,
        start: int | None = None,
        end: int | None = None,
    ) -> Iterator[bytes]:
        import obstore

        options = None
        if start is not None or end is not None:
            options = {"range": {"offset": start or 0} if end is None else (start or 0, end)}
        try:
            result = obstore.get(self.store, key, options=cast(Any, options))
        except Exception as exc:
            raise _wrap(exc, f"reading {self.url(key)}") from exc
        return (bytes(chunk) for chunk in result.stream(min_chunk_size=chunk_size))

    # -- writes --------------------------------------------------------------

    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        import obstore

        attributes = {"Content-Type": content_type} if content_type else None
        try:
            obstore.put(self.store, key, data, attributes=attributes)
        except Exception as exc:
            raise _wrap(exc, f"writing {self.url(key)}") from exc

    def upload_file(
        self,
        key: str,
        path: str | Path,
        *,
        content_type: str | None = None,
        multipart: bool | None = None,
    ) -> None:
        import obstore

        attributes = {"Content-Type": content_type} if content_type else None
        try:
            # A Path is streamed, in parts once it is large enough.
            obstore.put(self.store, key, Path(path), attributes=attributes, use_multipart=multipart)
        except Exception as exc:
            raise _wrap(exc, f"uploading {path} to {self.url(key)}") from exc

    def delete_keys(self, keys: Iterable[str]) -> list[Any]:
        import obstore

        keys = list(keys)
        if not keys:
            return []
        try:
            obstore.delete(self.store, keys)
        except Exception as exc:
            raise _wrap(exc, f"deleting from {self.url()}") from exc
        return []

    def delete_prefix(self, prefix: str) -> int:
        keys = [obj.key for obj in self.list_objects(prefix)]
        if keys:
            self.delete_keys(keys)
        return len(keys)

    # -- bucket --------------------------------------------------------------

    def bucket_exists(self) -> bool:
        """Whether the bucket answers a listing (one page, at most one key)."""
        import obstore

        try:
            next(iter(obstore.list(self.store, chunk_size=1)), None)
            return True
        except Exception as exc:
            if _not_found(exc):
                return False
            raise _wrap(exc, f"checking bucket {self.bucket}") from exc

    def ensure_bucket(self) -> bool:
        """Check only: creating a bucket on these stores is the operator's choice."""
        if not self.bucket_exists():
            raise StorageNotFound(
                f"bucket {self.url()} does not exist; create it before starting Depictio"
            )
        return False

    def check(self, checks: Iterable[str] | None = None) -> None:
        wanted = set(checks) if checks is not None else {"bucket", "write"}
        failures: list[str] = []
        if "bucket" in wanted or "write" in wanted:
            try:
                if not self.bucket_exists():
                    failures.append(f"bucket {self.url()} does not exist")
            except StorageError as exc:
                failures.append(f"bucket {self.url()} is not readable: {exc}")
        if "write" in wanted and not failures:
            probe = ".depictio/write_test"
            try:
                self.put_bytes(probe, b"test")
                self.delete_keys([probe])
            except StorageError as exc:
                failures.append(f"bucket {self.url()} is not writable: {exc}")
        if failures:
            raise StorageError("; ".join(failures))

    # -- handing the store to other libraries --------------------------------

    def presign_get(self, key: str, expires_in: int) -> str:
        import obstore

        try:
            return obstore.sign(self.store, "GET", key, timedelta(seconds=expires_in))
        except Exception as exc:
            raise _wrap(exc, f"signing {self.url(key)}") from exc

    def storage_options(self) -> dict[str, str]:
        raise NotImplementedError

    def filesystem(self) -> Any:
        from obstore.fsspec import FsspecStore

        # The protocol is a per-subclass string; obstore types it as a literal.
        make: Any = FsspecStore
        return make(
            self.fsspec_protocol,
            config=self._store_config(),
            client_options=self._client_options() or None,
        )
