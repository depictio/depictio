import numpy as np
import plotly.graph_objects as go
from plotly_resampler import FigureResampler, FigureWidgetResampler

x = np.arange(1_000_000)
noisy_sin = (3 + np.sin(x / 200) + np.random.randn(len(x)) / 10) * x / 1_000

# OPTION 2 - FigureResampler: dynamic aggregation via a Dash web-app
fig = FigureResampler(go.Figure())
fig.add_trace(go.Scattergl(name='noisy sine', showlegend=False), hf_x=x, hf_y=noisy_sin)

fig.show_dash(mode='inline')