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
NaN-size row dropping, category ordering, re-sorting, an aggregating trace, a
group px did not emit — shows up as "no combination reproduces this array" and
returns ``None``. A frozen figure is correct; a mis-bound one is wrong, so
**every ambiguity returns ``None``** and the caller freezes with
``binding_miss``:

* no anchor field (nothing in the trace we can tie back to a kwarg column);
* a trace matching zero or 2+ group combinations;
* a group combination px emitted no trace for (rows would silently vanish);
* a row-length array in a trace whose source column is undeterminable, or
  determinable in more than one way (e.g. 2-D ``customdata`` from
  ``hover_data``/``custom_data``: the runtime writes 1-D arrays, so those
  figures freeze);
* a whole-frame visualisation (heatmap, scatter_matrix, parallel_*, imshow,
  scatter_geo, choropleth — ``_WHOLE_FRAME_VISU``);
* a null in any grouping column (a null never matches a predicate at runtime);
* a non-OLS ``trendline`` (the runtime only refits closed-form 1-predictor OLS).

Stripping convention (what ``refill.ts`` expects)
-------------------------------------------------
``refill.ts`` deep-clones ``scaffold`` and **writes** every bound field with
``setPath`` (creating intermediates as needed), so bound arrays must simply be
**absent** from the scaffold — we ``del`` them rather than emptying them. An
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
from typing import Any

import polars as pl

from depictio.models.models.serverless import BindingTable, TraceBinding, TrendlineBinding

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


def _equal(left: list[Any], right: list[Any]) -> bool:
    return len(left) == len(right) and all(a == b for a, b in zip(left, right))


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
        try:
            raw = trace_obj[key]
        except (KeyError, ValueError, TypeError):
            raw = None
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
) -> list[tuple[dict[str, Any], list[int]]] | None:
    """Group value combinations present in the frame, with their row indexes.
    ``None`` when a grouping value is null (never matchable at runtime)."""
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
            return None
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
    component with ``binding_miss``. See the module docstring for the exhaustive
    list of bail-outs.

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
        _WHOLE_FRAME_VISU,
        create_figure_from_data,
        referenced_columns,
    )

    visu_type = component_meta.get("visu_type") or "scatter"
    dict_kwargs = component_meta.get("figure_params") or component_meta.get("dict_kwargs") or {}
    if not isinstance(dict_kwargs, dict) or not isinstance(df, pl.DataFrame) or df.height == 0:
        return None
    if str(visu_type).lower() in _WHOLE_FRAME_VISU:
        return None

    trendline_kind = dict_kwargs.get("trendline") or ""
    if trendline_kind and str(trendline_kind).lower() != "ols":
        return None  # the runtime only refits closed-form 1-predictor OLS

    referenced = referenced_columns(visu_type, dict_kwargs)
    if not referenced:
        return None
    candidates = sorted(c for c in referenced if c in df.columns)
    if not candidates:
        return None

    group_cols = _group_columns(dict_kwargs, df)
    combos = _combinations(df, group_cols)
    if combos is None:
        return None

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
        return None  # no traces (e.g. create_figure_from_data returned an error figure)

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
                return None  # a fitted trace we did not ask for — do not guess
            trendline_indexes.append(index)
            strip[index] = ["x", "y"]
            continue

        arrays = _collect_arrays(trace_json, fig.data[index])

        # 1. Anchor the trace on the fields whose source column the kwargs name.
        anchors = [(path, values) for path, values in arrays if path in hypothesis]
        if not anchors or any(values is None for _, values in anchors):
            return None
        matches = [
            combo_index
            for combo_index, (_, rows) in enumerate(combos)
            if all(
                values is not None and _equal(values, columns.project(hypothesis[path], rows))  # type: ignore[arg-type]
                for path, values in anchors
            )
        ]
        if len(matches) != 1:
            return None  # unmatched or ambiguous — freeze rather than guess
        combo_index = matches[0]
        group_values, rows = combos[combo_index]
        key = (combo_index, axes.get("xaxis", ""), axes.get("yaxis", ""))
        if key in claimed:
            return None  # two traces claim the same group in the same subplot
        claimed.add(key)
        matched_combos.add(combo_index)

        # 2. Every row-length array must resolve to exactly one source column.
        fields: dict[str, str] = {}
        for path, values in arrays:
            if values is None:
                # Unflattenable (2-D customdata, sub-objects). Only fatal when
                # it is row-bound, which we cannot rule out — so bail.
                return None
            if len(values) != len(rows):
                continue  # not row-bound (e.g. a 2-colour list); leave in scaffold
            guess = hypothesis.get(path)
            if guess is not None and _equal(values, columns.project(guess, rows)):
                fields[path] = guess
                continue
            resolved = [c for c in candidates if _equal(values, columns.project(c, rows))]
            if len(resolved) != 1:
                return None
            fields[path] = resolved[0]
        if not fields:
            return None

        trace_bindings.append(
            TraceBinding(i=index, group=dict(group_values), fields=fields, axes=axes)
        )
        strip[index] = list(fields)

    # Every group px could have plotted must be bound, or filtering would drop
    # rows the server would have shown.
    if len(matched_combos) != len(combos):
        return None

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
            return None
        trendlines.append(TrendlineBinding(i=index, on=partners[0]))
    if len(by_index) + len(trendlines) != len(traces_json):
        return None  # an unexplained trace is a mis-render waiting to happen

    # 4. Strip the data arrays; layout is untouched.
    for index, paths in strip.items():
        for path in paths:
            _strip_path(traces_json[index], path)

    return BindingTable(
        scaffold=scaffold,
        group_cols=group_cols,
        traces=trace_bindings,
        trendlines=trendlines,
        sampled=sampled,
    )
