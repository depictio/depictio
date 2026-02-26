"""plotly-complexheatmap: ComplexHeatmap-style visualizations with Plotly.

Provides clustered heatmaps with dendrograms, annotation tracks, and split
heatmaps using native Plotly figures with WebGL-first rendering.
"""

from plotly_complexheatmap.annotations import HeatmapAnnotation
from plotly_complexheatmap.heatmap import ComplexHeatmap

__version__ = "0.1.0"
__all__ = ["ComplexHeatmap", "HeatmapAnnotation"]
