"""Which tiles the optional Python runtime makes live, and what it costs.

Shared by both producers. A component is a *Python candidate* when the
browser cannot reproduce its server compute in TypeScript but the server's own
Python can run in Pyodide over the bundled table:

* a code-mode figure that did not bind (the transpiler refused its code, or
  the binder its call): its code runs in the server's sandbox, re-run on every
  filter change;
* ``group_compare``: the server's ``group_compare_from_frame``, any pair;
* an ``embedding`` with ``compute_method`` pca / pcoa / tsne: the server's
  ``_embedding_result_from_frame``. UMAP cannot: umap-learn needs numba, which
  has no WebAssembly build — those keep their export-time coordinates.

``complex_heatmap`` is not a candidate yet (its task reads a second, metadata
collection per request and builds through plotly-complexheatmap + pandas); it
stays frozen. Mode ``auto`` embeds the runtime exactly when one candidate
survives the build; ``on`` / ``off`` force it.
"""

from __future__ import annotations

from typing import Any, Literal

from depictio.serverless.pyodide.assets import estimate_bytes, features_packages

PythonRuntimeMode = Literal["auto", "on", "off"]

#: Marker a producer sets on a candidate before bundling its table (all
#: columns) and strips before the document is embedded (defined in pruning so
#: the column rule can read it without importing this module).
from depictio.serverless.pruning import PYTHON_JOB_KEY  # noqa: E402,F401

#: Filtered rows above which a job is answered from the frozen payload instead.
#: Measured in headless Chromium (chromium-1243) on the 314.0.7 runtime, warm
#: (RFC §13.6): a code figure (with_columns + px.scatter) over 200k rows x 9
#: columns in 0.16 s; a 60-feature Wilcoxon over 50k rows in 0.75 s (20k: 0.28 s);
#: PCA over 5k x 200 in 0.54 s (20k: 2.4 s); t-SNE over 1k x 50 in 13 s (300: 3.8 s).
MAX_ROWS: dict[str, int] = {
    "code_figure": 200_000,
    "group_compare": 50_000,
    "embedding": 5_000,
    "embedding_tsne": 1_000,
}


def _kind(comp: dict[str, Any]) -> str:
    return str(comp.get("viz_kind") or (comp.get("config") or {}).get("viz_kind") or "")


def candidate(comp: dict[str, Any]) -> tuple[str, set[str]] | None:
    """``(job, features)`` when the Python runtime could serve this component.

    For a code figure this is a *possible* job: one that binds goes live in
    TypeScript and drops it after the build.
    """
    ctype = comp.get("component_type")
    if ctype == "figure" and comp.get("mode") == "code" and comp.get("code_content"):
        return "code_figure", {"code_figure"}
    if ctype != "advanced_viz" or not comp.get("dc_id"):
        return None
    kind = _kind(comp)
    config = comp.get("config") or {}
    if kind == "group_compare" and config.get("group_col"):
        return "group_compare", {"group_compare"}
    if kind == "embedding":
        method = str(config.get("compute_method") or "").lower()
        if method in ("pca", "pcoa"):
            return "embedding", {"embedding"}
        if method == "tsne":
            return "embedding", {"embedding", "embedding_tsne"}
    return None


def max_rows(job: str, features: set[str]) -> int:
    if job == "embedding" and "embedding_tsne" in features:
        return MAX_ROWS["embedding_tsne"]
    return MAX_ROWS[job]


def addon_packages(features: set[str]) -> list[str]:
    """``RuntimeAddon.packages`` for these features: packages then extras."""
    packages, extras = features_packages(features)
    return packages + extras


def size_note(features: set[str]) -> str:
    return f"+{estimate_bytes(features) / 1e6:.1f} MB"


def live_detail(job: str, features: set[str]) -> str:
    """The tier detail of a Python-live tile."""
    what = {
        "code_figure": "its code re-runs in the server's code sandbox (RestrictedPython) "
        "over the filtered rows",
        "group_compare": "any pair is recomputed with the server's group_compare_from_frame",
        "embedding": "the projection is recomputed with the server's _embedding_result_from_frame",
    }[job]
    return (
        f"live through the embedded Python runtime (Pyodide, {size_note(features)} for the "
        f"bundle's Python jobs): {what}; above {max_rows(job, features):,} filtered rows the "
        "export-time snapshot is shown instead"
    )


def unavailable_reason(features: set[str]) -> str | None:
    """Fetch and verify the add-on's files now; ``None`` when they are all there.

    Called by a build (never by a preflight) before it promises Python-live
    tiers: in ``auto`` mode a runtime that cannot be fetched (no network, no
    ``DEPICTIO_PYODIDE_DIR``) leaves those tiles frozen instead of failing the
    export.
    """
    from depictio.serverless.pyodide.assets import PyodideAssetError, load_assets

    try:
        load_assets(features)
    except (PyodideAssetError, OSError) as exc:
        # An I/O error is as much "not available here" as a failed download.
        return str(exc)
    return None


def ipc_blob(frame: Any) -> str:
    """A table as base64 Arrow IPC (zstd) for the Python runtime.

    Pyodide's polars wheel is built without the Parquet reader (``read_parquet``
    raises there); its IPC reader, zstd included, is present. The frame keeps
    the bundled Parquet's rows in order, so the runtime's row mask applies.
    """
    import base64
    import io

    buf = io.BytesIO()
    frame.write_ipc(buf, compression="zstd")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def user_frame(frame: Any, companions: dict[str, str] | None = None) -> Any:
    """``frame`` without the build-time companion columns (``__code__`` & co.)."""
    drop = set(companions or {})
    keep = [
        c
        for c in frame.columns
        if c not in drop and not c.startswith(("__code__", "__ts__", "__fe__"))
    ]
    return frame.select(keep)
