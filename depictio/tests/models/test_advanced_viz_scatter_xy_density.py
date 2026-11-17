"""The density view of `scatter_xy`: its scale is a closed choice, log by default."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from depictio.models.components.advanced_viz.configs import ScatterXyConfig


def test_density_scale_defaults_to_log_and_takes_linear():
    assert ScatterXyConfig().density_scale == "log"
    assert ScatterXyConfig(density_scale="linear").density_scale == "linear"


def test_density_scale_is_a_closed_choice():
    with pytest.raises(ValidationError):
        ScatterXyConfig(density_scale="sqrt")  # type: ignore[arg-type]
