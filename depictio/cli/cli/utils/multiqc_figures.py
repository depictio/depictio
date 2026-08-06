"""Shared, dependency-light MultiQC figure builder + cache-key hasher.

Single source of truth for turning a parsed MultiQC report into a Plotly figure
and for the figure cache key. Lives in ``depictio.cli.cli.utils`` (a CLI-shipped
package the API already imports from — see ``sample_mapping``) so the **CLI
offline prerender** and the **API render path** produce byte-identical figures
and byte-identical cache keys. Key equality is the correctness lynchpin: the CLI
uploads a figure under ``multiqc_figure_cache_key(...)`` and the server must
resolve the exact same key to serve it.

No Redis / settings / S3 dependencies here — callers own parsing (``multiqc``
global state), caching, locking and I/O. This module only:
  - hashes the figure cache key (pure ``hashlib``),
  - builds one ``go.Figure`` from an already-resident ``multiqc.report``.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
from typing import List, Optional

import plotly.graph_objects as go

from depictio.cli.cli.utils.mantine_templates import (
    ensure_mantine_templates,
    get_theme_template,
)

# 8-digit hex (#rrggbbaa). Some MultiQC heatmaps (e.g. FastQC "Status Checks")
# emit an alpha-bearing hex for "no-data" cells; Plotly's heatmap `colorscale`
# property rejects 8-digit hex at assignment time, so the figure can't even be
# built. We normalise such colors to rgba() (see _patch_colorscale_alpha).
_HEX8_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{8}$")


def _hex8_to_rgba(color: object) -> object:
    """Convert a #rrggbbaa hex string to an rgba() string; pass anything else through."""
    if isinstance(color, str) and _HEX8_COLOR_RE.match(color):
        r, g, b, a = (int(color[i : i + 2], 16) for i in (1, 3, 5, 7))
        return f"rgba({r}, {g}, {b}, {round(a / 255, 4)})"
    return color


def _sanitize_colorscale(value: object) -> object:
    """Rewrite 8-digit-hex colors inside a [[pos, color], ...] colorscale to rgba()."""
    if not isinstance(value, (list, tuple)):
        return value
    out = []
    for entry in value:
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            out.append([entry[0], _hex8_to_rgba(entry[1])])
        else:
            out.append(entry)
    return out


@contextlib.contextmanager
def _patch_colorscale_alpha():
    """Temporarily tolerate 8-digit-hex colorscales during figure construction.

    Plotly validates the `colorscale` property on assignment and raises on
    8-digit hex, which would abort MultiQC's ``get_figure``. We wrap the
    validator so that, *only* when the original validation fails, the colorscale
    is retried with its alpha-hex colors converted to rgba(). Valid colorscales
    are untouched, and the original validator is always restored.
    """
    from _plotly_utils.basevalidators import ColorscaleValidator

    original = ColorscaleValidator.validate_coerce

    def patched(self, v):
        try:
            return original(self, v)
        except ValueError:
            return original(self, _sanitize_colorscale(v))

    # setattr (not direct assignment) so the temporary method swap on this
    # third-party validator class doesn't trip static method-type checks.
    setattr(ColorscaleValidator, "validate_coerce", patched)
    try:
        yield
    finally:
        setattr(ColorscaleValidator, "validate_coerce", original)


def multiqc_figure_cache_key(
    s3_locations: List[str],
    module: str,
    plot: str,
    dataset_id: Optional[str] = None,
    theme: str = "light",
    filter_sig: Optional[str] = None,
    dc_id: Optional[str] = None,
) -> str:
    """Generate the cache key for a rendered MultiQC figure.

    Deterministic over the sorted S3 locations plus module/plot/dataset/theme
    (and optional filter signature). ``dc_id`` is embedded literally in the key
    so a DC-scoped invalidation (``cache.delete_pattern(f"dc={dc_id}")``) can
    drop every figure variant for that DC.

    This is the ONE definition shared by the API render path and the CLI offline
    prerender; keep both callers routed through here so their keys never drift.
    """
    sorted_locations = sorted(s3_locations)
    key_parts = [
        "|".join(sorted_locations),
        module,
        plot,
        str(dataset_id),
        theme,
        filter_sig or "",
    ]
    key_str = "::".join(key_parts)
    hash_digest = hashlib.sha256(key_str.encode()).hexdigest()[:16]
    return f"multiqc:figure:dc={dc_id or 'none'}:{hash_digest}"


def figure_cache_key_sha(cache_key: str) -> str:
    """Trailing hash segment of a bare figure cache key (``...:<16-hex>``).

    The prerendered figure for a key is stored under this segment as its filename
    — on disk (``multiqc_prerender_store``), on S3 (``multiqc_s3_prerender``) and
    at CLI upload time. Kept here next to the key that produces it so the three
    stores can never drift on how they name a figure.
    """
    return cache_key.rsplit(":", 1)[-1]


def build_multiqc_figure(
    module: str,
    plot: str,
    dataset_id: Optional[str] = None,
    theme: str = "light",
) -> go.Figure:
    """Build one Plotly figure from the currently-resident ``multiqc.report``.

    The caller MUST have already parsed the report(s) into MultiQC's module-global
    state (``multiqc.parse_logs``) and, in a threaded server, hold the MultiQC
    lock across parse + this call. Raises ``ValueError`` (from ``multiqc.get_plot``)
    if ``module``/``plot`` is not present — callers may catch and re-parse.

    Applies the ``mantine_light``/``mantine_dark`` template so the serialized
    figure dict is identical whether built by the CLI or the API worker.
    """
    import multiqc

    ensure_mantine_templates()

    plot_obj = multiqc.get_plot(module, plot)
    if not plot_obj or not hasattr(plot_obj, "get_figure"):
        raise ValueError(f"Failed to get plot object for {module}/{plot}")

    # Tolerate alpha-hex colorscales (e.g. FastQC "Status Checks") that Plotly
    # would otherwise reject when the heatmap trace is constructed.
    with _patch_colorscale_alpha():
        fig = plot_obj.get_figure(dataset_id=dataset_id if dataset_id else 0)

    fig.update_layout(
        title=f"{module.upper()}: {plot}",
        template=get_theme_template(theme),
        autosize=True,
        width=None,
        height=None,
        margin=dict(t=60, l=60, r=60, b=60),
    )
    return fig
