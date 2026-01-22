"""
Plotly Figure Customization System.

This module provides a declarative, Vizro-inspired system for applying
minimal post-processing customizations to Plotly figures. It integrates
seamlessly with the YAML dashboard configuration system.

Key features:
- Axis scale changes (linear, log, symlog)
- Reference lines (hline, vline, diagonal)
- Point highlighting (for UMAP, Volcano plots)
- Annotation overlays
- Shape additions

Example YAML usage:
    stored_metadata:
      - index: "scatter-001"
        component_type: "figure"
        visu_type: "scatter"
        dict_kwargs:
          x: "x_column"
          y: "y_column"
        customizations:
          axes:
            x:
              scale: "log"
              title: "Log X Axis"
            y:
              scale: "linear"
              range: [0, 100]
          reference_lines:
            - type: "hline"
              y: 0.05
              line_dash: "dash"
              line_color: "red"
              annotation_text: "p=0.05 threshold"
          highlights:
            - column: "significant"
              value: true
              marker_color: "red"
              marker_size: 12
"""

from .models import (
    AnnotationConfig,
    AnnotationPosition,
    AxesConfig,
    AxisConfig,
    AxisScale,
    ColorbarConfig,
    FigureCustomizations,
    HighlightCondition,
    HighlightConditionOperator,
    HighlightConfig,
    HighlightStyle,
    HoverConfig,
    LegendConfig,
    LineStyle,
    ReferenceLineConfig,
    ReferenceLineType,
    ShapeConfig,
)
from .presets import (
    log_scale_customizations,
    merge_customizations,
    qq_plot_customizations,
    regression_plot_customizations,
    threshold_customizations,
    time_series_customizations,
    umap_cluster_customizations,
    umap_highlight_customizations,
    volcano_plot_customizations,
)
from .processor import apply_customizations

__all__ = [
    # Core models
    "FigureCustomizations",
    "AxesConfig",
    "AxisConfig",
    "AxisScale",
    "ReferenceLineConfig",
    "ReferenceLineType",
    "LineStyle",
    "HighlightConfig",
    "HighlightCondition",
    "HighlightConditionOperator",
    "HighlightStyle",
    "AnnotationConfig",
    "AnnotationPosition",
    "ShapeConfig",
    "LegendConfig",
    "ColorbarConfig",
    "HoverConfig",
    # Processor
    "apply_customizations",
    # Presets
    "volcano_plot_customizations",
    "umap_highlight_customizations",
    "umap_cluster_customizations",
    "regression_plot_customizations",
    "qq_plot_customizations",
    "time_series_customizations",
    "threshold_customizations",
    "log_scale_customizations",
    "merge_customizations",
]
