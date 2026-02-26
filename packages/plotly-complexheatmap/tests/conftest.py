"""Shared fixtures for plotly-complexheatmap tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def small_matrix() -> np.ndarray:
    """6 × 4 matrix with reproducible values."""
    rng = np.random.default_rng(42)
    return rng.standard_normal((6, 4))


@pytest.fixture()
def small_df(small_matrix: np.ndarray) -> pd.DataFrame:
    """DataFrame wrapper around :func:`small_matrix`."""
    return pd.DataFrame(
        small_matrix,
        index=[f"gene_{i}" for i in range(6)],
        columns=[f"sample_{j}" for j in range(4)],
    )


@pytest.fixture()
def row_groups() -> list[str]:
    """Row group labels matching a 6-row matrix."""
    return ["A", "A", "B", "B", "C", "C"]


@pytest.fixture()
def col_groups() -> list[str]:
    """Column group labels matching a 4-col matrix."""
    return ["X", "X", "Y", "Y"]
