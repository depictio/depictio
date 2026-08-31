"""Bind externally-supplied filters to the dashboard controls they mean.

An external host builds ``?filters=`` from the manifest, which publishes each
interactive component as ``{component_id, filter: {column_name, ...}}``. Inside
Depictio, though, a filter is matched to its control by ``index`` — the
dashboard-internal component id — and only some render paths care:

* ``figure`` and ``advanced_viz`` go through ``_build_filter_metadata``, which
  keys purely on ``column_name``, so they honour a filter with no ``index``.
* ``multiqc`` goes through ``_resolve_multiqc_sample_filter``, which looks the
  filter up in ``stored_metadata`` by ``index`` to decide whether the column
  belongs to the MultiQC data collection or to a metadata DC that has to be
  loaded and joined. With no ``index`` it finds nothing and silently returns
  the unfiltered figure.

So the same filter payload filtered some components and not others, and the
response still said ``filter_applied: true`` because that flag was computed from
the request rather than from what happened. That is the worst version of this
bug: a host page sees a 200, a truthful-looking flag, and an unchanged figure.

Binding here — once, at the export boundary — makes the published contract the
real one. A filter that names a column some control on this dashboard drives is
given that control's ``index`` and ``dc_id``, and every render path then agrees
about what it means.
"""

from __future__ import annotations

from depictio.api.v1.configs.logging_init import logger

__all__ = ["bind_filters"]


def _controls(dashboard_doc: dict) -> list[dict]:
    """Interactive components of a dashboard, in stored order."""
    return [
        component
        for component in (dashboard_doc.get("stored_metadata") or [])
        if component.get("component_type") == "interactive" and component.get("index")
    ]


def _match(control: dict, column_name: str, dc_id: str | None) -> bool:
    """Does this control drive ``column_name`` (on ``dc_id`` if one was given)?

    ``dc_id`` is only used to disambiguate. Two data collections can both have a
    ``sample`` column, and a host that knows which one it means should be able to
    say so; a host that does not care gets the first control on that column.
    """
    if str(control.get("column_name") or "") != column_name:
        return False
    if dc_id and str(control.get("dc_id") or "") != dc_id:
        return False
    return True


def bind_filters(dashboard_doc: dict, filters: list[dict]) -> tuple[list[dict], list[str]]:
    """Attach ``index``/``dc_id`` to each filter from the dashboard's own controls.

    Args:
        dashboard_doc: the dashboard, for its ``stored_metadata``.
        filters: filters as the caller sent them.

    Returns:
        ``(bound, unbound_columns)``. ``bound`` is a new list, same order, with
        ``index`` and ``dc_id`` filled in wherever a control was found.
        ``unbound_columns`` names the columns no control on this dashboard
        drives, so the response can say so instead of quietly ignoring them.

    A filter that already carries an ``index`` is passed through untouched: an
    explicit id is a stronger statement of intent than a column name, and a
    caller replaying a payload captured from the dashboard should get exactly
    what the dashboard would.
    """
    if not filters:
        return [], []

    controls = _controls(dashboard_doc)
    bound: list[dict] = []
    unbound: list[str] = []

    for entry in filters:
        if not isinstance(entry, dict):
            continue
        if entry.get("index"):
            bound.append(entry)
            continue

        column_name = str(entry.get("column_name") or "")
        # `component_id` is what the manifest calls the index, so accept it as a
        # direct alias — a host copying the field name it was given is right.
        component_id = entry.get("component_id")
        if component_id:
            bound.append({**entry, "index": str(component_id)})
            continue

        if not column_name:
            bound.append(entry)
            continue

        dc_id = str(entry.get("dc_id") or "") or None
        control = next(
            (candidate for candidate in controls if _match(candidate, column_name, dc_id)),
            None,
        )
        if control is None:
            # Not an error: a host may legitimately filter a column that has no
            # control on this dashboard, and the column-keyed render paths will
            # still apply it. It is reported so a host can tell the difference
            # between "filtered to nothing" and "filter never reached anything".
            unbound.append(column_name)
            bound.append(entry)
            continue

        bound.append(
            {
                **entry,
                "index": str(control.get("index")),
                "dc_id": str(control.get("dc_id") or "") or entry.get("dc_id"),
            }
        )

    if unbound:
        logger.debug("export: filters with no matching control: %s", unbound)
    return bound, unbound
