"""Entry points the static runtime calls inside Pyodide (serverless RFC §13.6).

Shipped into the bundle by ``modules.py`` beside the server code it runs. The
runtime hands each call the component's bundled table (Parquet bytes, once per
collection), the row mask of the current filter state (computed by the same
in-browser engine every live tile uses, links resolved) and the request the
renderer built; each function runs the server's own code over the masked frame
and returns JSON in the shape the corresponding endpoint returns.

Runs in CPython too: ``depictio/tests/unit/serverless/test_pyodide_runtime.py``
imports this tree from a temp directory, isolated from the installed package,
and compares every entry point with the server functions it ships.
"""

from __future__ import annotations

import io
import json
import math
import time
from typing import Any

import numpy as np
import polars as pl

_TABLES: dict[str, pl.DataFrame] = {}


def _bytes(value: Any) -> bytes:
    """A JS Uint8Array (JsProxy) or Python buffer, as bytes."""
    if hasattr(value, "to_py"):
        value = value.to_py()
    return bytes(value)


def load_table(dc_id: str, ipc: Any) -> int:
    """Read one bundled table once (Arrow IPC: Pyodide's polars has no Parquet reader)."""
    if dc_id not in _TABLES:
        _TABLES[dc_id] = pl.read_ipc(io.BytesIO(_bytes(ipc)))
    return _TABLES[dc_id].height


def has_table(dc_id: str) -> bool:
    return dc_id in _TABLES


def _frame(dc_id: str, mask: Any) -> pl.DataFrame:
    df = _TABLES[dc_id]
    if mask is None:
        return df
    flags = np.frombuffer(_bytes(mask), dtype=np.uint8).astype(bool)
    return df.filter(pl.Series(flags))


def _json_safe(value: Any) -> Any:
    """NaN / inf to null, numpy to Python — what ``inject.json_safe`` does."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "dtype") and hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _dumps(value: Any) -> str:
    return json.dumps(_json_safe(value), default=str)


class BundleJobError(Exception):
    """A job the server would also have refused, with its message."""


def code_figure(spec_json: str, dc_id: str, mask: Any = None) -> str:
    """A code-mode figure, the way ``build_figure_preview`` builds one.

    The author's code runs in the server's sandbox (``SimpleCodeExecutor``:
    RestrictedPython, the attribute guards, the audit hook) over the masked
    frame, with the names the server binds (``code_group_globals``: the
    dashboard's category colours, no groups); then the server's post-pass:
    ``uirevision``, ``recolor_code_figure``, ``tidy_facet_layout``. The theme
    template is applied in the browser, as for every bundled figure.
    """
    from depictio_bundle_ext.figure_builder import code_sets_template, recolor_code_figure
    from depictio_bundle_ext.groups import code_group_globals, tidy_facet_layout

    from depictio.api.v1.services.figure.code_executor import SimpleCodeExecutor

    started = time.monotonic()
    spec = json.loads(spec_json)
    code = str(spec.get("code") or "")
    colors = spec.get("category_colors") or None
    df = _frame(dc_id, mask)
    ok, fig, message = SimpleCodeExecutor().execute_code(
        code, df, code_group_globals(None, None, colors)
    )
    if not ok:
        raise BundleJobError(message)
    fig.update_layout(uirevision="persistent")
    recolor_code_figure(fig, colors, code, grouped=False)
    try:
        tidy_facet_layout(fig)
    except Exception:  # the server never loses a figure to its tidying either
        pass
    figure = json.loads(fig.to_json())
    return _dumps(
        {
            "figure": figure,
            "metadata": {
                "filter_applied": mask is not None,
                "was_sampled": False,
                "displayed_data_count": df.height,
                "total_data_count": df.height,
                "full_data_loaded": True,
                "code_sets_template": code_sets_template(code),
                "python_ms": int((time.monotonic() - started) * 1000),
            },
        }
    )


def _given(payload: dict[str, Any], key: str, default: Any) -> Any:
    """``celery_tasks._given``: an explicit 0 stays 0, only a missing key defaults."""
    value = payload.get(key)
    return default if value is None else value


def group_compare(payload_json: str, dc_id: str, mask: Any = None) -> str:
    """``compute_group_compare`` after its load: the server's ``group_compare_from_frame``."""
    from depictio.api.v1.services.group_compare import group_compare_from_frame

    payload = json.loads(payload_json)
    started = time.monotonic()
    result = group_compare_from_frame(
        _frame(dc_id, mask),
        index_col=str(payload.get("index_col") or "index"),
        group_a=payload.get("group_a") or {},
        group_b=payload.get("group_b") or {},
        test=str(payload.get("test") or "wilcoxon"),
        log_transform=bool(payload.get("log_transform", True)),
        max_features=int(_given(payload, "max_features", 2000)),
        min_observations=int(_given(payload, "min_observations", 3)),
        fdr_threshold=float(_given(payload, "fdr_threshold", 0.05)),
        log2fc_threshold=float(_given(payload, "log2fc_threshold", 1.0)),
        top_n_labels=int(_given(payload, "top_n_labels", 20)),
    )
    return _dumps({**result, "load_ms": 0, "python_ms": int((time.monotonic() - started) * 1000)})


def embedding(payload_json: str, dc_id: str, mask: Any = None) -> str:
    """``compute_embedding`` after its load: the server's ``_embedding_result_from_frame``."""
    from depictio_bundle_ext.celery_tasks import _embedding_result_from_frame

    payload = json.loads(payload_json)
    method = str(payload.get("method") or "pca").lower()
    if method not in {"pca", "tsne", "pcoa"}:
        raise BundleJobError(f"{method} cannot run in the browser")
    result = _embedding_result_from_frame(
        _frame(dc_id, mask),
        feature_id_col=str(payload.get("feature_id_col") or "sample_id"),
        method=method,
        params=payload.get("params") or {},
        extra_cols=list(payload.get("extra_cols") or []),
    )
    return _dumps({**result, "load_ms": 0})
