"""Resolving "which data should this render read?".

A render endpoint is told *what* to draw by the component's metadata and *when*
to draw it from by this module. Three sources, in order of precedence:

1. **Per-component override** — ``data_versions: {"<dc_id>": <delta_version>}``
   on the request. The finest grain: one component pinned to old data while
   the rest of the dashboard stays live, for comparing then against now
   side by side.

2. **Dashboard "as of" a stored version** — ``as_of_version: "<version_id>"``.
   Reads that version's ``DataCollectionStamp`` list and pins every collection
   to the Delta commit it was authored against. This is what makes a dashboard
   version genuinely reproducible rather than merely a saved layout: the
   components come back *and* so does the data they were drawn from.

3. **Nothing** — read current data. Every existing caller.

Two design choices worth stating, because both were tempting to get wrong:

**Unresolvable pins are reported, never hidden.** A collection a version cannot
pin (a stamp with ``version_kind: none``, or a collection added after the
version was taken) reads current data, and ``DataVersionPins.unresolved`` names
it with the reason. A render does not carry that list: the client asks
``POST /dashboards/data_version_status/{id}`` once per selection and badges the
tiles that still show current data, rather than every render repeating it. A
caller asking for "as of v3" and receiving today's numbers with no indication
is the exact failure this feature exists to prevent.

**Resolution is per collection, not per dashboard.** A dashboard mixing a Delta
table with a MultiQC parquet collection can pin the former and not the latter.
Reporting that honestly beats refusing the whole request or pretending both
travelled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.dashboards_endpoints import version_store, versioning


@dataclass
class DataVersionPins:
    """Which Delta commit each collection should be read at.

    ``pins`` holds only collections that resolved to a concrete commit;
    everything absent reads current data. ``unresolved`` maps a collection to
    the reason it could not be pinned, which ``data_version_status`` reports,
    so the client can badge what still shows live data rather than claim it
    all travelled.
    """

    pins: dict[str, int] = field(default_factory=dict)
    unresolved: dict[str, str] = field(default_factory=dict)
    #: The version id this came from, when resolved via ``as_of_version``.
    as_of_version_id: str | None = None
    #: Collections a request's ``data_versions`` explicitly kept live (``null``).
    kept_live: set[str] = field(default_factory=set)
    #: The ``as_of_version``'s own stamps, as stored.
    stamps: list[dict[str, Any]] = field(default_factory=list)

    def for_dc(self, dc_id: str) -> int | None:
        """The Delta commit to read for this collection, or None for current."""
        return self.pins.get(str(dc_id))

    @property
    def active(self) -> bool:
        return bool(self.pins) or bool(self.unresolved)


#: The reason a collection the dashboard reads is not pinned when the version
#: holds no stamp for it: it was added after the version was taken.
NOT_IN_VERSION = "not_in_version"


def stale_version_detail(version_id: Any) -> str:
    """The 400 detail for a request naming a version that no longer exists.

    Kept to one sentence of fixed shape on purpose: the editor recognises it
    (it starts with "Version" and says "no longer exists") to drop a
    time-travel selection whose version was deleted or pruned, rather than
    leaving every tile failing until the user clears it by hand.
    """
    return f"Version {version_id} no longer exists."


def foreign_version_detail(version_id: Any) -> str:
    """The 400 detail for a version of another dashboard family."""
    return f"Version {version_id} does not belong to this dashboard."


def check_version_family(record: dict[str, Any] | None, version_id: Any, dashboard: dict) -> None:
    """Raise ``ValueError`` unless ``record`` is a version of ``dashboard``'s family.

    One check for both halves of a time-travelling render (``as_of_version``
    for the data, ``definition_version`` for the definition), so the two can
    never disagree about which versions a dashboard may name.
    """
    if record is None:
        # A deleted version is a caller error, not a reason to serve current
        # data as though it were historical.
        raise ValueError(stale_version_detail(version_id))
    # Another family's version would pin this dashboard's collections to
    # commits stamped for a different dashboard: a render labelled "as of v3"
    # that is v3 of nothing on screen. It would also let a caller probe the
    # stamps of a dashboard they were never shown by pairing it with one they
    # can open. Same check, same reasoning, as the ``?version=`` preview in
    # ``routes._overlay_version``.
    family_id = versioning.resolve_family_id(dashboard)
    if family_id is None or record.get("family_id") != str(family_id):
        raise ValueError(foreign_version_detail(version_id))


def referenced_dc_ids(components: list[dict[str, Any]] | None) -> list[str]:
    """The data collections a list of components reads, in first-seen order."""
    seen: dict[str, None] = {}
    for component in components or []:
        if not isinstance(component, dict):
            continue
        dc_id = component.get("dc_id")
        if dc_id:
            seen.setdefault(str(dc_id), None)
    return list(seen)


def pins_from_stamps(
    stamps: list[dict[str, Any]], referenced: list[str] | None = None
) -> DataVersionPins:
    """Turn a stored version's data-collection stamps into read pins.

    A stamp only yields a pin when it recorded a Delta commit. Anything else —
    a manifest collection, an asset, a pre-provenance aggregation — is reported
    as unresolved with the stamp's own reason, which is already written for a
    human to read.

    ``referenced`` is what the dashboard reads now. A collection in it with no
    stamp at all was added after the version was taken; it reads current data
    and is reported as ``not_in_version`` rather than silently left out.
    """
    resolved = DataVersionPins()

    for stamp in stamps or []:
        if not isinstance(stamp, dict):
            continue
        dc_id = str(stamp.get("dc_id") or "")
        if not dc_id:
            continue

        delta_version = stamp.get("delta_version")
        if stamp.get("version_kind") == "delta" and isinstance(delta_version, int):
            resolved.pins[dc_id] = delta_version
        else:
            resolved.unresolved[dc_id] = str(stamp.get("reason") or "no_version_recorded")

    for dc_id in referenced or []:
        key = str(dc_id)
        if key not in resolved.pins and key not in resolved.unresolved:
            resolved.unresolved[key] = NOT_IN_VERSION

    return resolved


def _delta_version_or_error(dc_id: str, version: Any) -> int:
    """A ``data_versions`` value as a Delta commit, or ``ValueError``.

    A commit is a non-negative integer. ``int()`` alone would take ``True`` as
    commit 1, ``3.7`` as 3 and ``"3"`` as 3, and a negative one only failed
    later inside deltalake, as a 500 for a table and a silent null for a card.
    """
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise ValueError(
            f"data_versions[{dc_id}] must be a Delta commit number (an integer of 0 or "
            f"more) or null, not {version!r}."
        )
    return version


def resolve_data_versions(
    request: dict[str, Any] | None,
    *,
    dashboard: dict[str, Any] | None = None,
    referenced: list[str] | None = None,
) -> DataVersionPins:
    """Read the time-travel intent out of a render request body.

    Accepts both grains at once: ``as_of_version`` sets the baseline for the
    whole dashboard and ``data_versions`` overrides individual collections on
    top of it, which is what "pin this one component to older data" needs.

    ``dashboard`` is the document being rendered. When given, an
    ``as_of_version`` must belong to its tab family, and a collection it reads
    that the version holds no stamp for is reported as ``not_in_version``.
    Every render endpoint passes it (see ``routes._data_pins``); only unit
    tests of the stamp logic leave it out. ``referenced`` overrides the
    collections to report on, for a caller looking at a whole tab family.

    Raises ``ValueError`` (a 400 at every endpoint) for a version that no
    longer exists or belongs to another family, and for a ``data_versions``
    value that is not a commit number or null.
    """
    if not isinstance(request, dict):
        return DataVersionPins()

    resolved = DataVersionPins()

    as_of = request.get("as_of_version")
    if as_of:
        record = version_store.get_version(str(as_of))
        if record is None:
            raise ValueError(stale_version_detail(as_of))
        if dashboard is not None:
            check_version_family(record, as_of, dashboard)
        if referenced is None and dashboard is not None:
            referenced = referenced_dc_ids(dashboard.get("stored_metadata"))
        resolved = pins_from_stamps(record.get("data_collections") or [], referenced)
        resolved.as_of_version_id = str(as_of)
        resolved.stamps = list(record.get("data_collections") or [])

    overrides = request.get("data_versions")
    if overrides is not None and not isinstance(overrides, dict):
        raise ValueError("data_versions must map data collection ids to commit numbers.")
    for dc_id, version in (overrides or {}).items():
        key = str(dc_id)
        if version is None:
            # Explicit "this one stays live": drop any dashboard-level pin.
            resolved.pins.pop(key, None)
            resolved.unresolved.pop(key, None)
            resolved.kept_live.add(key)
            continue
        resolved.pins[key] = _delta_version_or_error(key, version)
        resolved.unresolved.pop(key, None)

    # Logged because "the picker does nothing" is indistinguishable, from the
    # server's side, between a client that never sent a pin and a server that
    # dropped one. One line naming the resolved pins turns a UI bug report into
    # a bisected one: no line at all means the request arrived unpinned.
    if resolved.active:
        logger.info(
            f"data time travel: as_of={resolved.as_of_version_id} "
            f"pins={resolved.pins} unresolved={resolved.unresolved}"
        )

    return resolved


def collection_statuses(
    pins: DataVersionPins,
    referenced: list[str],
    identities: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """What each collection shows under ``pins``, for the banners and tile badges.

    One entry per collection in ``referenced`` (what the family reads now) and
    per collection the ``as_of_version`` stamped (what its components read),
    each with a ``status``:

    * ``pinned``: read at ``delta_version``. An image collection's manifest
      travels but its pixels do not, which ``reason`` says.
    * ``live``: read as it is now. ``reason`` says why when time travel was
      asked for: ``not_in_version`` (added since), ``kept_live`` (a
      ``data_versions`` null), or the stamp's own reason.
    * ``not_versioned``: a collection with no Delta history at all (MultiQC,
      JBrowse, GeoJSON, phylogeny), always shown as it is now.

    ``identities`` maps a collection to its ``workflow_tag``,
    ``data_collection_tag`` and ``dc_type`` as the project holds them; a
    collection the project no longer holds falls back to its stamp.
    """
    stamps = {str(s.get("dc_id")): s for s in pins.stamps if isinstance(s, dict) and s.get("dc_id")}
    order = list(dict.fromkeys([*map(str, referenced), *stamps]))

    entries: list[dict[str, Any]] = []
    for dc_id in order:
        stamp = stamps.get(dc_id) or {}
        identity = identities.get(dc_id) or {}
        dc_type = str(identity.get("dc_type") or stamp.get("dc_type") or "")
        kind = versioning._classify_dc(dc_type)
        entry: dict[str, Any] = {
            "dc_id": dc_id,
            "workflow_tag": identity.get("workflow_tag") or stamp.get("workflow_tag") or "",
            "data_collection_tag": identity.get("data_collection_tag")
            or stamp.get("data_collection_tag")
            or "",
            "dc_type": dc_type,
            "status": "live",
            "delta_version": None,
            "reason": None,
        }
        if kind in ("manifest", "asset"):
            entry["status"] = "not_versioned"
            entry["reason"] = stamp.get("reason") or f"{kind}_versioning_not_enabled"
        elif pins.for_dc(dc_id) is not None:
            entry["status"] = "pinned"
            entry["delta_version"] = pins.for_dc(dc_id)
            if dc_type.lower() == "image":
                entry["reason"] = "image_pixels_not_versioned"
        elif dc_id in pins.kept_live:
            entry["reason"] = "kept_live"
        elif dc_id in pins.unresolved:
            entry["reason"] = pins.unresolved[dc_id]
        entries.append(entry)
    return entries
