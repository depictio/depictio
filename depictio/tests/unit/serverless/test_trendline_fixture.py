"""The browser trendline refit's parity fixture is current.

``packages/depictio-static-core/fixtures/trendline-expected.json`` holds what
px (+ statsmodels + pandas) draws for each trendline kind the binder ships, and
``test/trendline.test.ts`` holds the TypeScript refit to it. Regenerating it
here catches the other half: a plotly/statsmodels/pandas bump that changes a
fit (or a binder change that changes a binding) must update the fixture, so the
TS side is re-checked against the new reference.
"""

import importlib.util
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


def test_trendline_fixture_is_current() -> None:
    gen = _generator()
    assert gen.OUT.read_text() == gen.render(), (
        "fixtures/trendline-expected.json is stale; regenerate it with "
        "`uv run --extra dev python packages/depictio-static-core/scripts/"
        "generate_trendline_fixture.py` and re-run the static-core vitest suite"
    )
