"""Rebuild a Nonpareil coverage curve from the summary row Nonpareil publishes.

**Why this exists.** ``NONPAREIL_SET`` collapses every ``.npo`` into one small table
(``nonpareil_all_samples.tsv``) of fitted numbers per library: ``kappa``, ``C``,
``LR``, ``modelR``, ``LRstar`` and ``diversity``. The per-effort redundancy samples
that the curve is drawn from stay inside the ``.npo`` files, which nf-core pipelines
do not publish, so a template that only has the summary has no curve to plot - yet
the curve is the whole point of running Nonpareil.

The curve is recoverable because Nonpareil's model is a two-parameter one. Nonpareil
fits the coverage of a metagenome against sequencing effort as the CDF of a gamma
distribution on the log of the effort::

    C(effort) = P(shape, ln(effort) / scale)

where ``P`` is the regularised lower incomplete gamma function. The summary hands us
two independent readings of that same distribution:

* ``diversity`` (Nd) is its mean, i.e. ``shape * scale``;
* ``LRstar`` is the effort at which the model reaches 95% coverage, i.e.
  ``ln(LRstar)`` is its 95th percentile.

Two equations, two unknowns. :func:`fit_model` solves them; :func:`coverage` then
evaluates the curve anywhere. The round-trip check is what makes this a
reconstruction rather than a plausible-looking invention: feeding each library's own
``LR`` back through the fitted model reproduces the published ``C`` to within 0.05
absolute on the nf-core/taxprofiler 2.0.1 megatest, always slightly above it, which
is the expected sign - ``C`` is the last coverage actually observed, while the curve
is the smooth model fitted through it. See
``depictio/tests/recipes/test_nonpareil_curves.py``.

No scipy: the incomplete gamma is implemented here (series plus continued fraction,
the standard split at ``x < shape + 1``) so the recipe depends on nothing beyond the
numpy/polars already pinned.
"""

from __future__ import annotations

import math

import polars as pl

UNKNOWN_PLATFORM = "unknown"

# Numerical settings for the incomplete-gamma evaluation. 300 iterations is far
# more than either branch needs for the shapes Nonpareil fits (roughly 20-200).
_MAX_ITER = 300
_EPS = 1e-12
_TINY = 1e-300


def regularised_gamma_p(shape: float, x: float) -> float:
    """Regularised lower incomplete gamma ``P(shape, x)``, i.e. a gamma CDF.

    Series expansion below ``shape + 1``, Lentz's continued fraction for the upper
    tail above it - the split every implementation uses, because each branch
    converges slowly exactly where the other is fast.
    """
    if shape <= 0.0:
        raise ValueError("regularised_gamma_p: shape must be positive")
    if x <= 0.0:
        return 0.0

    log_prefix = -x + shape * math.log(x) - math.lgamma(shape)
    if log_prefix < -700.0:
        # exp() would underflow; P is 0 below the mean and 1 above it.
        return 0.0 if x < shape else 1.0
    prefix = math.exp(log_prefix)

    if x < shape + 1.0:
        term = 1.0 / shape
        total = term
        n = shape
        for _ in range(_MAX_ITER):
            n += 1.0
            term *= x / n
            total += term
            if abs(term) < abs(total) * _EPS:
                break
        return min(1.0, total * prefix)

    # Upper tail Q(shape, x) by continued fraction, then P = 1 - Q.
    b = x + 1.0 - shape
    c = 1.0 / _TINY
    d = 1.0 / b
    h = d
    for i in range(1, _MAX_ITER + 1):
        an = -i * (i - shape)
        b += 2.0
        d = an * d + b
        if abs(d) < _TINY:
            d = _TINY
        c = b + an / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return max(0.0, 1.0 - prefix * h)


def gamma_quantile(shape: float, scale: float, p: float) -> float:
    """Inverse gamma CDF by bisection.

    Bisection rather than Newton on purpose: the derivative is cheap but the
    bracket is trivially safe, this runs a few dozen times per ingest, and a
    quantile that silently lands on the wrong root would be invisible in the
    rendered curve.
    """
    if not 0.0 < p < 1.0:
        raise ValueError("gamma_quantile: p must be strictly between 0 and 1")
    lo, hi = 0.0, max(shape * scale * 4.0, 1.0)
    while regularised_gamma_p(shape, hi / scale) < p:
        hi *= 2.0
        if hi > 1e12:
            break
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if regularised_gamma_p(shape, mid / scale) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-10 * max(1.0, hi):
            break
    return 0.5 * (lo + hi)


def fit_model(diversity: float, lr_star: float, star: float = 0.95) -> tuple[float, float]:
    """Recover ``(shape, scale)`` from Nonpareil's ``diversity`` and ``LRstar``.

    ``diversity`` pins the mean (``shape * scale``), so one unknown is left; it is
    found by bisecting on ``shape`` until the model's ``star`` quantile matches
    ``ln(LRstar)``. The quantile falls monotonically as ``shape`` grows (the mean is
    held fixed, so a larger shape only narrows the distribution), which is what makes
    the bracket safe.
    """
    if diversity <= 0.0 or lr_star <= 1.0:
        raise ValueError("fit_model: diversity must be positive and LRstar above 1")
    target = math.log(lr_star)
    if target <= diversity:
        # The published 95% effort sits at or below the mean: the fit is degenerate,
        # so fall back on a narrow distribution centred on the mean rather than
        # bisecting towards infinity.
        shape = 1e4
        return shape, diversity / shape

    def quantile_for(shape: float) -> float:
        return gamma_quantile(shape, diversity / shape, star)

    lo, hi = 1.0, 1.0
    while quantile_for(hi) > target and hi < 1e7:
        hi *= 2.0
    while quantile_for(lo) < target and lo > 1e-4:
        lo /= 2.0
    for _ in range(100):
        mid = math.sqrt(lo * hi)
        if quantile_for(mid) > target:
            lo = mid
        else:
            hi = mid
        if hi / lo < 1.0 + 1e-9:
            break
    shape = math.sqrt(lo * hi)
    return shape, diversity / shape


def coverage(shape: float, scale: float, effort: float) -> float:
    """Model coverage at a sequencing effort, in base pairs."""
    if effort <= 1.0:
        return 0.0
    return regularised_gamma_p(shape, math.log(effort) / scale)


def effort_grid(lr: float, lr_star: float, points: int) -> list[float]:
    """A log-spaced sequencing-effort axis spanning the observed and projected run.

    Starts three decades below the effort actually sequenced so the low-coverage
    shoulder is visible, and stops one decade past the projected 95% effort so the
    plateau is drawn rather than implied. ``points`` is the decimation budget the
    ``profile`` kind asks recipes to respect.
    """
    if points < 2:
        raise ValueError("effort_grid: need at least two points")
    low = math.log10(max(lr, 10.0)) - 3.0
    high = math.log10(max(lr_star, lr * 10.0, 100.0)) + 1.0
    step = (high - low) / (points - 1)
    return [10.0 ** (low + i * step) for i in range(points)]


def samplesheet_lookup(samples: pl.DataFrame | None) -> list[tuple[str, str]]:
    """``(sample id, platform)`` pairs from a samplesheet, longest id first.

    Nonpareil names its rows after the *library* (sample plus run accession), so the
    sample a row belongs to is recovered by longest-prefix match - the same idiom
    ``taxpasta/profiles.py`` uses on taxpasta's column names, and the reason the
    persistent sample filter can reach these collections at all.
    """
    if samples is None or samples.is_empty():
        return []
    id_col = next(
        (c for c in ("sample", "sampleID", "sample_id", "id") if c in samples.columns), None
    )
    if id_col is None:
        return []
    plat_col = next((c for c in ("instrument_platform", "platform") if c in samples.columns), None)
    pairs: dict[str, str] = {}
    for row in samples.iter_rows(named=True):
        sample = str(row.get(id_col) or "")
        if not sample:
            continue
        platform = str(row.get(plat_col) or UNKNOWN_PLATFORM) if plat_col else UNKNOWN_PLATFORM
        pairs.setdefault(sample, platform)
    return sorted(pairs.items(), key=lambda pair: len(pair[0]), reverse=True)


def attribute_library(library: str, lookup: list[tuple[str, str]]) -> tuple[str, str]:
    """Longest samplesheet id that prefixes the library id wins."""
    for sample, platform in lookup:
        if library.startswith(sample):
            return sample, platform
    return library, UNKNOWN_PLATFORM
