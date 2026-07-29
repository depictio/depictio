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

**Unresolvable pins fail loudly.** If a version's stamp says ``version_kind:
none`` — no provenance recorded — we do not quietly serve current data under a
historical label. A caller asking for "as of v3" and receiving today's numbers
with no indication is the exact failure this feature exists to prevent. The
resolver reports which collections it could not pin so the endpoint can say so.

**Resolution is per collection, not per dashboard.** A dashboard mixing a Delta
table with a MultiQC parquet collection can pin the former and not the latter.
Reporting that honestly beats refusing the whole request or pretending both
travelled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.dashboards_endpoints import version_store


@dataclass
class DataVersionPins:
    """Which Delta commit each collection should be read at.

    ``pins`` holds only collections that resolved to a concrete commit;
    everything absent reads current data. ``unresolved`` maps a collection to
    the reason it could not be pinned, so the response can carry a warning
    rather than silently degrading to live data.
    """

    pins: dict[str, int] = field(default_factory=dict)
    unresolved: dict[str, str] = field(default_factory=dict)
    #: The version id this came from, when resolved via ``as_of_version``.
    as_of_version_id: str | None = None

    def for_dc(self, dc_id: str) -> int | None:
        """The Delta commit to read for this collection, or None for current."""
        return self.pins.get(str(dc_id))

    @property
    def active(self) -> bool:
        return bool(self.pins) or bool(self.unresolved)

    def warning(self) -> str | None:
        """One sentence naming what could not be pinned, or None."""
        if not self.unresolved:
            return None
        parts = [f"{dc_id} ({reason})" for dc_id, reason in sorted(self.unresolved.items())]
        return (
            "Showing current data for "
            f"{len(parts)} collection{'' if len(parts) == 1 else 's'} with no recorded "
            f"version: {', '.join(parts)}."
        )

    def as_response_meta(self) -> dict[str, Any]:
        """Shape the viewer renders in the preview banner."""
        return {
            "as_of_version_id": self.as_of_version_id,
            "pinned": dict(self.pins),
            "unresolved": dict(self.unresolved),
            "warning": self.warning(),
        }


def pins_from_stamps(stamps: list[dict[str, Any]]) -> DataVersionPins:
    """Turn a stored version's data-collection stamps into read pins.

    A stamp only yields a pin when it recorded a Delta commit. Anything else —
    a manifest collection, an asset, a pre-provenance aggregation — is reported
    as unresolved with the stamp's own reason, which is already written for a
    human to read.
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

    return resolved


def resolve_data_versions(request: dict[str, Any] | None) -> DataVersionPins:
    """Read the time-travel intent out of a render request body.

    Accepts both grains at once: ``as_of_version`` sets the baseline for the
    whole dashboard and ``data_versions`` overrides individual collections on
    top of it, which is what "pin this one component to older data" needs.
    """
    if not isinstance(request, dict):
        return DataVersionPins()

    resolved = DataVersionPins()

    as_of = request.get("as_of_version")
    if as_of:
        record = version_store.get_version(str(as_of))
        if record is None:
            # A deleted version is a caller error, not a reason to serve
            # current data as though it were historical.
            raise ValueError(f"Version {as_of} no longer exists.")
        resolved = pins_from_stamps(record.get("data_collections") or [])
        resolved.as_of_version_id = str(as_of)

    overrides = request.get("data_versions")
    if isinstance(overrides, dict):
        for dc_id, version in overrides.items():
            key = str(dc_id)
            if version is None:
                # Explicit "this one stays live" — drop any dashboard-level pin.
                resolved.pins.pop(key, None)
                resolved.unresolved.pop(key, None)
                continue
            try:
                resolved.pins[key] = int(version)
                resolved.unresolved.pop(key, None)
            except (TypeError, ValueError):
                logger.warning(
                    f"resolve_data_versions: ignoring non-integer delta version "
                    f"{version!r} for dc {key}"
                )

    return resolved
