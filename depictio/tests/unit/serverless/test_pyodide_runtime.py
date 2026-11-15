"""The Python a bundle runs in Pyodide is the server's, and answers like it.

``depictio/serverless/pyodide/modules.py`` copies server modules (verbatim) and
server functions (extracted with what they reach) into the tree a bundle
writes into Pyodide's filesystem. This test writes that tree into a temp
directory and imports it in a fresh CPython process, isolated from the
installed ``depictio`` package, then checks each entry point of
``depictio_bundle.py`` against the server function it ships: same answer on
the same frame. The browser half (boot from file://, zero network) is the
offline Playwright spec ``python-runtime.spec.ts``.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("RestrictedPython")

from depictio.serverless.pyodide import assets, plan  # noqa: E402
from depictio.serverless.pyodide.modules import bundle_python_sources, extract  # noqa: E402


@pytest.fixture(scope="module")
def tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("pyodide-tree")
    for path, source in bundle_python_sources().items():
        out = root / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(source)
    return root


def _run(tree: Path, body: str) -> dict:
    """Run ``body`` against the shipped tree only; it prints one JSON line."""
    code = f"import sys\nsys.path.insert(0, {str(tree)!r})\n{body}"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "DEPICTIO_CONTEXT": "cli"},
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _ipc_literal(df: pl.DataFrame) -> str:
    buf = io.BytesIO()
    df.write_ipc(buf, compression="zstd")
    return repr(buf.getvalue())


def test_the_tree_is_the_shipped_one_not_the_installed_package(tree: Path) -> None:
    out = _run(tree, "import json, depictio; print(json.dumps({'f': depictio.__file__}))")
    assert out["f"].startswith(str(tree))


def test_code_figure_runs_in_the_server_sandbox(tree: Path) -> None:
    df = pl.DataFrame({"species": ["a", "b", "a", "c"], "v": [1.0, 2.0, 3.0, 4.0]})
    body = f"""
import json, depictio_bundle as b
b.load_table("dc", {_ipc_literal(df)})
ok = json.loads(b.code_figure(json.dumps({{"code": "fig = px.bar(df, x='species', y='v')"}}), "dc", bytes([1, 1, 0, 1])))
refused = []
for code in ("import os\\nfig = px.bar(df, x='species', y='v')", "x = open('/etc/passwd')\\nfig = px.bar(df, x='species', y='v')"):
    try:
        b.code_figure(json.dumps({{"code": code}}), "dc")
        refused.append(False)
    except b.BundleJobError:
        refused.append(True)
print(json.dumps({{"traces": len(ok["figure"]["data"]), "x": ok["figure"]["data"][0]["x"], "rows": ok["metadata"]["displayed_data_count"], "refused": refused}}))
"""
    out = _run(tree, body)
    assert out["rows"] == 3
    assert sorted(out["x"]) == ["a", "b", "c"]
    assert out["refused"] == [True, True]


def test_group_compare_matches_the_server_function(tree: Path) -> None:
    from depictio.api.v1.services.group_compare import group_compare_from_frame

    rng = np.random.default_rng(1)
    df = pl.DataFrame(
        {
            "id": [f"c{i}" for i in range(60)],
            "cl": ["k1"] * 30 + ["k2"] * 30,
            **{f"g{i}": rng.gamma(2.0, 2.0, 60) for i in range(8)},
        }
    )
    a = {"label": "k1", "column": "cl", "values": ["k1"]}
    b = {"label": "k2", "column": "cl", "values": ["k2"]}
    expected = group_compare_from_frame(df, index_col="id", group_a=a, group_b=b)
    payload = json.dumps({"index_col": "id", "group_a": a, "group_b": b})
    out = _run(
        tree,
        f"import depictio_bundle as b\nb.load_table('dc', {_ipc_literal(df)})\n"
        f"print(b.group_compare({payload!r}, 'dc'))",
    )
    assert out["rows"] == expected["rows"]
    assert out["significant_count"] == expected["significant_count"]


def test_pca_matches_the_server_function(tree: Path) -> None:
    from depictio.api.v1.celery_tasks import _embedding_result_from_frame

    rng = np.random.default_rng(2)
    df = pl.DataFrame(
        {
            "sample_id": [f"s{i}" for i in range(40)],
            **{f"f{i}": rng.normal(size=40) for i in range(12)},
        }
    )
    kwargs = {"feature_id_col": "sample_id", "method": "pca", "params": {"n_components": 2}}
    expected = _embedding_result_from_frame(df, extra_cols=[], **kwargs)
    out = _run(
        tree,
        f"import depictio_bundle as b\nb.load_table('dc', {_ipc_literal(df)})\n"
        f"print(b.embedding({json.dumps(kwargs)!r}, 'dc'))",
    )
    for key in ("dim_1", "dim_2"):
        assert np.allclose(np.abs(out[key]), np.abs(expected[key]), atol=1e-9)


def test_extract_refuses_a_dependency_the_bundle_does_not_ship() -> None:
    import types

    mod = types.ModuleType("fake")
    src = "from depictio.api.v1.db import client\n\ndef f():\n    return client\n"
    exec(src, mod.__dict__)
    import inspect

    orig = inspect.getsource
    inspect.getsource = lambda m: src if m is mod else orig(m)  # type: ignore[assignment]
    try:
        with pytest.raises(Exception, match="does not ship"):
            extract(mod, ("f",))
    finally:
        inspect.getsource = orig  # type: ignore[assignment]


def test_candidates_and_sizes() -> None:
    code = {"component_type": "figure", "mode": "code", "code_content": "fig = px.bar(df)"}
    assert plan.candidate(code) == ("code_figure", {"code_figure"})
    gc = {
        "component_type": "advanced_viz",
        "viz_kind": "group_compare",
        "dc_id": "x",
        "config": {"group_col": "c"},
    }
    assert plan.candidate(gc) == ("group_compare", {"group_compare"})
    umap = {
        "component_type": "advanced_viz",
        "viz_kind": "embedding",
        "dc_id": "x",
        "config": {"compute_method": "umap"},
    }
    assert plan.candidate(umap) is None
    pkgs, extras = assets.features_packages({"code_figure"})
    assert {"numpy", "polars", "pandas", "narwhals"} <= set(pkgs)
    assert extras == ["plotly", "restrictedpython"]
    # Sized from pin.json alone: core + numpy + polars is the floor.
    assert assets.estimate_bytes(set()) > 30_000_000
    assert assets.estimate_bytes({"group_compare"}) - assets.estimate_bytes(set()) > 15_000_000
