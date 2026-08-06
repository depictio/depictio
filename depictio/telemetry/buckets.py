"""Coarse bucketing for count metrics.

Exact integers are not sent for any usage count. A deployment reporting
"47 users, 12 projects, 213 dashboards, 4 workflows" is close to uniquely
identifiable even with no name attached to it; the same deployment reported as
"11-50 users, 11-50 projects, 200+ dashboards, 2-5 workflows" answers the only
question the maintainers actually have — roughly how big is it — while sitting in
a bucket with many other installs.

The boundaries are deliberately uneven: the difference between 0, 1 and a handful
carries real signal (is this an evaluation, a single-user install, or a team?),
whereas the difference between 300 and 400 dashboards does not.
"""

from typing import Final

#: Upper bound (inclusive) → label. Anything above the last bound gets ``OVERFLOW_LABEL``.
_BOUNDS: Final[tuple[tuple[int, str], ...]] = (
    (0, "0"),
    (1, "1"),
    (5, "2-5"),
    (10, "6-10"),
    (50, "11-50"),
    (200, "51-200"),
)

OVERFLOW_LABEL: Final[str] = "200+"

#: Every label ``bucket()`` can return, in ascending order. Useful for ordering
#: chart axes at the collector end, and asserted against in the tests.
LABELS: Final[tuple[str, ...]] = tuple(label for _, label in _BOUNDS) + (OVERFLOW_LABEL,)


def bucket(value: int | None) -> str:
    """Map a count onto a coarse bucket label.

    ``None`` maps to ``"unknown"`` so a metric that could not be computed stays
    distinguishable from a genuine zero — conflating the two would quietly turn
    a broken query into a plausible-looking data point.

    Negative values are not expected and are treated as ``"unknown"`` rather than
    silently bucketed as zero.
    """
    if value is None or value < 0:
        return "unknown"
    for upper, label in _BOUNDS:
        if value <= upper:
            return label
    return OVERFLOW_LABEL


def bucket_seconds(seconds: float | None) -> str:
    """Map a duration onto a coarse bucket label.

    Used for CLI command durations, where the useful distinction is
    "instant / quick / slow / very slow", not the millisecond count.
    """
    if seconds is None or seconds < 0:
        return "unknown"
    if seconds < 1:
        return "<1s"
    if seconds < 10:
        return "1-10s"
    if seconds < 60:
        return "10-60s"
    if seconds < 600:
        return "1-10m"
    return "10m+"
