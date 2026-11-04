"""Provenance and publication records carried by a project.

Every field here is written by the server only. The API strips them from
create/update payloads (``SERVER_OWNED_PROJECT_FIELDS`` in
``projects_endpoints/provenance.py``) and an import never takes them from the
bundle as-is: it appends to the provenance chain and decides the lock itself.

Timestamps are naive UTC strings (``utc_now_str``), like ``registration_time``,
so a project round-trips through a JSON bundle without any datetime parsing.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from depictio.models.timestamps import utc_now_str

#: Shape of a migrate bundle (``bundle.json`` + ``migrate_metadata.json``).
#: Bumped only when the bundle layout changes, independently of the app version.
#: Bundles that carry no ``bundle_format_version`` are format 1.
BUNDLE_FORMAT_VERSION = 2


def _as_str(value: Any) -> Any:
    """An id stored as an ObjectId, read back as the string these records hold.

    A backup restore (and the bundle import) turns every ObjectId-shaped string
    of a document back into an ObjectId, including the ids kept here.
    """
    return value if value is None or isinstance(value, str) else str(value)


#: A string id that tolerates an ObjectId in the stored document.
IdStr = Annotated[str, BeforeValidator(_as_str)]


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
    migration_request_id: IdStr | None = None
    via: Literal["push", "cli", "zip"] = "cli"
    # Dashboards this import wrote. The next import of the same lineage deletes
    # the ones it no longer carries, and leaves every other dashboard of the
    # project (a visitor's copy) alone.
    dashboard_ids: list[IdStr] = []


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
    locked_by_id: IdStr | None = None
    locked_by_email: str | None = None
    reason: str | None = None
    source: Literal["migration", "admin"] = "admin"
    migration_request_id: IdStr | None = None
    dashboard_ids: list[IdStr] = []


# ---------------------------------------------------------------------------
# Server-to-server push (#1303)
# ---------------------------------------------------------------------------

#: How the data of a pushed project reaches the target's bucket.
#: ``inline``: the objects travel inside the bundle and the target writes them.
#: ``server_side_copy``: both instances share one S3 endpoint; the bundle only
#: carries a manifest (key, size, etag) and the target copies each object from
#: the source bucket with its own credentials. The source never holds the
#: target's write keys either way.
TransferMode = Literal["inline", "server_side_copy"]

#: Lifecycle of an inbound request on the target.
#: pending -> importing -> imported | failed; pending -> rejected | expired;
#: a newer request for the same project and source turns an older pending one
#: ``superseded``.
MigrationRequestStatus = Literal[
    "pending", "importing", "imported", "rejected", "failed", "expired", "superseded"
]

MIGRATION_REQUEST_OPEN_STATES: frozenset[str] = frozenset({"pending", "importing"})


class MigrationRequester(BaseModel):
    """Who asked for the push, as the source asserts it.

    Not verified by the target: the pairing key authenticates the instance,
    not the person. The admin who approves sees it, and ownership by email is
    claimed only through SSO or an admin-provisioned account.
    """

    model_config = ConfigDict(extra="ignore")

    email: str | None = None
    name: str | None = None
    source_user_id: IdStr | None = None


class MigrationDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: Literal["approve", "reject"]
    by_id: IdStr | None = None
    by_email: str | None = None
    at: str = Field(default_factory=utc_now_str)
    lock: bool | None = None
    make_public: bool | None = None
    reason: str | None = None


class MigrationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: IdStr | None = None
    owner_id: IdStr | None = None
    #: Set when the requester has no account here yet: the approving admin owns
    #: the project until this email signs in through SSO.
    pending_owner_email: str | None = None
    locked: bool = False
    made_public: bool = False
    documents: dict[str, int] = {}
    s3_objects: int = 0
    error: str | None = None


class MigrationRequest(BaseModel):
    """One inbound push, stored in ``migration_requests`` on the target."""

    id: IdStr | None = Field(default=None, alias="_id")
    status: MigrationRequestStatus = "pending"
    #: The inbound source's configured name: taken from the pairing key that
    #: authenticated the upload, never from the request body.
    source_name: str
    source_instance: str | None = None
    source_depictio_version: str | None = None
    bundle_format_version: int | None = None
    requester: MigrationRequester = Field(default_factory=MigrationRequester)
    message: str | None = None
    project_id: IdStr | None = None
    project_name: str | None = None
    transfer_mode: TransferMode = "inline"
    #: Where the bundle waits for a decision: ``s3://<bucket>/<staging key>``.
    staging_key: str | None = None
    bundle_sha256: str | None = None
    bundle_bytes: int = 0
    #: ``BundleReport`` as computed at upload, recomputed on revalidate.
    report: dict[str, Any] = {}
    decision: MigrationDecision | None = None
    result: MigrationResult | None = None
    superseded_by: IdStr | None = None
    created_at: str = Field(default_factory=utc_now_str)
    updated_at: str = Field(default_factory=utc_now_str)

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


#: Lifecycle of an outbound push on the source.
MigrationPushStatus = Literal["building", "uploading", "submitted", "failed"]


class MigrationPush(BaseModel):
    """One outbound push, stored in ``migration_pushes`` on the source."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: IdStr | None = Field(default=None, alias="_id")
    status: MigrationPushStatus = "building"
    project_id: IdStr
    project_name: str | None = None
    target_id: str
    target_name: str | None = None
    requested_by_id: IdStr | None = None
    requested_by_email: str | None = None
    message: str | None = None
    transfer_mode: TransferMode = "inline"
    bundle_bytes: int = 0
    bundle_sha256: str | None = None
    #: The request id the target answered with (202).
    remote_request_id: str | None = None
    #: Last status read back from the target (``GET /inbound/requests/{id}``).
    remote_status: str | None = None
    error: str | None = None
    created_at: str = Field(default_factory=utc_now_str)
    updated_at: str = Field(default_factory=utc_now_str)
