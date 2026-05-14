"""
Visualization registry for the figure builder.

The registry is built lazily by `discover_all_visualizations()` (in
`parameter_discovery.py`), which inspects Plotly Express signatures and
custom builders (UMAP, complex heatmap). This module restricts the registry
to a curated set (`ALLOWED_VISUALIZATIONS`) and applies hand-authored
labels + descriptions so the React figure builder dropdown stays
human-readable.

When adding a visualization:
1. Drop the name from `_DISABLED_VISUALIZATIONS` if present (parameter_discovery.py).
2. Ensure an icon is mapped in `_VISUALIZATION_ICONS` (parameter_discovery.py).
3. Add it to `ALLOWED_VISUALIZATIONS` here.
4. Add a `(label, description)` row to `VIZ_LABELS_DESCRIPTIONS` here.
"""

from typing import Dict, List

from .models import VisualizationDefinition
from .parameter_discovery import discover_all_visualizations

# Curated set of visualization types exposed to the figure builder.
#
# `heatmap` and `scatter_matrix` were excluded on purpose: the first is not a
# Plotly Express constructor of its own (heatmap rendering goes through the
# complex-heatmap path in core.py), and scatter_matrix has a per-viz parameter
# shape that doesn't match the rest of the builder cleanly. Add them back only
# alongside dedicated builder support.
ALLOWED_VISUALIZATIONS = {
    "scatter",
    "line",
    "bar",
    "box",
    "histogram",
    "violin",
    "ecdf",
    "density_heatmap",
    "density_contour",
    "area",
    "funnel",
    "strip",
}

# Hand-authored display metadata. Override Plotly's auto-generated labels and
# docstring-derived descriptions with concise, user-facing copy. Keys MUST be
# present in `ALLOWED_VISUALIZATIONS`. Format: {name: (label, description)}.
VIZ_LABELS_DESCRIPTIONS: Dict[str, tuple[str, str]] = {
    "scatter": (
        "Scatter Plot",
        "Compare two numeric variables — each point is a row, optionally colored or sized by a third column.",
    ),
    "line": (
        "Line Chart",
        "Show a value over an ordered axis (time, position, rank).",
    ),
    "bar": (
        "Bar Chart",
        "Compare a numeric value across categories.",
    ),
    "histogram": (
        "Histogram",
        "Frequency distribution of a single numeric variable.",
    ),
    "box": (
        "Box Plot",
        "Distribution summary (median, IQR, outliers) for one numeric variable, optionally grouped.",
    ),
    "violin": (
        "Violin Plot",
        "Distribution shape with kernel density — use when you need more detail than a box plot.",
    ),
    "ecdf": (
        "ECDF",
        "Empirical cumulative distribution — fraction of values at or below each point.",
    ),
    "density_heatmap": (
        "Density Heatmap",
        "2D bin counts as a heatmap — shows where points concentrate.",
    ),
    "density_contour": (
        "Density Contour",
        "2D bin counts as contour lines — smoother alternative to density heatmap.",
    ),
    "area": (
        "Area Chart",
        "Filled line chart — emphasize cumulative quantities or composition over an axis.",
    ),
    "funnel": (
        "Funnel",
        "Stage-by-stage drop-off (e.g. conversion).",
    ),
    "strip": (
        "Strip Plot",
        "One-dimensional scatter — every observation as a tick along a numeric axis.",
    ),
}

# Cache for discovered visualizations to avoid repeated discovery.
_visualization_cache: Dict[str, VisualizationDefinition] = {}
_cache_initialized = False


def _ensure_cache_initialized():
    """Build the visualization cache once.

    Discovers all visualizations, filters to `ALLOWED_VISUALIZATIONS`, and
    overrides label/description with hand-authored copy from
    `VIZ_LABELS_DESCRIPTIONS` so the dropdown UI is consistent.
    """
    global _cache_initialized, _visualization_cache
    if _cache_initialized:
        return

    all_visualizations = discover_all_visualizations()
    _visualization_cache = {
        name: viz_def
        for name, viz_def in all_visualizations.items()
        if name in ALLOWED_VISUALIZATIONS
    }

    for name, (label, description) in VIZ_LABELS_DESCRIPTIONS.items():
        if name in _visualization_cache:
            _visualization_cache[name].label = label
            _visualization_cache[name].description = description

    _cache_initialized = True


def get_visualization_registry() -> Dict[str, VisualizationDefinition]:
    """Get the registry of all available visualizations."""
    _ensure_cache_initialized()
    return _visualization_cache


def get_visualization_definition(name: str) -> VisualizationDefinition:
    """Get visualization definition by name."""
    registry = get_visualization_registry()
    if name not in registry:
        raise ValueError(f"Unknown visualization type: {name}")
    return registry[name]


def get_available_visualizations() -> List[VisualizationDefinition]:
    """Get list of all available visualizations."""
    registry = get_visualization_registry()
    return list(registry.values())


def get_visualization_names() -> List[str]:
    """Get list of visualization names."""
    registry = get_visualization_registry()
    return list(registry.keys())
