"""Shared MultiQC figure builder: cache-key contract + offline-prerender gating.

The offline prerender only works if the CLI and the API compute *byte-identical*
figure cache keys — the server resolves a CLI-uploaded figure purely by that key.
These tests pin the key format (a golden value + order/scope invariants), confirm
the API delegator returns the same key as the shared function, and cover the
prerender opt-in gate and its fresh-ingest-only skip logic. None of this needs
MultiQC or S3 installed.
"""

from types import SimpleNamespace

import pytest

from depictio.cli.cli.utils import multiqc_processor as mp
from depictio.cli.cli.utils.multiqc_figures import multiqc_figure_cache_key

_ENV = "DEPICTIO_MULTIQC_PRERENDER"


# --------------------------------------------------------------------------- #
# Cache-key contract
# --------------------------------------------------------------------------- #


def test_cache_key_is_order_independent():
    a = multiqc_figure_cache_key(
        ["s3://b/dc/h2.parquet", "s3://b/dc/h1.parquet"], "fastqc", "plot", None, "dark", dc_id="DC"
    )
    b = multiqc_figure_cache_key(
        ["s3://b/dc/h1.parquet", "s3://b/dc/h2.parquet"], "fastqc", "plot", None, "dark", dc_id="DC"
    )
    assert a == b


def test_cache_key_golden_value():
    """Pin the exact key format so already-cached figures keep resolving."""
    key = multiqc_figure_cache_key(
        ["s3://bucket/dc/hash/multiqc.parquet"],
        "fastqc",
        "per_base_sequence_quality",
        None,
        "light",
        dc_id="DC1",
    )
    assert key == "multiqc:figure:dc=DC1:2734826375549f6f"


def test_cache_key_varies_by_theme_dataset_filter_dc():
    base = dict(module="m", plot="p", dc_id="DC")
    locs = ["s3://b/x.parquet"]
    k = lambda **kw: multiqc_figure_cache_key(locs, **{**base, **kw})  # noqa: E731
    assert k(theme="light") != k(theme="dark")
    assert k(dataset_id=None) != k(dataset_id="Counts")
    assert k(filter_sig=None) != k(filter_sig="s1|s2")
    assert multiqc_figure_cache_key(locs, "m", "p", dc_id="A") != multiqc_figure_cache_key(
        locs, "m", "p", dc_id="B"
    )


def test_cache_key_none_dc_segment():
    key = multiqc_figure_cache_key(["s3://b/x.parquet"], "m", "p")
    assert key.startswith("multiqc:figure:dc=none:")


def test_api_delegator_matches_shared_key():
    """The API's ``_generate_figure_cache_key`` must equal the shared function."""
    pytest.importorskip("depictio.api.cache")
    try:
        from depictio.api.v1.services.multiqc.figures import _generate_figure_cache_key
    except Exception:  # pragma: no cover - API stack not importable in this env
        pytest.skip("API figures module not importable in this environment")

    args = (["s3://b/2.parquet", "s3://b/1.parquet"], "fastqc", "plot", "Counts", "dark")
    assert _generate_figure_cache_key(*args, dc_id="DC") == multiqc_figure_cache_key(
        *args, dc_id="DC"
    )


# --------------------------------------------------------------------------- #
# _iter_module_plots normalisation
# --------------------------------------------------------------------------- #


def test_iter_module_plots_handles_str_and_dict_entries():
    entries = ["simple_plot", {"gc_content": ["Percentages", "Counts"]}, {"nodata": []}]
    assert list(mp._iter_module_plots(entries)) == [
        ("simple_plot", []),
        ("gc_content", ["Percentages", "Counts"]),
        ("nodata", []),
    ]


def test_iter_module_plots_empty():
    assert list(mp._iter_module_plots(None)) == []
    assert list(mp._iter_module_plots([])) == []


# --------------------------------------------------------------------------- #
# Prerender opt-in gate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, False),
        ("", False),
        ("0", False),
        ("false", False),
        ("no", False),
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
    ],
)
def test_prerender_enabled_gate(monkeypatch, value, expected):
    monkeypatch.delenv(_ENV, raising=False)
    if value is not None:
        monkeypatch.setenv(_ENV, value)
    assert mp.multiqc_prerender_enabled() is expected


# --------------------------------------------------------------------------- #
# Fresh-ingest-only skip logic (no MultiQC / no S3 touched on skip)
# --------------------------------------------------------------------------- #


def _fake_dc():
    return SimpleNamespace(id="DC123")


def _fake_cfg():
    return SimpleNamespace(s3_storage=SimpleNamespace(bucket="depictio-bucket"))


def test_prerender_skips_when_no_local_inputs(monkeypatch):
    called = {"api": False}
    monkeypatch.setattr(
        mp, "api_get_multiqc_s3_locations", lambda *a, **k: called.__setitem__("api", True)
    )
    # Empty inputs → returns before any API/S3/MultiQC work.
    mp._prerender_multiqc_figures(_fake_dc(), _fake_cfg(), [], SimpleNamespace())
    assert called["api"] is False


def test_prerender_skips_on_append_set_mismatch(monkeypatch):
    """DC has reports beyond this run's local files → skip (Celery fallback)."""
    monkeypatch.setattr(
        mp,
        "api_get_multiqc_s3_locations",
        lambda dc_id, cfg: ["s3://b/a.parquet", "s3://b/b.parquet"],
    )
    # We only have one of the two reports locally → mismatch → early return,
    # never importing multiqc (which isn't installed in the test env).
    inputs = [("/local/a.parquet", "s3://b/a.parquet")]
    mp._prerender_multiqc_figures(_fake_dc(), _fake_cfg(), inputs, SimpleNamespace())
