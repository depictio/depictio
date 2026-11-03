"""Provenance and publication records carried by a project.

Every field here is written by the server only. The API strips them from
create/update payloads (``SERVER_OWNED_PROJECT_FIELDS`` in
``projects_endpoints/provenance.py``) and an import never takes them from the
bundle as-is: it appends to the provenance chain and decides the lock itself.

Timestamps are naive UTC strings (``utc_now_str``), like ``registration_time``,
so a project round-trips through a JSON bundle without any datetime parsing.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from depictio.models.timestamps import utc_now_str

#: Shape of a migrate bundle (``bundle.json`` + ``migrate_metadata.json``).
#: Bumped only when the bundle layout changes, independently of the app version.
#: Bundles that carry no ``bundle_format_version`` are format 1.
BUNDLE_FORMAT_VERSION = 2


class ImportHop(BaseModel):
    """One import of this project into an instance.

    A project that travelled A -> B -> C carries two hops, oldest first. No
    requester email: the project document is readable on public projects; the
    request that brought it here keeps that.
    """

    model_config = ConfigDict(extra="ignore")

    source_instance: str = "unknown"
    source_depictio_version: str | None = None
    bundle_format_version: int | None = None
    exported_at: str | None = None
    imported_at: str = Field(default_factory=utc_now_str)
    target_depictio_version: str = "unknown"
    bundle_sha256: str | None = None
    migration_request_id: str | None = None
    via: Literal["push", "cli", "zip"] = "cli"
    # Dashboards this import wrote. The next import of the same lineage deletes
    # the ones it no longer carries, and leaves every other dashboard of the
    # project (a visitor's copy) alone.
    dashboard_ids: list[str] = []


class ProjectProvenance(BaseModel):
    """Which Depictio produced this project, and how it got here."""

    model_config = ConfigDict(extra="ignore")

    # None on projects created before version tracking existed.
    created_with_version: str | None = None
    imported_from: list[ImportHop] = []


class PublishedLock(BaseModel):
    """A project frozen read-only on this instance.

    ``dashboard_ids`` are the dashboards published with it: a visitor's copy of
    a public dashboard lives in the same project but is not part of the release,
    so it stays editable by its owner.
    """

    model_config = ConfigDict(extra="ignore")

    locked_at: str = Field(default_factory=utc_now_str)
    locked_by_id: str | None = None
    locked_by_email: str | None = None
    reason: str | None = None
    source: Literal["migration", "admin"] = "admin"
    migration_request_id: str | None = None
    dashboard_ids: list[str] = []
