"""
Dynamic visualization type definitions.

Phase 1: Simplified to support only 4 core visualization types:
- scatter: 2D scatter plot
- line: Line chart for time series
- bar: Categorical bar chart
- box: Distribution box plot

This replaces the comprehensive dynamic discovery with a focused set of
visualizations for initial re-integration.
"""

from typing import Dict, List

from .models import VisualizationDefinition
from .parameter_discovery import discover_all_visualizations

# Phase 1: Core visualization types (expanded to include histogram)
ALLOWED_VISUALIZATIONS = {"scatter", "line", "bar", "box", "histogram"}

# Cache for discovered visualizations to avoid repeated discovery
_visualization_cache: Dict[str, VisualizationDefinition] = {}
_cache_initialized = False


def _ensure_cache_initialized():
    """Initialize the visualization cache if not already done.

    Phase 1: Only include allowed visualization types.
    """
    global _cache_initialized, _visualization_cache
    if not _cache_initialized:
        # Discover all visualizations, then filter to allowed types only
        all_visualizations = discover_all_visualizations()
        _visualization_cache = {
            name: viz_def
            for name, viz_def in all_visualizations.items()
            if name in ALLOWED_VISUALIZATIONS
        }
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
