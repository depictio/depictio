"""
Dynamic visualization type definitions.

This module provides future-proof definitions for all supported Plotly Express
visualizations using dynamic parameter discovery. This replaces hardcoded
definitions and automatically adapts to new Plotly versions.
"""

from typing import Dict, List

from .models import VisualizationDefinition
from .parameter_discovery import discover_all_visualizations

# Cache for discovered visualizations to avoid repeated discovery
_visualization_cache: Dict[str, VisualizationDefinition] = {}
_cache_initialized = False


def _ensure_cache_initialized():
    """Initialize the visualization cache if not already done."""
    global _cache_initialized, _visualization_cache
    if not _cache_initialized:
        _visualization_cache = discover_all_visualizations()
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
