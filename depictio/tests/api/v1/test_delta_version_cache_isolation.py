"""The historical-read cache must not be able to poison the live one.

This is the load-bearing test of Delta time travel. ``load_deltatable_lite``
salts its cache keys, and before this feature the salt was ``aggregation_version``
alone — which does not change when you ask for an *older Delta commit* of the
same aggregation. A frame read at version 0 would therefore be stored under the
key a live read looks up, and the next caller asking for current data would be
handed two-commits-old rows with no error anywhere.

Everything here runs against a real two-commit Delta table on ``tmp_path``. A
mock cannot tell you whether the rows came back from the right commit, and the
whole point is which rows come back.
"""

from __future__ import annotations

import polars as pl
import pytest
from bson import ObjectId

from depictio.api.v1 import deltatables_utils
from depictio.api.v1.deltatables_utils import (
    DeltaVersionUnavailable,
    _create_delta_scan,
    build_cache_salt,
    load_deltatable_lite,
)

WF_ID = ObjectId("6a69cdb81e672a4a1b849fc1")
DC_ID = ObjectId("6a69cdb81e672a4a1b849fc2")


@pytest.fixture
def versioned_table(tmp_path, monkeypatch) -> str:
    """A table with two commits: v0 holds 2 rows, v1 holds 4.

    Local ``file://`` paths need no credentials, and an empty mapping keeps
    object_store out of the way — the same arrangement
    ``test_preview_time_travel.py`` uses.
    """
    monkeypatch.setattr("depictio.api.v1.deltatables_utils.polars_s3_config", {})

    destination = str(tmp_path / "table")
    pl.DataFrame({"sample": ["a", "b"], "value": [1, 2]}).write_delta(destination)
    pl.DataFrame({"sample": ["a", "b", "c", "d"], "value": [1, 2, 3, 4]}).write_delta(
        destination, mode="overwrite"
    )
    return destination


@pytest.fixture
def wired(versioned_table, monkeypatch):
    """Point ``load_deltatable_lite`` at the fixture table with no Mongo/HTTP.

    Also clears both module-level caches, which are process-global and would
    otherwise leak between tests in the same worker.
    """
    monkeypatch.setattr(deltatables_utils, "_get_delta_location", lambda *a, **k: versioned_table)
    monkeypatch.setattr(deltatables_utils, "_get_aggregation_version", lambda *a, **k: "1")
    monkeypatch.setattr(deltatables_utils, "_get_dc_type_from_db", lambda *a, **k: "table")
    monkeypatch.setattr(deltatables_utils, "get_deltatable_size_from_db", lambda *a, **k: -1)

    deltatables_utils._DELTA_SCHEMA_CACHE.clear()
    deltatables_utils._dataframe_memory_cache.clear()
    deltatables_utils._cache_metadata.clear()
    deltatables_utils._DELTA_AVAILABILITY_CACHE.clear()

    # `depictio.api.cache` keeps its *own* in-process store as the fallback when
    # Redis is unreachable, which it always is under pytest. Leaving it warm
    # makes a later test hit that layer and return before ever reaching the
    # module-level dict these assertions read — the run passes in isolation and
    # fails in a suite.
    from depictio.api.cache import get_cache

    get_cache()._memory_cache.clear()

    return versioned_table


def _load(**kwargs) -> pl.DataFrame:
    return load_deltatable_lite(WF_ID, DC_ID, **kwargs)


class TestCacheSalt:
    """The salt itself, before any I/O is involved."""

    def test_a_live_read_is_salted_exactly_as_before(self):
        assert build_cache_salt("3", None) == "3"

    def test_no_aggregation_and_no_version_stays_unsalted(self):
        # Preserves the pre-feature fallback: an unsalted key.
        assert build_cache_salt(None, None) is None

    def test_a_historical_read_is_always_salted(self):
        # Even with no aggregation_version to build on. An unsalted historical
        # key is precisely the poisoning case, so `None` is not an option here.
        assert build_cache_salt(None, 7) == "@dv7"
        assert build_cache_salt("", 7) == "@dv7"

    def test_version_zero_salts(self):
        # 0 is a real Delta version; a falsy-check bug would drop it.
        assert build_cache_salt("12", 0) == "12@dv0"

    @pytest.mark.parametrize("aggregation_version", ["1", "12", "1000", 7, None, ""])
    def test_no_live_salt_can_ever_contain_the_historical_marker(self, aggregation_version):
        """The disjointness argument, stated as a test.

        ``aggregation_version`` is an integer string, so ``@dv`` cannot occur in
        a live salt — which is what makes the two key spaces provably separate
        rather than merely unlikely to collide.
        """
        live = build_cache_salt(aggregation_version, None)
        assert live is None or "@dv" not in str(live)


class TestCacheIsolation:
    """The whole feature in four assertions."""

    def test_a_historical_read_returns_the_old_commit(self, wired):
        df = _load(delta_version=0)

        assert df.height == 2
        assert sorted(df["sample"].to_list()) == ["a", "b"]

    def test_a_live_read_after_a_historical_one_still_returns_live_data(self, wired):
        """The regression. Order matters: historical first, so it can poison."""
        historical = _load(delta_version=0)
        live = _load()

        assert historical.height == 2
        assert live.height == 4, "a historical frame was served as current data"
        assert sorted(live["sample"].to_list()) == ["a", "b", "c", "d"]

    def test_a_historical_read_after_a_live_one_is_not_served_the_live_frame(self, wired):
        """And the same in the other direction."""
        live = _load()
        historical = _load(delta_version=0)

        assert live.height == 4
        assert historical.height == 2, "a live frame was served as historical data"

    def test_the_two_key_spaces_are_disjoint(self, wired):
        """Not just 'the rows were right this time' — the keys cannot alias.

        Asserted on the keys actually written to the process-local cache, so it
        fails if a future refactor derives a key anywhere other than
        ``_generate_cache_keys``.
        """
        _load()
        live_keys = set(deltatables_utils._dataframe_memory_cache)

        _load(delta_version=0)
        all_keys = set(deltatables_utils._dataframe_memory_cache)
        historical_keys = all_keys - live_keys

        assert live_keys, "the live read cached nothing — the test proves nothing"
        assert historical_keys, "the historical read reused a live key"
        assert not (live_keys & historical_keys)
        assert all("@dv0" in key for key in historical_keys)
        assert not any("@dv" in key for key in live_keys)

    def test_the_schema_cache_is_keyed_on_the_compound_salt_too(self, wired):
        """`_DELTA_SCHEMA_CACHE` is a second, easily-missed key derivation site.

        It is consulted even when DataFrame caching is off, and its entries are
        column *sets* — so a shared entry between a historical and a live read
        would silently project the wrong columns after a schema change.
        """
        _load(select_columns=["sample"])
        _load(select_columns=["sample"], delta_version=0)

        salts = {salt for _dc, salt in deltatables_utils._DELTA_SCHEMA_CACHE}

        assert "1" in salts
        assert "1@dv0" in salts


class TestCachingDisabledPath:
    """`ENABLE_CACHING=False` skips the DataFrame cache but not the schema cache.

    It passed a literal ``None`` salt before this change, so every schema landed
    under ``(dc_id, "None")`` — never version-discriminated, and shared between
    historical and live reads.
    """

    def test_it_still_time_travels(self, wired, monkeypatch):
        monkeypatch.setattr(deltatables_utils, "ENABLE_CACHING", False)

        assert _load(delta_version=0).height == 2
        assert _load().height == 4

    def test_its_schema_entries_are_version_discriminated(self, wired, monkeypatch):
        monkeypatch.setattr(deltatables_utils, "ENABLE_CACHING", False)

        _load(select_columns=["sample"], delta_version=0)
        _load(select_columns=["sample"])

        salts = {salt for _dc, salt in deltatables_utils._DELTA_SCHEMA_CACHE}

        assert "None" not in salts, "the uncached path is still filing schemas under a null salt"
        assert {"1", "1@dv0"} <= salts


class TestUseLocalFiles:
    """The mirror is a fresh single-commit table, so it has no history at all.

    ``cache_delta_table_from_s3`` does ``scan_delta(current).collect()`` then
    ``write_delta(mode="overwrite")``. Asking that mirror for version 0 returns
    *current* data and does not error — the failure mode this feature exists to
    prevent, arriving through the back door.
    """

    def test_a_versioned_read_bypasses_the_mirror(self, versioned_table, monkeypatch):
        monkeypatch.setattr(deltatables_utils, "USE_LOCAL_FILES", True)
        monkeypatch.setattr("depictio.api.v1.deltatables_utils.polars_s3_config", {})

        calls = []
        monkeypatch.setattr(
            deltatables_utils,
            "cache_delta_table_from_s3",
            lambda path, config: calls.append(path) or path,
        )

        df = _create_delta_scan(versioned_table, "table", version=0).collect()

        assert calls == [], "a versioned read went through the local mirror"
        assert df.height == 2

    def test_an_unversioned_read_still_uses_the_mirror(self, versioned_table, monkeypatch):
        monkeypatch.setattr(deltatables_utils, "USE_LOCAL_FILES", True)
        monkeypatch.setattr("depictio.api.v1.deltatables_utils.polars_s3_config", {})

        calls = []
        monkeypatch.setattr(
            deltatables_utils,
            "cache_delta_table_from_s3",
            lambda path, config: calls.append(path) or path,
        )

        _create_delta_scan(versioned_table, "table").collect()

        assert calls == [versioned_table]


class TestMultiQCRefusesToTimeTravel:
    """Parquet has no commit log. Ignoring the version would return the current
    sample set while the caller believes it is historical."""

    def test_a_versioned_multiqc_scan_raises(self, tmp_path):
        with pytest.raises(DeltaVersionUnavailable) as excinfo:
            _create_delta_scan(str(tmp_path / "x.parquet"), "multiqc", version=0, dc_id="dc1")

        assert excinfo.value.reason == "not_versioned"
        assert excinfo.value.dc_id == "dc1"

    def test_case_is_not_load_bearing(self, tmp_path):
        # `dc_type` reaches here from several sources with inconsistent casing.
        with pytest.raises(DeltaVersionUnavailable):
            _create_delta_scan(str(tmp_path / "x.parquet"), "MultiQC", version=1)

    def test_an_unversioned_multiqc_scan_is_untouched(self, tmp_path, monkeypatch):
        monkeypatch.setattr("depictio.api.v1.deltatables_utils.polars_s3_config", {})
        pl.DataFrame({"sample": ["a"]}).write_parquet(tmp_path / "x.parquet")

        scan = _create_delta_scan(str(tmp_path / "x.parquet"), "multiqc")

        assert scan.collect().height == 1


class TestUnavailableVersions:
    def test_a_version_above_the_head_raises(self, versioned_table, monkeypatch):
        monkeypatch.setattr("depictio.api.v1.deltatables_utils.polars_s3_config", {})

        with pytest.raises(DeltaVersionUnavailable) as excinfo:
            _create_delta_scan(versioned_table, "table", version=99, dc_id="dc1").collect()

        assert excinfo.value.requested_version == 99

    def test_availability_is_probed_once_per_window(self, versioned_table, monkeypatch):
        """`bulk_compute_cards` renders every card in one request, so an
        un-memoized probe would read the Delta log once per card."""
        monkeypatch.setattr("depictio.api.v1.deltatables_utils.polars_s3_config", {})
        deltatables_utils._DELTA_AVAILABILITY_CACHE.clear()

        reads = []

        class _CountingTable:
            def __init__(self, location, storage_options=None):
                reads.append(location)

            def version(self):
                return 1

        monkeypatch.setattr("deltalake.DeltaTable", _CountingTable)

        for _ in range(5):
            assert deltatables_utils.check_delta_version_available(versioned_table, 0) is None

        assert len(reads) == 1

    def test_out_of_range_is_reported_without_attempting_a_read(self, versioned_table, monkeypatch):
        monkeypatch.setattr("depictio.api.v1.deltatables_utils.polars_s3_config", {})
        deltatables_utils._DELTA_AVAILABILITY_CACHE.clear()

        assert deltatables_utils.check_delta_version_available(versioned_table, 99) == (
            "out_of_range"
        )
        assert deltatables_utils.check_delta_version_available(versioned_table, 1) is None
