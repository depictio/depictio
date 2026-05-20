"""plotly-upset: UpSet plot visualizations with Plotly.

Interactive set intersection plots with annotation tracks using native
Plotly figures.
"""

from plotly_upset.annotations import UpSetAnnotation
from plotly_upset.upset import UpSetPlot

__version__ = "0.1.0"
__all__ = ["UpSetPlot", "UpSetAnnotation"]
