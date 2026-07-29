"""One generation of a single-blob data collection.

GeoJSON and phylogeny are the two data collection families that are neither a
Delta table nor a set of content-addressed objects: each is *one* opaque file.
GeoJSON wrote it to a single fixed key and overwrote it in place, so the
previous content was unrecoverable. Phylogeny was never uploaded at all — the
CLI recorded the path on the machine that ran the scan, which the container
frequently cannot read.

Content addressing fixes both at once. Each upload lands at
``{dc_id}/versions/{sha256}/{filename}``, so a PUT is idempotent, a re-upload of
identical bytes is free, and a version that pins a digest resolves to exactly
the bytes it was authored against — with no bucket versioning, which would
otherwise have to retain every Delta table's churn too.

Mirrors ``DeltaTableAggregated.aggregation``: a monotonic list where the last
entry is current. Both parent configs are ``extra="forbid"``, so every field
defaults and the list defaults to empty — a config written before this existed
still validates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AssetVersion(BaseModel):
    """One uploaded generation of a single-file data collection."""

    #: Full sha256 of the file's bytes — not truncated, and not
    #: ``File.file_hash`` (which digests *metadata*, so a touch reads as a
    #: change and a rewrite with matching metadata is invisible). This is the
    #: address, so it has to be the real thing.
    digest: str = Field(default="", description="Full sha256 of the file contents")

    #: ``s3://{bucket}/{dc_id}/versions/{digest}/{filename}``.
    s3_location: str = Field(default="", description="Where this generation lives")

    filename: str = Field(default="", description="Original file name, for display and download")
    size_bytes: Optional[int] = Field(default=None, description="Size of the uploaded file")

    #: Monotonic per collection, starting at 1. Ordering by this rather than by
    #: timestamp keeps it correct under clock skew between writers.
    generation: int = Field(default=1, description="Monotonic upload counter")

    uploaded_at: datetime = Field(
        default_factory=datetime.now, description="When this generation was uploaded"
    )
    #: The path the file was read from at upload time. Recorded for provenance
    #: only — it is frequently a path on the operator's own machine, which is
    #: precisely why the bytes are now uploaded rather than referenced.
    source_path: Optional[str] = Field(default=None, description="Local path at upload time")

    model_config = ConfigDict(extra="forbid")

    def __repr__(self) -> str:
        return f"AssetVersion(gen={self.generation}, digest={self.digest[:12]}, {self.filename})"
