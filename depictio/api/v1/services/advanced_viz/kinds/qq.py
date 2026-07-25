"""QQ plot — observed vs expected -log10(p) under a uniform null.

Port of ``advanced_viz/QQRenderer.tsx`` (the ``figure`` useMemo, lines 118-330).
Faithful details that are easy to get wrong:

* ``expected`` is ``-log10((k+1)/(n+1))`` over *ascending* p, so it descends from
  index 0 — the maximum is at index 0, not the end.
* λ (genomic inflation) uses the same Beasley-Springer-Moro normal-quantile
  approximation as the TS ``chi2InvCdf1df``, divided by 0.4549 (median χ², 1 df).
  Reimplementing it with ``statistics.NormalDist`` would give subtly different
  numbers and break parity, so the approximation is ported as-is.
* Axis ranges are independent (qqman / Hail convention): X is bounded by the
  expected maximum, Y grows freely with significant hits, and the identity
  diagonal spans ``max(x, y)`` so it visibly exits the frame when the tail breaks.
"""

from __future__ import annotations

import math
from typing import Any

from depictio.api.v1.services.advanced_viz.figure_registry import register
from depictio.api.v1.services.advanced_viz.palette import TAB10_PALETTE, stable_color_map

#: Median of the chi-square distribution with 1 df — the λ denominator.
_CHI2_MEDIAN_1DF = 0.4549

_DEFAULT_POINT_COLOR = "#4C72B0"


def _columns(config: dict[str, Any]) -> list[str | None]:
    return [
        config.get("p_value_col") or "p_value",
        config.get("feature_id_col"),
        config.get("category_col"),
    ]


def _chi2_inv_cdf_1df(p: float) -> float:
    """Chi-square inverse CDF for 1 df, via Beasley-Springer-Moro.

    Ported verbatim from ``QQRenderer.tsx:104-116`` so λ matches the browser's
    value exactly.
    """
    if p <= 0:
        return math.inf
    if p >= 1:
        return 0.0
    a = 1 - p
    t = math.sqrt(-2 * math.log(min(a, 1 - a)))
    num = 2.515517 + 0.802853 * t + 0.010328 * t * t
    den = 1 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t * t * t
    z = (1 if a > 0.5 else -1) * (t - num / den)
    return z * z


def _lambda_for(sorted_ps: list[float]) -> float:
    """Genomic inflation factor from an ascending list of p-values."""
    if not sorted_ps:
        return math.nan
    mid = sorted_ps[len(sorted_ps) // 2]
    return _chi2_inv_cdf_1df(mid) / _CHI2_MEDIAN_1DF


def _build_series(ps: list[Any], idxs: list[int], ids: list[Any] | None) -> dict[str, Any]:
    """Sort valid p-values ascending and derive the observed/expected pair."""
    valid: list[tuple[int, float]] = []
    for i in idxs:
        p = ps[i] if i < len(ps) else None
        try:
            pf = float(p) if p is not None else None
        except (TypeError, ValueError):
            continue
        if pf is not None and 0 < pf <= 1:
            valid.append((i, pf))
    valid.sort(key=lambda d: d[1])

    n = len(valid)
    observed = [-math.log10(p) for _, p in valid]
    expected = [-math.log10((k + 1) / (n + 1)) for k in range(n)]
    ids_sorted = [str(ids[i] or "") if ids else "" for i, _ in valid]
    return {
        "expected": expected,
        "observed": observed,
        "ids": ids_sorted,
        "ps": [p for _, p in valid],
        "n": n,
    }


@register("qq", columns=_columns)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    is_dark = theme == "dark"
    p_col = config.get("p_value_col") or "p_value"
    id_col = config.get("feature_id_col")
    cat_col = config.get("category_col")

    show_ci = bool(controls.get("show_ci", config.get("show_ci", True)))
    show_identity = bool(controls.get("show_identity", True))
    point_size = int(controls.get("point_size", 5))
    top_n_labels = int(controls.get("top_n_labels", 0))

    ps = rows.get(p_col) or []
    ids = rows.get(id_col) if id_col else None
    cats = rows.get(cat_col) if cat_col else None

    traces: list[dict[str, Any]] = []
    expected_max = 0.0
    observed_max = 0.0
    lambda_overall = math.nan
    ci_lines: dict[str, list[float]] | None = None

    if cats:
        colour_by_cat = stable_color_map({str(c) for c in cats}, TAB10_PALETTE)
        all_ps: list[float] = []
        for cat in sorted({str(c) for c in cats}):
            idxs = [i for i, c in enumerate(cats) if str(c) == cat]
            series = _build_series(ps, idxs, ids)
            if series["n"] == 0:
                continue
            expected_max = max(expected_max, series["expected"][0])
            observed_max = max(observed_max, *series["observed"])
            all_ps.extend(series["ps"])
            traces.append(
                {
                    "type": "scattergl",
                    "mode": "markers",
                    "name": cat,
                    "x": series["expected"],
                    "y": series["observed"],
                    "text": series["ids"],
                    "hovertemplate": (
                        ("<b>%{text}</b><br>" if series["ids"] and series["ids"][0] else "")
                        + "expected: %{x:.3f}<br>observed: %{y:.3f}<extra></extra>"
                    ),
                    "marker": {
                        "color": colour_by_cat.get(cat),
                        "size": point_size,
                        "opacity": 0.85,
                    },
                }
            )
        lambda_overall = _lambda_for(sorted(all_ps))
    else:
        series = _build_series(ps, list(range(len(ps))), ids)
        expected_max = series["expected"][0] if series["expected"] else 0.0
        observed_max = max([0.0, *series["observed"]])
        lambda_overall = _lambda_for(series["ps"])
        traces.append(
            {
                "type": "scattergl",
                "mode": "markers",
                "x": series["expected"],
                "y": series["observed"],
                "text": series["ids"],
                "hovertemplate": (
                    ("<b>%{text}</b><br>" if series["ids"] and series["ids"][0] else "")
                    + "expected: %{x:.3f}<br>observed: %{y:.3f}<extra></extra>"
                ),
                "marker": {
                    "color": _DEFAULT_POINT_COLOR,
                    "size": point_size,
                    "opacity": 0.85,
                },
            }
        )

        if top_n_labels > 0 and series["ids"] and series["ids"][0]:
            ranked = sorted(
                range(len(series["observed"])),
                key=lambda i: series["observed"][i],
                reverse=True,
            )[:top_n_labels]
            traces.append(
                {
                    "type": "scatter",
                    "mode": "text",
                    "x": [series["expected"][i] for i in ranked],
                    "y": [series["observed"][i] + observed_max * 0.03 for i in ranked],
                    "text": [series["ids"][i] for i in ranked],
                    "textposition": "top center",
                    "textfont": {
                        "size": 10,
                        "color": "rgba(255,255,255,0.9)" if is_dark else "rgba(0,0,0,0.85)",
                    },
                    "hoverinfo": "skip",
                    "showlegend": False,
                }
            )

        if show_ci:
            n = series["n"]
            xs: list[float] = []
            lower: list[float] = []
            upper: list[float] = []
            for k in range(1, n + 1):
                p = k / (n + 1)
                variance = (p * (1 - p)) / (n + 2)
                se = math.sqrt(variance) / (math.log(10) * max(p, 1e-12))
                e_exp = -math.log10(p)
                xs.append(e_exp)
                lower.append(max(0.0, e_exp - 1.96 * se))
                upper.append(e_exp + 1.96 * se)
            ci_lines = {"x": xs, "lower": lower, "upper": upper}

    if ci_lines:
        # Prepended so the band paints behind the points; the second trace fills
        # down to the first via `tonexty`.
        traces[0:0] = [
            {
                "type": "scatter",
                "mode": "lines",
                "x": ci_lines["x"],
                "y": ci_lines["upper"],
                "line": {"width": 0},
                "showlegend": False,
                "hoverinfo": "skip",
            },
            {
                "type": "scatter",
                "mode": "lines",
                "x": ci_lines["x"],
                "y": ci_lines["lower"],
                "fill": "tonexty",
                "fillcolor": "rgba(255,255,255,0.10)" if is_dark else "rgba(0,0,0,0.08)",
                "line": {"width": 0},
                "showlegend": False,
                "hoverinfo": "skip",
            },
        ]

    x_upper = expected_max * 1.05
    y_upper = observed_max * 1.05
    diagonal_upper = max(x_upper, y_upper)

    annotations: list[dict[str, Any]] = []
    if not math.isnan(lambda_overall):
        annotations.append(
            {
                "xref": "paper",
                "yref": "paper",
                "x": 0.02,
                "y": 0.98,
                "xanchor": "left",
                "yanchor": "top",
                "text": f"λ = {lambda_overall:.3f}",
                "showarrow": False,
                "font": {"size": 12, "color": "#fff" if is_dark else "#222"},
                "bgcolor": "rgba(20,20,20,0.6)" if is_dark else "rgba(255,255,255,0.7)",
                "bordercolor": "rgba(255,255,255,0.3)" if is_dark else "rgba(0,0,0,0.2)",
                "borderwidth": 1,
                "borderpad": 4,
            }
        )

    return {
        "data": traces,
        "layout": {
            "margin": {"l": 60, "r": 20, "t": 20, "b": 50},
            "xaxis": {"title": {"text": "-log10(expected)"}, "range": [0, x_upper]},
            "yaxis": {"title": {"text": "-log10(observed)"}, "range": [0, y_upper]},
            "shapes": (
                [
                    {
                        "type": "line",
                        "x0": 0,
                        "y0": 0,
                        "x1": diagonal_upper,
                        "y1": diagonal_upper,
                        "line": {
                            "dash": "dash",
                            "color": "#ddd" if is_dark else "#444",
                            "width": 1,
                        },
                    }
                ]
                if show_identity
                else []
            ),
            "annotations": annotations,
            "showlegend": bool(cats),
            "autosize": True,
        },
    }
