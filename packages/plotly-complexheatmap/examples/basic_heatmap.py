#!/usr/bin/env python
"""Basic clustered heatmap example."""

import numpy as np
import pandas as pd

from plotly_complexheatmap import ComplexHeatmap

# Simulate a small gene-expression matrix
rng = np.random.default_rng(42)
n_genes, n_samples = 30, 12
data = rng.standard_normal((n_genes, n_samples))

# Add structure: first 10 genes up-regulated in first 6 samples
data[:10, :6] += 2.0
data[10:20, 6:] += 1.5

df = pd.DataFrame(
    data,
    index=[f"gene_{i:02d}" for i in range(n_genes)],
    columns=[f"sample_{j:02d}" for j in range(n_samples)],
)

hm = ComplexHeatmap(
    df,
    cluster_rows=True,
    cluster_cols=True,
    colorscale="RdBu_r",
    normalize="row",
    name="z-score",
    width=800,
    height=600,
)

fig = hm.to_plotly()
fig.show()
