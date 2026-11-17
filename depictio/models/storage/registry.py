"""Backends by configuration name, and the URL schemes they store."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from depictio.models.storage.base import StorageBackend

_BACKENDS: dict[str, type[StorageBackend]] = {}


def register_backend(cls: type[StorageBackend]) -> type[StorageBackend]:
    """Class decorator: make ``cls`` selectable as ``DEPICTIO_STORAGE_BACKEND=<cls.name>``."""
    existing = _BACKENDS.get(cls.name)
    if existing is not None and existing is not cls:
        raise ValueError(f"storage backend '{cls.name}' is already registered by {existing!r}")
    if any(b.scheme == cls.scheme and b is not cls for b in _BACKENDS.values()):
        raise ValueError(f"URL scheme '{cls.scheme}' is already served by another backend")
    _BACKENDS[cls.name] = cls
    return cls


def backend_class(name: str) -> type[StorageBackend]:
    """The backend registered as ``name``; ``ValueError`` naming the known ones otherwise."""
    try:
        return _BACKENDS[name]
    except KeyError:
        known = ", ".join(sorted(_BACKENDS)) or "none"
        raise ValueError(f"unknown storage backend '{name}' (known: {known})") from None


def backend_names() -> tuple[str, ...]:
    return tuple(sorted(_BACKENDS))


def object_schemes() -> tuple[str, ...]:
    """Every scheme a stored location may carry, from the registered backends."""
    return tuple(sorted({b.scheme for b in _BACKENDS.values()}))
