"""Basic UpSet plot example — minimal binary DataFrame with defaults."""

import numpy as np
import pandas as pd

from plotly_upset import UpSetPlot

# Create synthetic binary data: 6 sets, 200 elements
np.random.seed(42)
n_elements = 200
sets = {
    "Gene Set A": np.random.choice([0, 1], n_elements, p=[0.6, 0.4]),
    "Gene Set B": np.random.choice([0, 1], n_elements, p=[0.5, 0.5]),
    "Gene Set C": np.random.choice([0, 1], n_elements, p=[0.7, 0.3]),
    "Gene Set D": np.random.choice([0, 1], n_elements, p=[0.65, 0.35]),
    "Gene Set E": np.random.choice([0, 1], n_elements, p=[0.75, 0.25]),
    "Gene Set F": np.random.choice([0, 1], n_elements, p=[0.8, 0.2]),
}
df = pd.DataFrame(sets)

# Create and display the UpSet plot with default settings
plot = UpSetPlot(df, title="Gene Set Overlaps")
fig = plot.to_plotly()
fig.show()
