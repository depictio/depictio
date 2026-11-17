"""``<scheme>://<bucket>/<key>`` locations, for every registered backend."""

from __future__ import annotations

from typing import NamedTuple

from depictio.models.storage.registry import object_schemes


class ObjectURL(NamedTuple):
    scheme: str
    bucket: str
    key: str


def _scheme_of(url: str) -> str | None:
    head, sep, _ = url.partition("://")
    return head.lower() if sep else None


def is_object_url(url: object, schemes: tuple[str, ...] | None = None) -> bool:
    """Whether ``url`` is a location in an object store (any case of the scheme).

    ``schemes`` defaults to every registered backend's. A URL with no bucket
    (``s3://``) is not one.
    """
    if not isinstance(url, str):
        return False
    scheme = _scheme_of(url.strip())
    if scheme is None or scheme not in (schemes or object_schemes()):
        return False
    return bool(url.strip()[len(scheme) + 3 :].split("/", 1)[0])


def split_object_url(url: str, schemes: tuple[str, ...] | None = None) -> ObjectURL:
    """``(scheme, bucket, key)`` of an object-store URL; ``ValueError`` otherwise.

    The scheme comes back lower-case; the key keeps its slashes, minus the one
    after the bucket.
    """
    value = url.strip()
    if not is_object_url(value, schemes):
        allowed = ", ".join(f"{s}://" for s in (schemes or object_schemes()))
        raise ValueError(f"not an object-store location ({allowed}): {url!r}")
    scheme = _scheme_of(value)
    assert scheme is not None
    bucket, _, key = value[len(scheme) + 3 :].partition("/")
    return ObjectURL(scheme, bucket, key)


def object_url(scheme: str, bucket: str, key: str = "") -> str:
    """``<scheme>://<bucket>/<key>``; just ``<scheme>://<bucket>`` with no key."""
    key = key.lstrip("/")
    return f"{scheme}://{bucket}/{key}" if key else f"{scheme}://{bucket}"
