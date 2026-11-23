"""The report host of the static runtime: producer A's manifest, in a Quarto report.

The common trunk of Depictio's two offline outputs (RFC serverless §14, RFC
notebook export §3.9). A serverless bundle and a rendered report embed the same
thing — one ``BundleManifest`` built by producer A, one static runtime — and
differ only in the host page:

* the bundle (``producer_a.export_static``) is a page composed from that same
  runtime and the manifest (``serverless.bundle_html``), which mounts the
  viewer App over the whole page;
* the report (this module, then ``combined.py``) carries the manifest, once,
  beside the static runtime (``dist-static/combined-runtime.{js,css}``,
  ``vite.combined.config.ts``), which mounts each tile into the placeholder the
  notebook generator wrote for it, and the dashboard's controls into the
  report's "Filters" part. The same runtime also holds the whole dashboard,
  shown behind a "Report | Dashboard" switch when the file is the combined
  output.

The manifest is producer A's own (``export_manifest``), so a report is exactly
as live as the bundle of the same dashboard would be and is refused on the same
grounds: building one needs *owner* on the dashboard's project (RFC §8, a
manifest carries the data), and the same size ceilings apply. The one addition
is ``initial_filters``: the exported analysis state's filters, so the runtime
opens on the view the document narrates.

A state the runtime cannot reproduce in the page is not embedded at all
(:func:`ineligibility`): pinned data or definitions (the manifest holds current
data), and selection groups / colour-by / split panels (the report runtime has
no group store). Those reports keep every tile's own output, as before.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from depictio.models.models.analysis_state import AnalysisState
from depictio.models.models.serverless import BundleManifest

logger = logging.getLogger(__name__)

RUNTIME_DIR_ENV = "DEPICTIO_REPORT_RUNTIME_DIR"


class ReportRuntimeRefused(RuntimeError):
    """This state (or this caller) cannot have the runtime embedded."""


def runtime_dir() -> Path:
    """``dist-static/`` of the runtime in use (or the env override)."""
    override = os.environ.get(RUNTIME_DIR_ENV)
    if override:
        return Path(override)
    from depictio.serverless.dist import dist_static_dir

    return dist_static_dir()


def ineligibility(state: AnalysisState) -> str | None:
    """Why the runtime cannot open on ``state``, or ``None`` when it can."""
    if state.pins.active:
        return (
            "the export reads pinned data or definitions; the in-page runtime carries the "
            "current data only"
        )
    if state.color_by.kind != "none" or state.split_panels:
        return "the view is coloured or split by selection groups, which the in-page runtime does not draw"
    if any(g.filter_active for g in state.groups) or any(
        f.source == "group_filter" for f in state.filters
    ):
        return "a selection group filters the view, which the in-page runtime does not apply"
    return None


def initial_filters(state: AnalysisState) -> list[dict[str, Any]]:
    """The state's filters, in the wire shape the viewer's filter store holds."""
    return [f for f in state.filters_as_payload() if f.get("source") != "group_filter"]


def build_report_manifest(
    dashboard_id: str,
    user: Any,
    state: AnalysisState,
    *,
    python_runtime: str = "off",
) -> BundleManifest:
    """Producer A's manifest for ``dashboard_id``'s family, opening on ``state``.

    Raises :class:`ReportRuntimeRefused` for a state the runtime cannot
    reproduce, and lets producer A's own errors through (permission —
    ``ProducerAError`` — and size — ``BundleTooLargeError``).
    """
    reason = ineligibility(state)
    if reason:
        raise ReportRuntimeRefused(reason)
    if user is None:
        # producer A reads ``None`` as "the instance's admin" (operator-run
        # exports); a report is always somebody's, and gets only their rights.
        raise ReportRuntimeRefused("a report's manifest is built with its requester's rights")
    from depictio.serverless import producer_a

    result = producer_a.export_manifest(
        str(dashboard_id), producer_a.resolve_user(user), python_runtime=python_runtime
    )
    assert result.manifest is not None
    return result.manifest.model_copy(update={"initial_filters": initial_filters(state)})


def manifest_json(manifest: BundleManifest) -> str:
    """The manifest as JSON text, serialised once (no intermediate dict).

    Falls back to a dump through ``json`` for a payload pydantic cannot write
    (a numpy scalar in an ``Any`` field), with non-finite floats as ``null``
    either way, as ``JSON.parse`` needs.
    """
    try:
        return manifest.model_dump_json()
    except (ValueError, TypeError) as exc:
        logger.debug("manifest JSON: falling back to json.dumps (%s)", exc)
        from depictio.notebook.report_runtime import _json_safe

        return json.dumps(
            _json_safe(manifest.model_dump(mode="json")), default=str, separators=(",", ":")
        )


def user_payload(user: Any) -> dict[str, Any]:
    """The requester, as a worker task's JSON argument (``ExportUser`` fields)."""
    from depictio.serverless.producer_a import resolve_user

    export_user = resolve_user(user)
    return {
        "id": str(export_user.id),
        "email": export_user.email,
        "is_admin": export_user.is_admin,
        "is_anonymous": export_user.is_anonymous,
    }
