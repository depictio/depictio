"""The report layer of a dashboard: one document's export notes (#1457).

Notebook export renders a dashboard as a report. The report layer is what
makes that report *written*: an introduction and a conclusion, a cover, which
tiles belong in the report and in which order. It lives on the dashboard
family's main tab (``report_layer``, like ``shared_labels``), so a version
covers the whole family — text and tiles together — and a restore brings back
a past layer.

Who may read or write it: whoever may change the dashboard, i.e. an editor of
the project or the owner of the dashboard document (a reader who duplicated a
public dashboard owns the copy). Everyone else — a viewer, an anonymous
visitor — is answered 404, the same as a dashboard they cannot see: the layer
is the authoring side, and its existence leaks nothing to them.

A published (locked) dashboard is refused with 409, like every content
change. The write is an autosave that coalesces: the text is part of the
dashboard's content, seeded into a baseline and captured as a version, but an
editor's typing is not one timeline step per keystroke.
"""

from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
    _capture_version_quietly,
    _ensure_baseline_quietly,
    check_dashboard_mutation_permission,
)
from depictio.api.v1.endpoints.projects_endpoints.publish_lock import assert_dashboard_unlocked
from depictio.api.v1.endpoints.user_endpoints.routes import get_user_or_anonymous
from depictio.models.models.base import PyObjectId
from depictio.models.models.report_layer import ReportLayer, ReportLayerPut, seed_intro_from_notes
from depictio.models.models.users import User
from depictio.models.timestamps import utc_now_naive

report_layer_router = APIRouter()

#: The layer's revision when a dashboard stores none.
_EMPTY_REVISION = 0


def _require_report_editor() -> None:
    """The report layer only exists on a deployment that turned the editor on.

    Off (the default) the routes answer 404, like the rest of the
    notebook-export endpoints when their feature flag is off: not an error the
    caller can act on, and not an answer that reveals the feature exists.
    """
    if not (settings.notebook_export.enabled and settings.notebook_export.report_editor):
        raise HTTPException(status_code=404, detail="The report layer editor is disabled.")


def stored_layer(main_tab: dict[str, Any]) -> dict[str, Any] | None:
    """The layer as the main tab holds it, or ``None``."""
    layer = main_tab.get("report_layer")
    return layer if isinstance(layer, dict) else None


def _plain(value: Any) -> Any:
    """ObjectIds back to strings, so the response is plain JSON."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _editable_family(dashboard_id: PyObjectId, current_user: User) -> tuple[ObjectId, dict]:
    """The family's main tab, when ``current_user`` may write its report layer.

    Every refusal is a 404: a layer (or a dashboard) the caller may not touch
    is one they are not meant to know exists.
    """
    doc = dashboards_collection.find_one(
        {"dashboard_id": ObjectId(str(dashboard_id))},
        {"project_id": 1, "parent_dashboard_id": 1},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    parent = doc.get("parent_dashboard_id")
    family_id = ObjectId(str(parent)) if parent else ObjectId(str(dashboard_id))
    main_tab = dashboards_collection.find_one({"dashboard_id": family_id})
    if not main_tab:
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    if getattr(current_user, "is_anonymous", False) and not settings.auth.is_single_user_mode:
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    if not check_dashboard_mutation_permission(main_tab, current_user, "editor"):
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    return family_id, main_tab


@report_layer_router.get("/{dashboard_id}")
async def get_report_layer(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict:
    """The layer as it is stored, or the intro the dashboard's notes suggest.

    A dashboard with nothing stored shows its author a draft: its Guide notes
    as the intro, marked ``seeded_from_notes`` and not written anywhere. The
    editor saves it (as any other layer write) or clears it; a reader who
    exports without ever opening the editor is not affected.
    """
    _require_report_editor()
    _family_id, main_tab = _editable_family(dashboard_id, current_user)
    layer = stored_layer(main_tab)
    if layer is None:
        seeded = seed_intro_from_notes(str(main_tab.get("notes_content") or ""))
        if seeded is None:
            return ReportLayer().model_dump(mode="json")
        return ReportLayer(intro=seeded, seeded_from_notes=True).model_dump(mode="json")
    return ReportLayer.model_validate(_plain(layer)).model_dump(mode="json")


@report_layer_router.put("/{dashboard_id}")
async def put_report_layer(
    dashboard_id: PyObjectId,
    payload: ReportLayerPut,
    current_user: User = Depends(get_user_or_anonymous),
) -> dict:
    """Replace the report layer (last write wins, against the revision read).

    A write against a stale revision is refused with 409 and the stored layer
    with its author and time, so two editors cannot overwrite each other's
    prose. The first write takes no revision: a dashboard with nothing stored
    is at revision 0.

    Content change, so it seeds a baseline and captures a version before and
    after — as an autosave: the layer is part of the dashboard, but an
    editor's typing is not one timeline step per keystroke.
    """
    _require_report_editor()
    family_id, main_tab = _editable_family(dashboard_id, current_user)
    assert_dashboard_unlocked(main_tab)

    before = stored_layer(main_tab)
    stored_revision = int(before.get("revision") or 0) if before else _EMPTY_REVISION
    if payload.base_revision != stored_revision:
        last = before or {}
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "The report layer changed since you opened it. "
                    f"It is now at revision {stored_revision}."
                ),
                "layer": _plain(last) if before else None,
                "revision": stored_revision,
                "updated_by": last.get("updated_by"),
                "updated_at": last.get("updated_at"),
            },
        )

    layer = payload.layer.model_copy(
        update={
            "revision": stored_revision + 1,
            "updated_by": str(current_user.id) if current_user else None,
            "updated_at": utc_now_naive(),
            # Only a GET seed says so; a write is the editor's own text.
            "seeded_from_notes": False,
        }
    )
    # Before the write, as for every route that bypasses `/save`.
    _ensure_baseline_quietly(family_id, current_user)
    dashboards_collection.update_one(
        {"dashboard_id": family_id}, {"$set": {"report_layer": layer.model_dump(mode="json")}}
    )
    _capture_version_quietly(family_id, current_user, kind="auto")
    logger.info(f"Dashboard {family_id}: report layer written at revision {layer.revision}")
    return layer.model_dump(mode="json")
