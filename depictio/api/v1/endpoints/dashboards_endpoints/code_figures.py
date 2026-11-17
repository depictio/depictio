"""Stop the non-admin users of an instance from writing new figure code.

A code figure runs its Python on a worker of the server. With
``DEPICTIO_VIEWER_CODE_FIGURES_LOCKED`` set, a deployment open to people it does
not know (a workshop, say) keeps the code figures its templates bring and refuses
new code from anyone but an administrator.

The code a request carries is compared to what is already trusted, so everything
that merely round-trips a figure keeps working: saving a dashboard, moving a tile,
duplicating a dashboard, adding a catalogue figure. Only code nobody trusted before
is refused. Templates reach the database through the in-process import, which does
not come through here.
"""

from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import dashboards_collection
from depictio.models.components.advanced_viz.catalog import load_catalog_entries

CODE_FIGURES_LOCKED = (
    "Writing figure code is turned off on this server. Existing code figures keep "
    "working, and UI mode is available for new figures."
)


def _figure_code_in(value: Any) -> Iterator[str]:
    """Every code a document would run, at any depth: a dashboard, a YAML import, a preview."""
    if isinstance(value, dict):
        code = value.get("code_content")
        if value.get("mode") == "code" and isinstance(code, str) and code.strip():
            yield code
        for item in value.values():
            yield from _figure_code_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from _figure_code_in(item)


@lru_cache(maxsize=1)
def _catalog_code() -> frozenset[str]:
    return frozenset(
        render.code
        for entry in load_catalog_entries()
        for output in entry.outputs
        for render in output.renders_as
        if render.code
    )


def _is_trusted(code: str) -> bool:
    """Whether this exact code ships in the catalogue or is already on a dashboard."""
    if code in _catalog_code():
        return True
    stored = {"stored_metadata": {"$elemMatch": {"mode": "code", "code_content": code}}}
    return dashboards_collection.find_one(stored, {"_id": 1}) is not None


def refuse_new_figure_code(document: Any, current_user: Any) -> None:
    """Answer 403 when the lock is on and ``document`` carries code not trusted yet."""
    if not settings.viewer.code_figures_locked or getattr(current_user, "is_admin", False):
        return
    if not all(_is_trusted(code) for code in set(_figure_code_in(document))):
        raise HTTPException(status_code=403, detail=CODE_FIGURES_LOCKED)
