"""`ataqv/metrics.py`: the per-library median fragment length.

The histogram ataqv writes has one row per length, so the median must be
weighted by read count; a plain median over the rows is the middle of the axis.
"""

from __future__ import annotations

from depictio.catalog.ataqv.metrics import _median_fragment_length


def test_median_is_weighted_by_read_count() -> None:
    metrics = {
        "fragment_length_counts_fields": ["fragment_length", "read_count", "fraction_of_all_reads"],
        "fragment_length_counts": [[50, 8, 0.8], [500, 1, 0.1], [1000, 1, 0.1]],
    }
    assert _median_fragment_length(metrics) == 50.0


def test_no_histogram_gives_no_median() -> None:
    assert _median_fragment_length({}) is None
    assert _median_fragment_length({"fragment_length_counts": [[10, 0]]}) is None
