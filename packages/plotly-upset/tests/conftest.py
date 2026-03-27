"""Shared test fixtures."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def binary_df() -> pd.DataFrame:
    """Small binary DataFrame with 4 sets and 10 rows."""
    np.random.seed(42)
    data = {
        "SetA": [1, 1, 1, 0, 0, 1, 0, 1, 0, 1],
        "SetB": [1, 0, 1, 1, 0, 0, 1, 1, 0, 0],
        "SetC": [0, 1, 1, 1, 1, 0, 0, 0, 1, 0],
        "SetD": [0, 0, 1, 0, 1, 1, 0, 0, 0, 1],
    }
    return pd.DataFrame(data)


@pytest.fixture
def annotated_df() -> pd.DataFrame:
    """Binary DataFrame with extra numeric and categorical columns."""
    np.random.seed(42)
    data = {
        "SetA": [1, 1, 1, 0, 0, 1, 0, 1, 0, 1],
        "SetB": [1, 0, 1, 1, 0, 0, 1, 1, 0, 0],
        "SetC": [0, 1, 1, 1, 1, 0, 0, 0, 1, 0],
        "SetD": [0, 0, 1, 0, 1, 1, 0, 0, 0, 1],
        "score": np.random.randn(10).tolist(),
        "quality": np.random.uniform(0, 100, 10).tolist(),
        "category": ["A", "B", "A", "C", "B", "A", "C", "B", "A", "C"],
    }
    return pd.DataFrame(data)
