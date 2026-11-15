"""The browser's sampling table is generated from sampling.py, never hand-kept.

A hand copy in ``advancedViz.ts`` once listed 18 of the 54 kinds, so every
``none`` kind added since (``stacked_bar``, the benchmark kinds, ``msa``...)
was hash-sampled in the bundle while the server served it whole, and not even
flagged ``degraded``. The generated TS module and the ``log_spaced_rank_thin``
fixture are committed; this test fails when either differs from what the
generator would write against today's ``sampling.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
STATIC_CORE = REPO / "packages" / "depictio-static-core"
GENERATOR_PATH = STATIC_CORE / "scripts" / "generate_sampling_table.py"
REGEN = "uv run --extra dev python packages/depictio-static-core/scripts/generate_sampling_table.py"


def _generator():
    spec = importlib.util.spec_from_file_location("_sampling_table_gen", GENERATOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_ts_table_matches_sampling_py():
    gen = _generator()
    assert gen.TS_PATH.read_text() == gen.render_ts(), f"stale sampling table — run: {REGEN}"


def test_log_rank_fixture_matches_sampling_py():
    gen = _generator()
    assert gen.FIXTURE_PATH.read_text() == gen.render_fixture(), f"stale fixture — run: {REGEN}"


def test_hand_copy_is_gone():
    """advancedViz.ts imports the generated table instead of declaring one."""
    src = (STATIC_CORE / "src" / "advancedViz.ts").read_text()
    assert "from './generated/sampling'" in src
    assert "export const KIND_SAMPLING_POLICY" not in src
    assert "export const TAIL_ROLE" not in src
