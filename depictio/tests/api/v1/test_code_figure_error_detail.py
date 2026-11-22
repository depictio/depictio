"""Who may see a code figure's failure detail.

The executor's failure message carries the error text plus a traceback tail
(worker file paths included). An editor debugging their figure needs it; a
viewer or an anonymous visitor must get the generic message only. The
endpoints compute the caller's project role into ``code_error_detail``;
these tests pin the builder and the worker path that consume it.
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from depictio.api.v1.services.figure.figure_builder import (
    CODE_ERROR_GENERIC_MESSAGE,
    process_code_mode_figure,
)

# References a column the frame does not have, so the exec always fails.
FAILING_CODE = "fig = px.scatter(df.to_pandas(), x='missing', y='depth')"


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sample": ["s0", "s1", "s2"],
            "depth": [1.0, 2.0, 3.0],
        }
    )


def _annotation(fig: Any) -> str:
    if isinstance(fig, dict):  # worker output: the figure is a JSON dict
        return str(fig["layout"]["annotations"][0]["text"])
    return str(fig.layout.annotations[0].text)


# --- the builder ------------------------------------------------------------


def test_editor_error_figure_keeps_detail():
    ok, fig, _ = process_code_mode_figure(
        FAILING_CODE, _frame(), "light", "test", error_detail=True
    )
    assert not ok
    text = _annotation(fig)
    assert "Code execution error" in text
    assert "missing" in text  # the actual column error, not a mask


def test_viewer_error_figure_is_generic():
    ok, fig, _ = process_code_mode_figure(
        FAILING_CODE, _frame(), "light", "test", error_detail=False
    )
    assert not ok
    text = _annotation(fig)
    assert text == f"⚠️ {CODE_ERROR_GENERIC_MESSAGE}"
    # No traceback lines, no worker paths.
    assert "Traceback" not in text
    assert "missing" not in text
    assert ".py" not in text
    assert "/" not in text


def test_detail_defaults_to_kept():
    """Legacy callers that pass no flag keep the detailed message."""
    ok, fig, _ = process_code_mode_figure(FAILING_CODE, _frame(), "light", "test")
    assert not ok
    assert "Code execution error" in _annotation(fig)


# --- the worker -------------------------------------------------------------


@pytest.fixture
def worker(monkeypatch):
    from depictio.api.v1 import celery_tasks, deltatables_utils

    def fake_load(**kwargs: Any) -> pl.DataFrame:
        return _frame()

    monkeypatch.setattr(deltatables_utils, "load_deltatable_lite", fake_load)
    monkeypatch.setattr(deltatables_utils, "open_deltatable_scan", fake_load)

    # No Mongo here: the brand theme falls back to the env defaults at once.
    def _no_branding() -> None:
        raise RuntimeError("no mongo in this test")

    monkeypatch.setattr(
        "depictio.api.v1.services.branding.resolve_effective_brand_theme", _no_branding
    )
    return celery_tasks


def _payload(**extra) -> dict:
    payload = {
        "metadata": {
            "wf_id": "000000000000000000000000",
            "dc_id": "000000000000000000000000",
            "dc_config": {"delta_location": "s3://bucket/dc"},
            "visu_type": "scatter",
            "dict_kwargs": {},
            "mode": "code",
            "code_content": FAILING_CODE,
        },
        "filter_metadata": [],
        "theme": "light",
    }
    payload.update(extra)
    return payload


def test_worker_keeps_detail_for_editors(worker):
    result = worker.build_figure_preview.run(_payload(code_error_detail=True))
    error = result["metadata"]["error"]
    assert "missing" in error
    assert error != CODE_ERROR_GENERIC_MESSAGE
    assert "Code execution error" in _annotation(result["figure"])


def test_worker_sanitizes_error_for_viewers(worker):
    result = worker.build_figure_preview.run(_payload(code_error_detail=False))
    assert result["metadata"]["error"] == CODE_ERROR_GENERIC_MESSAGE
    assert _annotation(result["figure"]) == f"⚠️ {CODE_ERROR_GENERIC_MESSAGE}"
    serialized = str(result["figure"])
    assert "Traceback" not in serialized
    assert "missing" not in serialized


def test_worker_detail_defaults_to_kept(worker):
    """Payloads without the flag (legacy/internal builders) keep the detail."""
    result = worker.build_figure_preview.run(_payload())
    assert "missing" in result["metadata"]["error"]
