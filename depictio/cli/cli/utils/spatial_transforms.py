"""2D affine algebra for SpatialData / OME-NGFF coordinate transformations.

Pure functions, no I/O. An :data:`Affine2D` is the tuple ``(a, b, c, d, e, f)``
of the map ``x' = a*x + b*y + c``, ``y' = d*x + e*y + f``.

NGFF transforms are written per axis (``cyx`` for an image, ``xy`` for
shapes). :func:`from_ngff` keeps the ``x`` and ``y`` components and drops the
others (channel, z, time), so the image and the shapes land in the same 2D
plane whatever their axis order. Supported types: ``identity``, ``scale``,
``translation``, ``affine`` and ``sequence`` (composed in order); any other
type raises :class:`UnsupportedTransformError`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

Affine2D = tuple[float, float, float, float, float, float]

IDENTITY: Affine2D = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)


class UnsupportedTransformError(ValueError):
    """A coordinate transformation that cannot be reduced to a 2D affine map."""


def scale(sx: float, sy: float) -> Affine2D:
    return (float(sx), 0.0, 0.0, 0.0, float(sy), 0.0)


def translation(tx: float, ty: float) -> Affine2D:
    return (1.0, 0.0, float(tx), 0.0, 1.0, float(ty))


def compose(first: Affine2D, then: Affine2D) -> Affine2D:
    """The map applying ``first``, then ``then``."""
    a1, b1, c1, d1, e1, f1 = first
    a2, b2, c2, d2, e2, f2 = then
    return (
        a2 * a1 + b2 * d1,
        a2 * b1 + b2 * e1,
        a2 * c1 + b2 * f1 + c2,
        d2 * a1 + e2 * d1,
        d2 * b1 + e2 * e1,
        d2 * c1 + e2 * f1 + f2,
    )


def invert(m: Affine2D) -> Affine2D:
    a, b, c, d, e, f = m
    det = a * e - b * d
    if det == 0 or not np.isfinite(det):
        raise UnsupportedTransformError(f"transformation {m} is not invertible")
    ia, ib, id_, ie = e / det, -b / det, -d / det, a / det
    return (ia, ib, -(ia * c + ib * f), id_, ie, -(id_ * c + ie * f))


def apply(m: Affine2D, xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a, b, c, d, e, f = m
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    return a * xs + b * ys + c, d * xs + e * ys + f


def axis_names(axes: Any) -> list[str]:
    """Axis names from an NGFF ``axes`` list (dicts with ``name``, or strings)."""
    names: list[str] = []
    for axis in axes or []:
        name = axis.get("name") if isinstance(axis, dict) else axis
        if not isinstance(name, str):
            raise UnsupportedTransformError(f"malformed axes list: {axes!r}")
        names.append(name)
    return names


def system_name(end: Any) -> str | None:
    """Coordinate-system name of a transform's ``input`` / ``output`` (dict or string)."""
    if isinstance(end, dict):
        name = end.get("name")
        return name if isinstance(name, str) else None
    return end if isinstance(end, str) else None


def _end_axes(end: Any) -> list[str] | None:
    if isinstance(end, dict) and end.get("axes"):
        return axis_names(end["axes"])
    return None


def _xy_index(axes: Sequence[str], what: str, transform_type: str) -> tuple[int, int]:
    if "x" not in axes or "y" not in axes:
        raise UnsupportedTransformError(
            f"{transform_type} transformation {what} axes {list(axes)} lack x and y"
        )
    return axes.index("x"), axes.index("y")


def _vector(t: dict, key: str, axes: Sequence[str]) -> tuple[float, float]:
    values = t.get(key)
    if not isinstance(values, list):
        raise UnsupportedTransformError(
            f"{t.get('type')} transformation without an inline {key!r} list is not supported"
        )
    if len(values) != len(axes):
        raise UnsupportedTransformError(
            f"{t.get('type')} {key} {values} does not match the axes {list(axes)}"
        )
    ix, iy = _xy_index(axes, "input", str(t.get("type")))
    return float(values[ix]), float(values[iy])


def _affine(t: dict, in_axes: Sequence[str], out_axes: Sequence[str]) -> Affine2D:
    raw = t.get("affine")
    if not isinstance(raw, list) or not raw:
        raise UnsupportedTransformError("affine transformation without an inline matrix")
    n_in, n_out = len(in_axes), len(out_axes)
    matrix = np.asarray(raw, dtype=np.float64)
    if matrix.ndim == 1:
        # NGFF 0.4 flat row-major form: n_out rows of n_in + 1 values.
        if matrix.size != n_out * (n_in + 1):
            raise UnsupportedTransformError(f"affine of size {matrix.size} does not match axes")
        matrix = matrix.reshape(n_out, n_in + 1)
    if matrix.shape[1] != n_in + 1 or matrix.shape[0] not in (n_out, n_out + 1):
        raise UnsupportedTransformError(
            f"affine of shape {matrix.shape} does not match {n_in} input and {n_out} output axes"
        )
    ix, iy = _xy_index(in_axes, "input", "affine")
    ox, oy = _xy_index(out_axes, "output", "affine")
    row_x, row_y = matrix[ox], matrix[oy]
    return (row_x[ix], row_x[iy], row_x[-1], row_y[ix], row_y[iy], row_y[-1])


def from_ngff(t: dict, default_axes: Sequence[str]) -> tuple[Affine2D, list[str]]:
    """The 2D part of one NGFF transformation, and the axes of its output space.

    ``default_axes`` names the input axes when the transform does not list them
    (dataset-level transforms, members of a sequence).
    """
    if not isinstance(t, dict):
        raise UnsupportedTransformError(f"malformed transformation: {t!r}")
    kind = t.get("type")
    in_axes = _end_axes(t.get("input")) or list(default_axes)
    out_axes = _end_axes(t.get("output")) or in_axes
    if kind == "identity":
        return IDENTITY, out_axes
    if kind == "scale":
        return scale(*_vector(t, "scale", in_axes)), out_axes
    if kind == "translation":
        return translation(*_vector(t, "translation", in_axes)), out_axes
    if kind == "affine":
        return _affine(t, in_axes, out_axes), out_axes
    if kind == "sequence":
        steps = t.get("transformations")
        if not isinstance(steps, list):
            raise UnsupportedTransformError("sequence transformation without transformations")
        total, axes = IDENTITY, in_axes
        for step in steps:
            m, axes = from_ngff(step, axes)
            total = compose(total, m)
        return total, (_end_axes(t.get("output")) or axes)
    raise UnsupportedTransformError(f"coordinate transformation type {kind!r} is not supported")


def to_systems(
    transforms: Any, default_axes: Sequence[str], default_system: str = "global"
) -> dict[str, Affine2D]:
    """Map each target coordinate system to the element's 2D transform into it.

    A transform without a named output is taken as mapping to ``default_system``.
    """
    systems: dict[str, Affine2D] = {}
    for t in transforms or []:
        if not isinstance(t, dict):
            raise UnsupportedTransformError(f"malformed transformation: {t!r}")
        name = system_name(t.get("output")) or default_system
        systems[name], _ = from_ngff(t, default_axes)
    return systems


def pick_system(element: Sequence[str], image: Sequence[str]) -> str | None:
    """The coordinate system shared by an element and the image, ``global`` first."""
    shared = [name for name in image if name in element]
    if not shared:
        return None
    return "global" if "global" in shared else shared[0]
