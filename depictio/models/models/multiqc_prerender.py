"""MultiQC pre-render ledger model.

A small status doc per data collection that records whether the disk-persistent
pre-rendered figures (Phase 2) are current. The render endpoint consults this
to decide whether to read from disk, enqueue a build, or return 202.

Disk layout: ``<prerender_dir>/<dc_id>/<sha>.json.gz`` where ``<sha>`` is the
trailing 16-hex digest from ``_generate_figure_cache_key``. The doc only tracks
aggregate state — per-figure presence is determined by disk lookup.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

PrerenderStatus = Literal["pending", "building", "ready", "failed"]


class MultiQCPrerender(BaseModel):
    """Status ledger for a DC's pre-rendered figures.

    Stored in the ``multiqc_prerender`` collection, keyed by ``dc_id``.
    ``s3_locations_hash`` is the staleness signal — it hashes the sorted set of
    S3 locations for every MultiQC report in the DC; an upload/append/replace
    bumps it and the next build task rebuilds.
    """

    dc_id: str = Field(..., description="Data collection id this ledger tracks")
    s3_locations_hash: str = Field(
        default="",
        description="SHA-256 of the sorted s3_location set used for the current build",
    )
    status: PrerenderStatus = Field(
        default="pending", description="Lifecycle of the on-disk pre-rendered figures"
    )
    figure_count: int = Field(default=0, description="Number of figures successfully written")
    last_error: Optional[str] = Field(
        default=None, description="Most recent build failure message, if any"
    )
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        extra = "forbid"
