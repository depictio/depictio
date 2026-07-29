"""Re-export of the shared content-digest primitives.

The implementation lives in ``depictio.models`` because the CLI needs it too and
must not import from ``depictio.api`` — the CLI ships as its own package with
its own dependency set, and such an import would be the only one of its kind in
the tree. ``depictio/models`` is the tier both sides already share.

Kept as a module here so API code goes on importing from
``depictio.api.v1.services.content_digest``, which is where a reader looks.
"""

from depictio.models.content_digest import (  # noqa: F401
    ContentDigestMismatch,
    atomic_write,
    compute_bytes_sha256,
    compute_file_sha256,
    compute_stream_sha256,
    content_key,
    iter_file_chunks,
    read_sidecar,
    sidecar_path,
    verify_against_sidecar,
    write_sidecar,
)

__all__ = [
    "ContentDigestMismatch",
    "atomic_write",
    "compute_bytes_sha256",
    "compute_file_sha256",
    "compute_stream_sha256",
    "content_key",
    "iter_file_chunks",
    "read_sidecar",
    "sidecar_path",
    "verify_against_sidecar",
    "write_sidecar",
]
