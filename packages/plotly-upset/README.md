# plotly-upset

UpSet plot visualizations with Plotly — interactive set intersection plots with annotation tracks.

## Installation

```bash
pip install plotly-upset
```

## Quick Start

```python
import pandas as pd
from plotly_upset import UpSetPlot

df = pd.DataFrame({
    "Set A": [1, 1, 0, 0, 1],
    "Set B": [1, 0, 1, 0, 1],
    "Set C": [0, 1, 1, 1, 0],
})

plot = UpSetPlot(df, title="Set Intersections")
fig = plot.to_plotly()
fig.show()
```

## Features

- Class-based API with `.to_plotly()` returning a native Plotly Figure
- Annotation tracks: box, violin, bar, scatter, categorical, stacked bar
- Sorting by cardinality, degree, or input order
- Filtering by intersection size and degree
- Title and subtitle support
- Pandas and Polars DataFrame input
- `from_sets()` convenience constructor
