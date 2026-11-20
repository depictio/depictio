"""The browser trendline refit's parity fixture is current.

``packages/depictio-static-core/fixtures/trendline-expected.json`` holds what
px (+ statsmodels + pandas) draws for each trendline kind the binder ships, and
``test/trendline.test.ts`` holds the TypeScript refit to it. Regenerating it
here catches the other half: a plotly/statsmodels/pandas bump that changes a
fit (or a binder change that changes a binding) must update the fixture, so the
TS side is re-checked against the new reference.
"""

import importlib.util
import json
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STATIC_CORE = REPO_ROOT / "packages" / "depictio-static-core"
GENERATOR_PATH = STATIC_CORE / "scripts" / "generate_trendline_fixture.py"


def _generator():
    spec = importlib.util.spec_from_file_location("_trendline_fixture_gen", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _diff(a, b, path="$") -> str | None:
    """The first place two fixture trees differ, floats compared to 1e-9.

    The fit is BLAS- and platform-dependent in its last bits (CI's Python and
    numpy build differ from a laptop's), and the TS side is only held to 1e-9
    anyway; a byte-for-byte compare failed on that noise alone.
    """
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12):
                return None
        return f"{path}: {a!r} != {b!r}"
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return f"{path}: keys {sorted(a)} != {sorted(b)}"
        for k in a:
            d = _diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {a!r} != {b!r}"


def test_trendline_fixture_is_current() -> None:
    gen = _generator()
    stale = _diff(json.loads(gen.OUT.read_text()), json.loads(gen.render()))
    assert stale is None, (
        "fixtures/trendline-expected.json is stale; regenerate it with "
        "`uv run --extra dev python packages/depictio-static-core/scripts/"
        f"generate_trendline_fixture.py` and re-run the static-core vitest suite ({stale})"
    )
