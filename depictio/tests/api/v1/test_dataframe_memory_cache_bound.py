"""The in-process DataFrame cache stays within its budget.

`load_deltatable_lite` caches every frame it reads, one per collection and
Delta version. That path never evicted, counted a re-read twice and left
filtered frames out of the total, so the API kept every frame a time-travel
read or a before/after diff ever touched.
"""

import polars as pl
import pytest

from depictio.api.v1 import deltatables_utils as du


@pytest.fixture
def small_cache(monkeypatch):
    monkeypatch.setattr(du, "MEMORY_THRESHOLD_BYTES", 1000)
    monkeypatch.setattr(du, "MEMORY_PER_ITEM_MAX_BYTES", 600)
    monkeypatch.setattr(du, "_dataframe_memory_cache", {})
    monkeypatch.setattr(du, "_cache_metadata", {})
    monkeypatch.setattr(du, "_total_memory_usage", 0)
    monkeypatch.setattr("depictio.api.cache.cache_dataframe", lambda *a, **k: False)
    return du


def frame() -> pl.DataFrame:
    return pl.DataFrame({"v": [1]})


def test_the_oldest_frames_make_room(small_cache):
    for i in range(5):
        small_cache._cache_dataframe_to_stores(f"k{i}", frame(), 400)
    assert small_cache._total_memory_usage <= 1000
    assert set(small_cache._dataframe_memory_cache) == {"k3", "k4"}
    assert small_cache._total_memory_usage == 800


def test_a_frame_cached_again_is_counted_once(small_cache):
    small_cache._cache_dataframe_to_stores("k", frame(), 400)
    small_cache._cache_dataframe_to_stores("k", frame(), 400)
    assert small_cache._total_memory_usage == 400


def test_a_frame_over_the_item_cap_is_not_kept_in_memory(small_cache):
    small_cache._cache_dataframe_to_stores("big", frame(), 700)
    assert "big" not in small_cache._dataframe_memory_cache
    assert small_cache._total_memory_usage == 0
