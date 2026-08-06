"""Bind-and-refill BUILD side (RFC §4, phase 5a).

Turns a figure component into a :class:`BindingTable` — the thing the runtime
(``packages/depictio-static-core/src/refill.ts``) needs to re-render the *same*
figure under any filter mask, without porting one line of plotly-express to
TypeScript. ui-mode figures are built here from their kwargs; code-mode figures
(RFC §7, phase 6) hand in the figure their own Python produced plus the frame
its transpiled prologue derived (``fig=`` / ``df``), and bind the same way.

The invariant this exploits: **filtering only removes rows**, so the trace set
built on unfiltered data is a superset of any filtered view. We therefore build
the figure once, here, with the *real* ``create_figure_from_data`` — authentic
layout, colorway, faceting, hovertemplates, coloraxis, mantine template — and
emit, per trace, (a) the group-equality predicates selecting its rows and (b)
which source column feeds which trace field.

Matching is *verified against the data*, not guessed
------------------------------------------------------
The RFC sketches matching a trace to its group tuple via ``legendgroup``/
``name``. That is not decidable in general: with ``facet_row``/``line_group``
(and no colour) px emits ``name=''``/``legendgroup=''`` for **every** trace, and
group values are only recoverable from the hovertemplate prefix, which the
``labels`` kwarg can rewrite. So this module uses the sound version of the same
idea: for every group combination present in the frame we project the anchor
columns (x/y/…) and compare them **element-wise** against the produced trace's
arrays. A trace binds only if exactly one combination reproduces its data
exactly. ``legendgroup``/``name``/``xaxis``/``yaxis`` are still recorded (axes
in ``TraceBinding.axes``) but are not load-bearing.

That makes the matcher self-checking: every px behaviour we did *not* model —
NaN-size row dropping, category ordering, an aggregating trace, a group px did
not emit — shows up as "no combination reproduces this array" and returns
``None``. A frozen figure is correct; a mis-bound one is wrong, so **every
ambiguity returns ``None``** (with a :class:`BindingMiss` naming which one) and
the caller freezes with ``binding_miss``:

* no anchor field (nothing in the trace we can tie back to a kwarg column);
* a trace matching zero or 2+ group combinations;
* a group combination px emitted no trace for (rows would silently vanish);
* a row-length array in a trace whose source column is undeterminable, or
  determinable in more than one way;
* a whole-frame visualisation (heatmap, scatter_matrix, parallel_*, imshow,
  scatter_geo, choropleth — ``_WHOLE_FRAME_VISU``);
* every grouping value null, so px would plot nothing at all;
* a non-OLS ``trendline`` (the runtime only refits closed-form 1-predictor OLS).

A *single* null grouping value is not one of them — see :func:`_combinations`.

Row ORDER is not one of them either, for the visualisations where it draws
nothing — see :func:`_order_free_trace` and :func:`_permutation`.

Stripping convention (what ``refill.ts`` expects)
-------------------------------------------------
``refill.ts`` deep-clones ``scaffold`` and **writes** every bound field with
``setPath`` (creating intermediates as needed) and rebuilds ``customdata`` by
zipping its bound columns, so bound arrays must simply be **absent** from the
scaffold — we ``del`` them rather than emptying them. An
empty-list placeholder would work too but costs bytes; a *left-in* array would
be a full-length stale array whenever the runtime failed to overwrite it, so
absence is also the safer failure mode. Every array in a bound trace whose
length equals that trace's row count is bound (that is enforced above), so no
row-length array survives in the scaffold. Layout is copied through 100%
untouched — the runtime never re-derives structure.

Sampling
--------
``create_figure_from_data`` downsamples point plots above ``FIGURE_MAX_POINTS``.
A scaffold built from a *sample* could be missing a whole group (its rows might
not have been sampled), and the runtime refills from the **full** bundled
column, so it would silently drop those rows. When sampling fires we therefore
rebuild the scaffold with sampling disabled (``max_points=-1``) — the trace set
is then a true superset of every filtered view — and flag ``sampled=True`` so
the caller downgrades the component to ``partial``/``max_points``: the live
figure legitimately plots more points than the server would have.

Known accepted deviations (RFC §4 table, plus one)
--------------------------------------------------
``marker.sizeref``/``coloraxis.cmin|cmax`` stay at their unfiltered values, and
categorical axis ticks keep vanished categories. Additionally an OLS
trendline's *hovertemplate* keeps the unfiltered fit's equation and R² (it is
baked into the layout-side string by px); the drawn line itself is refit by the
runtime.
"""

from __future__ import annotations

import base64
import binascii
import math
from datetime import date, datetime, time
from enum import Enum
from typing import Any

import polars as pl

from depictio.models.models.serverless import (
    BindingTable,
    TierReason,
    TraceBinding,
    TrendlineBinding,
)


class BindingMiss(str, Enum):
    """Which bail-out refused a figure.

    The caller turns this into the sentence a user reads in the frozen-badge
    tooltip, so the members name the *actual* obstacle: "computed over the whole
    table" and "a trace array the runtime cannot refill" are different facts
    about a figure, and collapsing both into "no unambiguous trace↔group
    binding" tells the user something false about one of them.
    """

    NO_DATA = "no_data"
    WHOLE_FRAME_VISU = "whole_frame_visu"
    TRENDLINE_UNSUPPORTED = "trendline_unsupported"
    NO_SOURCE_COLUMNS = "no_source_columns"
    ALL_NULL_GROUPING = "all_null_grouping"
    NO_TRACES = "no_traces"
    TRENDLINE_UNEXPECTED = "trendline_unexpected"
    NO_ANCHOR = "no_anchor"
    TRACE_AMBIGUOUS = "trace_ambiguous"
    TRACE_COLLISION = "trace_collision"
    ARRAY_2D = "array_2d"
    COLUMN_AMBIGUOUS = "column_ambiguous"
    NO_BOUND_FIELD = "no_bound_field"
    GROUP_UNPLOTTED = "group_unplotted"
    TRENDLINE_UNPAIRABLE = "trendline_unpairable"
    TRACE_UNEXPLAINED = "trace_unexplained"


#: One user-facing clause per bail-out, written to read after "this figure is
#: frozen because …". Kept next to the code that raises them so a new bail-out
#: cannot ship without its sentence.
BINDING_MISS_DETAIL: dict[BindingMiss, str] = {
    BindingMiss.NO_DATA: "no data to bind against (empty table, or unreadable figure params)",
    BindingMiss.WHOLE_FRAME_VISU: (
        "this visualisation is computed over the whole table at once, so it has no "
        "per-row binding to refill"
    ),
    BindingMiss.TRENDLINE_UNSUPPORTED: "only an OLS trendline can be refit in the browser",
    BindingMiss.NO_SOURCE_COLUMNS: "the figure names no column of the bundled table",
    BindingMiss.ALL_NULL_GROUPING: "every grouping value is null, so the figure plots nothing",
    BindingMiss.NO_TRACES: "the server produced a figure with no traces",
    BindingMiss.TRENDLINE_UNEXPECTED: "the figure carries a fitted trace the params did not ask for",
    BindingMiss.NO_ANCHOR: "no trace field ties back to a source column",
    BindingMiss.TRACE_AMBIGUOUS: "a trace reproduces no group of the data, or more than one",
    BindingMiss.TRACE_COLLISION: "two traces claim the same group in the same subplot",
    BindingMiss.ARRAY_2D: "a trace array has a shape the runtime cannot refill",
    BindingMiss.COLUMN_AMBIGUOUS: "a trace array does not resolve to exactly one source column",
    BindingMiss.NO_BOUND_FIELD: "nothing in the trace could be bound to a column",
    BindingMiss.GROUP_UNPLOTTED: "a group of the data has no trace, so filtering would drop rows",
    BindingMiss.TRENDLINE_UNPAIRABLE: (
        "a trendline could not be paired with the trace it was fit against"
    ),
    BindingMiss.TRACE_UNEXPLAINED: "the figure holds a trace the binder cannot account for",
}


def miss_detail(miss: BindingMiss | None) -> str:
    """The user-facing clause for a refusal (a safe fallback for ``None``)."""
    if miss is None:
        return "no unambiguous trace↔group binding (RFC §4)"
    return BINDING_MISS_DETAIL[miss]


def miss_tier_reason(miss: BindingMiss | None) -> TierReason:
    """The manifest tier reason a refusal maps to.

    Only the whole-frame case has its own ``TierReason`` — the runtime badge
    already has copy for it ("computed over the whole table at once"), and it is
    not a *matching* failure at all. Everything else is a binding miss.
    """
    if miss is BindingMiss.WHOLE_FRAME_VISU:
        return TierReason.WHOLE_FRAME_VIZ
    return TierReason.BINDING_MISS


def frozen_miss_detail(miss: BindingMiss | None, prefix: str = "") -> str:
    """The detail line a refused figure carries — one sentence, one place.

    Every producer and every data-free classifier reports a refusal with this
    wording, so the tier table a preflight prints and the manifest a build emits
    cannot word the same verdict differently. ``prefix`` is the only part that
    varies: a code-mode figure says how far it got before the binder refused it.
    """
    return f"{prefix}{miss_detail(miss)}; frozen at the default filter state"


def planned_figure_miss(component_meta: dict[str, Any]) -> BindingMiss | None:
    """The refusals :func:`build_binding_with_reason` reaches *without* data.

    Two of its bail-outs are decided from the component's own metadata alone —
    a whole-frame visualisation and a non-OLS trendline — so the data-free tier
    classifiers can reach the same verdict, in the same words, instead of
    reporting the figure as undecided until the build has tried it. The builder
    itself calls this, which is what keeps plan and build from drifting apart.

    ``None`` means "nothing decidable here": every other bail-out needs the
    frame, or the figure the server pipeline produces from it.
    """
    from depictio.api.v1.services.figure.figure_builder import _WHOLE_FRAME_VISU

    visu_type = component_meta.get("visu_type") or "scatter"
    if str(visu_type).lower() in _WHOLE_FRAME_VISU:
        return BindingMiss.WHOLE_FRAME_VISU

    # ``figure_params`` is the lite spec's key for the px kwargs, ``dict_kwargs``
    # the stored_metadata one — the same two the builder reads.
    dict_kwargs = component_meta.get("figure_params") or component_meta.get("dict_kwargs") or {}
    if not isinstance(dict_kwargs, dict):
        return None
    trendline_kind = dict_kwargs.get("trendline") or ""
    if trendline_kind and str(trendline_kind).lower() != "ols":
        # the runtime only refits closed-form 1-predictor OLS
        return BindingMiss.TRENDLINE_UNSUPPORTED
    return None


# px grouping kwargs, in the order the manifest contract pins for
# ``BindingTable.group_cols``.
PX_GROUP_KWARGS: tuple[str, ...] = (
    "color",
    "symbol",
    "line_dash",
    "line_group",
    "pattern_shape",
    "facet_row",
    "facet_col",
)

# px kwarg -> the trace field path it populates. Used as the *hypothesis* for
# each row-length array found in a trace; a hypothesis that does not reproduce
# the data falls through to a uniqueness search over the referenced columns.
_FIELD_PATH_BY_KWARG: dict[str, str] = {
    "x": "x",
    "y": "y",
    "z": "z",
    "base": "base",
    "r": "r",
    "theta": "theta",
    "a": "a",
    "b": "b",
    "c": "c",
    "names": "labels",
    "values": "values",
    "size": "marker.size",
    "color": "marker.color",  # only when px treats colour as continuous
    "hover_name": "hovertext",
    "text": "text",
    "error_x": "error_x.array",
    "error_y": "error_y.array",
    "error_z": "error_z.array",
}

# px bakes this into every trendline trace's hovertemplate ("<b>OLS trendline</b>",
# "<b>LOWESS trendline</b>", …) — the only structural marker distinguishing a
# fitted trace from a raw one.
_TRENDLINE_MARK = "trendline</b>"

_ROW_INDEX = "__binding_row__"


# ---------------------------------------------------------------------------
# value normalisation (Plotly numpy/typed arrays vs Polars python values)
# ---------------------------------------------------------------------------


def _norm(value: Any) -> Any:
    """One comparable python scalar. NaN and null collapse to ``None`` (Polars
    yields ``None`` where numpy hands Plotly a ``nan``), numpy scalars unwrap,
    temporals become ISO strings."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, (str, int)):
        return value
    if hasattr(value, "item") and not isinstance(value, (list, tuple, dict)):
        try:
            return _norm(value.item())
        except (ValueError, AttributeError):
            return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def _typed_array(value: Any) -> list[Any] | None:
    """Decode Plotly's base64 typed-array wire form, ``{'dtype', 'bdata'}``.

    Plotly ≥6 serialises numeric arrays that way and does **not** decode them on
    the way back in (``go.Figure(fig_json)`` / ``plotly.io.from_json`` leave the
    dict in place — plotly.js decodes it in the browser). A figure the producer
    rebuilt from JSON — every code-mode figure, which comes back from the server
    pipeline as JSON — therefore holds these dicts where a live figure holds
    numpy arrays, and without this the binder would see "an array-ish attribute
    it cannot flatten" and refuse every one of them.

    ``None`` for anything that is not a plain 1-D buffer (an ``nd`` ``shape``
    included: a 2-D array is not column-bound).
    """
    if not isinstance(value, dict) or "bdata" not in value or "dtype" not in value:
        return None
    shape = value.get("shape")
    if shape not in (None, "") and len(str(shape).split(",")) > 1:
        return None
    import numpy as np

    try:
        # Plotly writes little-endian buffers regardless of host order.
        dtype = np.dtype(str(value["dtype"])).newbyteorder("<")
        buffer = base64.b64decode(value["bdata"])
        decoded = np.frombuffer(buffer, dtype=dtype)
    except (TypeError, ValueError, binascii.Error):
        return None
    return [_norm(item) for item in decoded.tolist()]


def _as_list(value: Any) -> list[Any] | None:
    """A Plotly trace attribute as a flat list of normalised scalars, or
    ``None`` when it is not a 1-D array (scalars, 2-D customdata, lists of
    sub-objects such as ``dimensions``)."""
    if isinstance(value, dict):
        return _typed_array(value)
    if value is None or isinstance(value, (str, bytes)):
        return None
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        return None
    out: list[Any] = []
    for item in value:
        if isinstance(item, (list, tuple, dict)) or hasattr(item, "to_plotly_json"):
            return None  # nested structure — not a column-bound array
        out.append(_norm(item))
    return out


def _as_matrix(value: Any) -> list[list[Any]] | None:
    """A 2-D trace attribute as rows of normalised scalars, or ``None``.

    The one that occurs is ``customdata``: px stacks ``hover_data``/
    ``custom_data`` into an (n, k) array, which reaches us either as a numpy
    object array (live figure) or as a tuple/list of row lists (a figure rebuilt
    from JSON, i.e. every producer-A code-mode figure). A ragged shape, a
    non-scalar cell or an empty matrix is ``None`` — not column-bound.
    """
    if isinstance(value, dict):
        return None  # a base64 typed array is 1-D by construction (see _typed_array)
    if value is None or isinstance(value, (str, bytes)):
        return None
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)) or not value:
        return None
    rows: list[list[Any]] = []
    width: int | None = None
    for row in value:
        if hasattr(row, "tolist"):
            row = row.tolist()
        if not isinstance(row, (list, tuple)) or not row:
            return None
        if width is None:
            width = len(row)
        elif len(row) != width:
            return None
        cells: list[Any] = []
        for cell in row:
            if isinstance(cell, (list, tuple, dict)) or hasattr(cell, "to_plotly_json"):
                return None
            cells.append(_norm(cell))
        rows.append(cells)
    return rows


def _equal(left: list[Any], right: list[Any]) -> bool:
    return len(left) == len(right) and all(a == b for a, b in zip(left, right))


# Visualisations whose traces are an unordered *collection* of marks: permuting
# a trace's rows moves nothing on screen (a bar segment sits at its x category,
# a box/violin/histogram aggregates, a marker sits at its coordinates). Anything
# that draws a path through its vertices in array order — line, area, ecdf,
# funnel — is deliberately absent: there, a reordering is a different picture.
_ORDER_FREE_VISU: frozenset[str] = frozenset({"bar", "box", "violin", "histogram", "strip"})


def _order_free_trace(visu_type: str, trace_json: dict[str, Any]) -> bool:
    """Whether this trace's row order is free to differ from the frame's.

    A scatter qualifies only when its ``mode`` says markers and nothing else:
    px writes the mode explicitly, and an *absent* mode is not "markers" —
    plotly.js infers ``lines+markers`` below 20 points, which would draw a path.
    """
    kind = str(visu_type).lower()
    if kind in _ORDER_FREE_VISU:
        return True
    if kind != "scatter":
        return False
    mode = trace_json.get("mode")
    return isinstance(mode, str) and "lines" not in mode


def _permutation(
    anchors: list[tuple[str, list[Any]]],
    hypothesis: dict[str, str],
    columns: _Columns,
    rows: list[int],
) -> list[int] | None:
    """Positions in ``rows`` the trace's anchor arrays are in, or ``None``.

    Element-wise matching answers "is this trace this group, in this order?".
    That extra clause is a real false negative: the user's own Polars decides
    the frame's row order, and ``group_by`` defaults to ``maintain_order=False``
    while ``sort`` breaks ties arbitrarily, so a figure built on the server's
    frame and the same figure built on the replayed frame (``prologue_exec``
    pins both to be deterministic) can hold the same rows in different orders.
    Nothing downstream depends on that order — ``refill.ts`` overwrites every
    bound array with its own replay's row order at first paint, the default
    filter state included — so for the order-free visualisations we match on the
    joint anchor MULTISET instead, and hand back the permutation that proves it.

    Returning the permutation (rather than a bool) keeps step 2 exactly as
    strict as before: every other array is still verified element-wise, just
    against the rows in the trace's order. Duplicate anchor tuples are consumed
    first-come-first-served; if that assignment makes another field disagree the
    figure freezes, which is the safe direction.
    """
    length = len(anchors[0][1])
    if any(len(values) != length for _, values in anchors) or length != len(rows):
        return None
    projected = [columns.project(hypothesis[path], rows) for path, _ in anchors]
    buckets: dict[tuple[Any, ...], list[int]] = {}
    try:
        for position in range(len(rows)):
            buckets.setdefault(tuple(values[position] for values in projected), []).append(position)
        out: list[int] = []
        for index in range(length):
            queue = buckets.get(tuple(values[index] for _, values in anchors))
            if not queue:
                return None  # a row of the trace this group does not have
            out.append(queue.pop())
    except TypeError:
        return None  # an unhashable cell — fall back to "does not match"
    return out


class _Columns:
    """Normalised full-column values, materialised once per column."""

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df
        self._cache: dict[str, list[Any]] = {}

    def full(self, name: str) -> list[Any]:
        cached = self._cache.get(name)
        if cached is None:
            cached = [_norm(v) for v in self._df[name].to_list()]
            self._cache[name] = cached
        return cached

    def project(self, name: str, rows: list[int]) -> list[Any]:
        values = self.full(name)
        return [values[i] for i in rows]


# ---------------------------------------------------------------------------
# trace introspection
# ---------------------------------------------------------------------------


def _trace_attr(trace_obj: Any, key: str) -> Any:
    """One attribute off a graph-objects trace, or ``None`` if it has no such
    property (the JSON and the object can disagree on exotic keys)."""
    try:
        return trace_obj[key]
    except (KeyError, ValueError, TypeError):
        return None


def _collect_arrays(
    trace_json: dict[str, Any], trace_obj: Any, prefix: str = ""
) -> list[tuple[str, list[Any] | None]]:
    """Every array-ish attribute of a trace as ``(dotted path, values)``.

    Structure comes from ``to_plotly_json()``, which encodes *numeric* arrays as
    ``{'dtype', 'bdata'}`` base64 blobs (Plotly ≥6) but leaves object arrays —
    string categories, ``customdata`` — as bare ndarrays; both shapes count.
    Values are read back off the graph-objects object, which still holds the
    plain numpy/tuple data. A ``None`` value marks an attribute that *looks*
    like an array but cannot be flattened — the caller treats it as unbindable.
    """
    out: list[tuple[str, list[Any] | None]] = []
    for key, json_value in trace_json.items():
        path = f"{prefix}{key}"
        raw = _trace_attr(trace_obj, key)
        is_typed_array = isinstance(json_value, dict) and "bdata" in json_value
        is_ndarray = not isinstance(json_value, (dict, str, bytes)) and hasattr(
            json_value, "tolist"
        )
        if is_typed_array or is_ndarray or isinstance(json_value, (list, tuple)):
            out.append((path, _as_list(raw if raw is not None else json_value)))
        elif isinstance(json_value, dict) and raw is not None:
            out.extend(_collect_arrays(json_value, raw, prefix=f"{path}."))
    return out


def _strip_path(trace_json: dict[str, Any], path: str) -> None:
    """Delete a bound field from the scaffold (see the stripping convention)."""
    parts = path.split(".")
    cursor: Any = trace_json
    for part in parts[:-1]:
        cursor = cursor.get(part) if isinstance(cursor, dict) else None
        if not isinstance(cursor, dict):
            return
    if isinstance(cursor, dict):
        cursor.pop(parts[-1], None)


def _customdata_columns(
    matrix: list[list[Any]], candidates: list[str], columns: _Columns, rows: list[int]
) -> list[str] | None:
    """The source columns behind a trace's 2-D ``customdata``, in plotly's own
    column order, or ``None`` when any of them is not uniquely determined.

    px stacks ``hover_data``/``custom_data`` into an (n, k) array and the
    hovertemplate addresses it positionally (``%{customdata[2]}``), so the order
    *is* the contract: ``refill.ts`` rebuilds the array by zipping these columns
    back in this order, which keeps every index in the (untouched) hovertemplate
    pointing at the same value it did on the server.

    Which column feeds which slot is resolved the same way every other array is
    — by reproducing the data, not by re-deriving px's kwarg ordering. Two
    candidates with identical values in a slot are ambiguous, and ambiguity
    freezes.
    """
    out: list[str] = []
    for slot in range(len(matrix[0])):
        values = [row[slot] for row in matrix]
        resolved = [c for c in candidates if _equal(values, columns.project(c, rows))]
        if len(resolved) != 1:
            return None
        out.append(resolved[0])
    return out


def _axes_of(trace_json: dict[str, Any]) -> dict[str, str]:
    axes = {}
    for key in ("xaxis", "yaxis"):
        value = trace_json.get(key)
        if isinstance(value, str) and value:
            axes[key] = value
    return axes


# ---------------------------------------------------------------------------
# grouping
# ---------------------------------------------------------------------------


def _group_columns(dict_kwargs: dict[str, Any], df: pl.DataFrame) -> list[str]:
    """px's grouping columns, in contract order.

    ``color`` groups only when px treats it as *discrete*, which it decides with
    ``_is_continuous`` — a numeric-dtype check. A wrong call here is not a
    correctness risk: the trace fingerprints stop matching and the component
    freezes.
    """
    cols: list[str] = []
    for kwarg in PX_GROUP_KWARGS:
        column = dict_kwargs.get(kwarg)
        if not isinstance(column, str) or column not in df.columns:
            continue
        if kwarg == "color" and df.schema[column].is_numeric():
            continue
        if column not in cols:
            cols.append(column)
    return cols


def _combinations(
    df: pl.DataFrame, group_cols: list[str]
) -> list[tuple[dict[str, Any], list[int]]]:
    """Group value combinations present in the frame, with their row indexes.

    A combination holding a null is **omitted**, so the rows under it bind to no
    trace. That is not a dropped row: px omits them from the figure too — it
    groups with ``drop_null_keys=True`` (``plotly/express/_core.py``), so the
    server's own render never plots a null-keyed group — and ``refill.ts``
    applies the same rule from the other side ("a null cell never matches any
    group", mirroring the mask kernel). Server and runtime therefore already
    agree on those rows; the builder just has to stop treating the disagreement
    it feared as certain.

    Omitting rather than refusing keeps the matcher self-checking. If some px
    version *did* emit a trace for a null-keyed group (polars NaN, say, which is
    not a null to ``drop_null_keys`` but normalises to one here), that trace
    reproduces no remaining combination, matches nothing, and the caller freezes
    — the same safe outcome as before, reached by evidence instead of by
    assumption.
    """
    if not group_cols:
        return [({}, list(range(df.height)))]
    grouped = (
        df.with_row_index(_ROW_INDEX)
        .select([_ROW_INDEX, *group_cols])
        .group_by(group_cols, maintain_order=True)
        .agg(pl.col(_ROW_INDEX))
    )
    out: list[tuple[dict[str, Any], list[int]]] = []
    for row in grouped.iter_rows(named=True):
        values = {col: _norm(row[col]) for col in group_cols}
        if any(v is None for v in values.values()):
            continue
        out.append((values, [int(i) for i in row[_ROW_INDEX]]))
    return out


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def build_binding(
    component_meta: dict[str, Any], df: pl.DataFrame, fig: Any = None
) -> BindingTable | None:
    """Binding table for one figure component, or ``None``.

    ``None`` means "not bindable with certainty" — the caller must freeze the
    component with ``binding_miss``. Callers that show the user *why* want
    :func:`build_binding_with_reason` instead.
    """
    return build_binding_with_reason(component_meta, df, fig=fig)[0]


def build_binding_with_reason(
    component_meta: dict[str, Any], df: pl.DataFrame, fig: Any = None
) -> tuple[BindingTable | None, BindingMiss | None]:
    """Like :func:`build_binding`, plus the :class:`BindingMiss` it refused on.

    See the module docstring for the exhaustive list of bail-outs; every one of
    them names itself here, because the caller's freeze reason is read by users.

    ``fig`` is an already-built ``plotly.graph_objects.Figure`` to use as the
    authoritative scaffold instead of calling ``create_figure_from_data``. That
    is the code-mode path (RFC §7, phase 6): the user's Python already ran —
    under RestrictedPython for producer A, a trusted local exec for producer B —
    and ``df`` is the *derived* frame its prologue produced, so re-deriving the
    figure here would both duplicate the work and lose everything the code did
    after the ``px`` call. Sampling is skipped with it: no service downsampled
    the code's own figure, so there is nothing to rebuild uncapped and
    ``sampled`` stays False.
    """
    from depictio.api.v1.services.figure.figure_builder import (
        create_figure_from_data,
        referenced_columns,
    )

    visu_type = component_meta.get("visu_type") or "scatter"
    dict_kwargs = component_meta.get("figure_params") or component_meta.get("dict_kwargs") or {}
    if not isinstance(dict_kwargs, dict) or not isinstance(df, pl.DataFrame) or df.height == 0:
        return None, BindingMiss.NO_DATA
    # The two bail-outs that need no data (whole-frame visu, non-OLS trendline).
    # They live in :func:`planned_figure_miss` so the preflight classifiers can
    # reach them too — same order, same verdicts.
    data_free_miss = planned_figure_miss(component_meta)
    if data_free_miss is not None:
        return None, data_free_miss
    # Past that gate a trendline can only be OLS; the matcher below still needs
    # to know whether one was asked for at all.
    trendline_kind = dict_kwargs.get("trendline") or ""

    referenced = referenced_columns(visu_type, dict_kwargs)
    if not referenced:
        return None, BindingMiss.NO_SOURCE_COLUMNS
    candidates = sorted(c for c in referenced if c in df.columns)
    if not candidates:
        return None, BindingMiss.NO_SOURCE_COLUMNS

    group_cols = _group_columns(dict_kwargs, df)
    combos = _combinations(df, group_cols)
    if not combos:
        # every grouping value is null: px plots nothing to bind
        return None, BindingMiss.ALL_NULL_GROUPING

    # Authoritative figure: the caller's prebuilt one (code mode), else the real
    # service on the unfiltered frame (errata #10).
    sampled = False
    if fig is None:
        stats: dict[str, Any] = {}
        fig = create_figure_from_data(
            df,
            visu_type,
            dict_kwargs,
            theme="light",
            max_points=component_meta.get("max_points"),
            render_stats=stats,
        )
        sampled = bool(stats.get("sampled", False))
        if sampled:
            # Rebuild uncapped: the runtime refills from the full column, so the
            # scaffold's trace set must cover every group of the full frame.
            fig = create_figure_from_data(df, visu_type, dict_kwargs, theme="light", max_points=-1)

    scaffold = fig.to_plotly_json()
    traces_json: list[dict[str, Any]] = list(scaffold.get("data") or [])
    if not traces_json:
        # e.g. create_figure_from_data returned an error figure
        return None, BindingMiss.NO_TRACES

    hypothesis: dict[str, str] = {}
    for kwarg, path in _FIELD_PATH_BY_KWARG.items():
        column = dict_kwargs.get(kwarg)
        if isinstance(column, str) and column in df.columns:
            hypothesis[path] = column

    columns = _Columns(df)
    trace_bindings: list[TraceBinding] = []
    trendlines: list[TrendlineBinding] = []
    trendline_indexes: list[int] = []
    claimed: set[tuple[int, str, str]] = set()
    matched_combos: set[int] = set()
    strip: dict[int, list[str]] = {}
    identity: dict[int, tuple[str, str, str, str]] = {}

    for index, trace_json in enumerate(traces_json):
        hovertemplate = trace_json.get("hovertemplate")
        axes = _axes_of(trace_json)
        identity[index] = (
            str(trace_json.get("name") or ""),
            str(trace_json.get("legendgroup") or ""),
            axes.get("xaxis", ""),
            axes.get("yaxis", ""),
        )
        if isinstance(hovertemplate, str) and _TRENDLINE_MARK in hovertemplate:
            if not trendline_kind:
                # a fitted trace we did not ask for — do not guess
                return None, BindingMiss.TRENDLINE_UNEXPECTED
            trendline_indexes.append(index)
            strip[index] = ["x", "y"]
            continue

        trace_obj = fig.data[index]
        arrays = _collect_arrays(trace_json, trace_obj)

        # 1. Anchor the trace on the fields whose source column the kwargs name.
        anchors: list[tuple[str, list[Any]]] = []
        for path, values in arrays:
            if path not in hypothesis:
                continue
            if values is None:
                return None, BindingMiss.NO_ANCHOR
            anchors.append((path, values))
        if not anchors:
            return None, BindingMiss.NO_ANCHOR
        # (combination, the order its rows appear in inside the trace).
        identity_order = list(range(len(anchors[0][1])))
        matches = [
            (combo_index, identity_order)
            for combo_index, (_, rows) in enumerate(combos)
            if all(
                _equal(values, columns.project(hypothesis[path], rows)) for path, values in anchors
            )
        ]
        if len(matches) != 1 and _order_free_trace(visu_type, trace_json):
            # Same rows, different order (see _permutation) — still this group.
            matches = []
            for combo_index, (_, rows) in enumerate(combos):
                order = _permutation(anchors, hypothesis, columns, rows)
                if order is not None:
                    matches.append((combo_index, order))
        if len(matches) != 1:
            # unmatched or ambiguous — freeze rather than guess
            return None, BindingMiss.TRACE_AMBIGUOUS
        combo_index, order = matches[0]
        group_values, combo_rows = combos[combo_index]
        rows = [combo_rows[position] for position in order]
        key = (combo_index, axes.get("xaxis", ""), axes.get("yaxis", ""))
        if key in claimed:
            return None, BindingMiss.TRACE_COLLISION
        claimed.add(key)
        matched_combos.add(combo_index)

        # 2. Every row-length array must resolve to exactly one source column.
        fields: dict[str, str] = {}
        customdata: list[str] = []
        for path, values in arrays:
            if values is None:
                # Not a flat array. ``customdata`` legitimately is not — px
                # stacks hover_data/custom_data into (n, k) — and binds column
                # by column below; anything else (sub-objects, a 2-D array we
                # have no contract for) stays unrefillable, and we cannot rule
                # out that it is row-bound, so bail.
                matrix = (
                    _as_matrix(_trace_attr(trace_obj, "customdata"))
                    if path == "customdata"
                    else None
                )
                if matrix is None or len(matrix) != len(rows):
                    return None, BindingMiss.ARRAY_2D
                resolved_customdata = _customdata_columns(matrix, candidates, columns, rows)
                if resolved_customdata is None:
                    return None, BindingMiss.COLUMN_AMBIGUOUS
                customdata = resolved_customdata
                continue
            if len(values) != len(rows):
                continue  # not row-bound (e.g. a 2-colour list); leave in scaffold
            guess = hypothesis.get(path)
            if guess is not None and _equal(values, columns.project(guess, rows)):
                fields[path] = guess
                continue
            resolved = [c for c in candidates if _equal(values, columns.project(c, rows))]
            if len(resolved) != 1:
                return None, BindingMiss.COLUMN_AMBIGUOUS
            fields[path] = resolved[0]
        if not fields:
            return None, BindingMiss.NO_BOUND_FIELD

        trace_bindings.append(
            TraceBinding(
                i=index,
                group=dict(group_values),
                fields=fields,
                customdata=customdata,
                axes=axes,
            )
        )
        strip[index] = [*fields, *(["customdata"] if customdata else [])]

    # Every group px could have plotted must be bound, or filtering would drop
    # rows the server would have shown.
    if len(matched_combos) != len(combos):
        return None, BindingMiss.GROUP_UNPLOTTED

    # 3. Trendlines: pair each with its unique raw trace (same name/legendgroup
    #    and subplot), which must carry x and y bindings for the runtime refit.
    by_index = {binding.i: binding for binding in trace_bindings}
    for index in trendline_indexes:
        partners = [
            binding.i
            for binding in trace_bindings
            if identity[binding.i] == identity[index]
            and "x" in binding.fields
            and "y" in binding.fields
        ]
        if len(partners) != 1:
            return None, BindingMiss.TRENDLINE_UNPAIRABLE
        trendlines.append(TrendlineBinding(i=index, on=partners[0]))
    if len(by_index) + len(trendlines) != len(traces_json):
        # an unexplained trace is a mis-render waiting to happen
        return None, BindingMiss.TRACE_UNEXPLAINED

    # 4. Strip the data arrays; layout is untouched.
    for index, paths in strip.items():
        for path in paths:
            _strip_path(traces_json[index], path)

    return (
        BindingTable(
            scaffold=scaffold,
            group_cols=group_cols,
            traces=trace_bindings,
            trendlines=trendlines,
            sampled=sampled,
        ),
        None,
    )
