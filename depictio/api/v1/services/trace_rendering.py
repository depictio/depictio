"""Whether an exported trace is drawn on the GPU or as SVG. It is never the GPU.

Plotly offers the same scatter twice: ``scatter`` builds one DOM node per point,
``scattergl`` uploads them to a WebGL context. Inside the viewer that is a speed
tradeoff, and the viewer picks the GPU — the baseline CSP even carries
``'unsafe-eval'`` so regl can compile its draw commands.

An export is not the viewer, and the tradeoff inverts:

* **WebGL contexts are finite and shared.** A browser allows a renderer process
  on the order of sixteen live contexts, and every same-origin frame lands in
  that one process. The cost of ``scattergl`` therefore scales with how many
  panels a page delivers, not with how big any one of them is. We do not know
  the host page's composition, so we cannot know what is left of its budget.
* **The consumer cannot see the dependency.** A ``scattergl`` in a spec hands
  them a GPU requirement they did not ask for, and it also costs them headless
  capture, print, and any machine whose GPU is blocklisted.
* **Being wrong is asymmetric.** Toward SVG costs some render time; toward
  WebGL can cost them the figure entirely, with "WebGL is not supported by your
  browser" as the only clue.

So exports have no threshold to tune: they are SVG. What bounds an export is the
row count, which ``services/advanced_viz/data.py`` caps and reports, and
``performance.figure_max_points`` — not a switch to the GPU.

``scatter3d`` and ``surface`` are deliberately absent from ``SVG_EQUIVALENT``:
they have no SVG form, so there is no decision to make and downgrading them
would mean dropping the trace.
"""

from __future__ import annotations

#: The scatter type every exported spec uses. Named rather than inlined so the
#: reasoning above has one place to live and each call site can point at it.
EXPORT_SCATTER_TYPE = "scatter"

#: GPU trace types that have a faithful SVG counterpart.
SVG_EQUIVALENT: dict[str, str] = {
    "scattergl": "scatter",
    "scatterpolargl": "scatterpolar",
}


def svg_equivalent(trace_type: str) -> str | None:
    """The SVG form of ``trace_type``, or ``None`` when it has none."""
    return SVG_EQUIVALENT.get(trace_type)
