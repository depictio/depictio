"""The colour of a run, when its samples already have one (epic #1399).

A dashboard pins colours to the values of its group columns (``locality``:
Athens blue, Barcelona orange). When the runs of a project follow such a
column, one value per run and one run per value (run_barcelona holds only
Barcelona samples, and no other run holds any), the run is that group: it
takes the group's colour, so "What's new", its toast and the Overlay speak the
dashboard's colours. Runs that follow no such column get none here; the viewer
hands them a colour of its own palette.

Only the columns stored with each Delta commit are read to choose the tables
(``aggregation_columns_specs``), and only two columns of the smallest one are
loaded, once per table version.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from bson import ObjectId

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import deltatables_collection

RUN_COLUMN = "depictio_run_id"


def _latest_columns(dc_ids: list[str]) -> list[tuple[str, int, int, set[str]]]:
    """``(dc_id, delta_version, rows, columns)`` of each table carrying runs."""
    oids = [ObjectId(d) for d in dc_ids if ObjectId.is_valid(d)]
    out = []
    for doc in deltatables_collection.find(
        {"data_collection_id": {"$in": oids}},
        {"data_collection_id": 1, "aggregation": {"$slice": -1}},
    ):
        last = (doc.get("aggregation") or [{}])[-1]
        columns = {s.get("name") for s in last.get("aggregation_columns_specs") or []}
        if RUN_COLUMN not in columns:
            continue
        out.append(
            (
                str(doc["data_collection_id"]),
                int(last.get("delta_version") or 0),
                int(last.get("rows_total") or 0),
                columns,
            )
        )
    return out


@lru_cache(maxsize=256)
def _values_by_run(
    wf_id: str, dc_id: str, delta_version: int, column: str
) -> tuple[tuple[str, frozenset[str]], ...]:
    """Each run of the table with the values of ``column`` its rows hold, read
    at ``delta_version`` (which also keys the cache: a new commit, a new entry)."""
    import polars as pl

    from depictio.api.v1.deltatables_utils import load_deltatable_lite

    frame = load_deltatable_lite(
        ObjectId(wf_id),
        ObjectId(dc_id),
        select_columns=[column, RUN_COLUMN],
        delta_version=delta_version,
    )
    pairs = (
        frame.select(pl.col(RUN_COLUMN).cast(pl.String), pl.col(column).cast(pl.String))
        .drop_nulls()
        .unique()
    )
    grouped: dict[str, set[str]] = {}
    for run, value in pairs.iter_rows():
        grouped.setdefault(run, set()).add(value)
    return tuple((run, frozenset(values)) for run, values in sorted(grouped.items()))


def group_run_colors(
    run_tags: list[str],
    category_colors: dict[str, dict[str, str]] | None,
    collections: dict[str, dict[str, Any]],
) -> dict[str, str]:
    """``{run_tag: colour}`` for the runs that are one group of a pinned column.

    The columns are tried in the order the dashboard pins them; the first one
    that is a group for a run gives its colour. A column fails for a run when
    the run's rows hold several of its values, or when its value is held by
    another run too: two runs in one colour would read as one.
    """
    wanted = [t for t in run_tags if t]
    pinned = {c: m for c, m in (category_colors or {}).items() if c != RUN_COLUMN and m}
    if not wanted or not pinned:
        return {}
    tables = _latest_columns(list(collections))
    colors: dict[str, str] = {}
    for column, mapping in pinned.items():
        holding = [t for t in tables if column in t[3]]
        if not holding:
            continue
        dc_id, version, _rows, _cols = min(holding, key=lambda t: t[2])
        wf_id = (collections.get(dc_id) or {}).get("workflow_id")
        if not wf_id:
            continue
        try:
            by_run = dict(_values_by_run(wf_id, dc_id, version, column))
        except Exception as exc:  # a table that cannot be read colours nothing
            logger.warning(f"run colours: cannot read {column} of {dc_id}: {exc}")
            continue
        holders: dict[str, set[str]] = {}
        for run, values in by_run.items():
            for value in values:
                holders.setdefault(value, set()).add(run)
        for run in wanted:
            if run in colors:
                continue
            values = by_run.get(run) or frozenset()
            if len(values) != 1:
                continue
            (value,) = values
            if holders.get(value) == {run} and mapping.get(value):
                colors[run] = mapping[value]
        if all(t in colors for t in wanted):
            break
    return colors
