"""The Nonpareil curve is reconstructed, not invented.

``depictio/recipes/lib/nonpareil.py`` rebuilds a coverage curve from two numbers
Nonpareil publishes (``diversity`` and ``LRstar``), because the per-effort samples
stay in the ``.npo`` files nf-core pipelines do not ship. A reconstruction that
merely *looked* plausible would be worse than no tile at all, so the evidence lives
here: the summary carries a third number, ``C``, that the fit never sees, and feeding
each library's own sequencing effort back through the fitted model has to land on it.

The rows below are the real nf-core/taxprofiler 2.0.1 megatest summary
(``nonpareil/nonpareil_all_samples.tsv``), copied in so the test runs without the
dataset on disk.
"""

from __future__ import annotations

import math

import polars as pl
import pytest

from depictio.recipes.lib.nonpareil import (
    attribute_library,
    coverage,
    effort_grid,
    fit_model,
    regularised_gamma_p,
    samplesheet_lookup,
)

# library, kappa, C, LR, modelR, LRstar, diversity
MEGATEST_ROWS: list[tuple[str, float, float, float, float, float, float]] = [
    (
        "MOCK_001_Illumina_Hiseq_3000_1",
        0.57019,
        0.598374012351435,
        102758434.24,
        0.997995950977435,
        2854883325.493,
        17.8036661724689,
    ),
    (
        "MOCK_002_Illumina_Hiseq_3000_1",
        0.62701,
        0.65265641493915,
        139340035.489,
        0.998655205801229,
        2348920315.80024,
        17.8173529254465,
    ),
    (
        "MOCK_003_Illumina_Hiseq_3000_1",
        0.74862,
        0.767467336196893,
        235058119.128,
        0.999525679381583,
        1789540673.31917,
        17.4039463281212,
    ),
    (
        "MOCK_003_Illumina_Hiseq_3000_2",
        0.59226,
        0.619511141535056,
        83067726.2399999,
        0.999446567292753,
        1583527704.69652,
        17.388950520839,
    ),
]


@pytest.mark.no_db
@pytest.mark.parametrize(
    "shape,x", [(0.5, 0.25), (1.0, 1.0), (5.0, 1.0), (60.0, 60.0), (200.0, 190.0)]
)
def test_regularised_gamma_p_is_a_cdf(shape: float, x: float) -> None:
    """Monotone, bounded, and matching the exponential case it reduces to."""
    value = regularised_gamma_p(shape, x)
    assert 0.0 <= value <= 1.0
    assert regularised_gamma_p(shape, x) <= regularised_gamma_p(shape, x * 1.5)
    if shape == 1.0:
        # P(1, x) is the exponential CDF, which is the one closed form available.
        assert value == pytest.approx(1.0 - math.exp(-x), abs=1e-10)


@pytest.mark.no_db
def test_fit_recovers_the_published_coverage() -> None:
    """The fit never sees ``C``; evaluating the model at ``LR`` has to reproduce it.

    The residual is expected to be small and positive: ``C`` is the last coverage
    actually observed, and the model is the smooth curve fitted through the
    observations, so it sits slightly above.
    """
    residuals = []
    for _, _, published_c, lr, _, lr_star, diversity in MEGATEST_ROWS:
        shape, scale = fit_model(diversity, lr_star)
        assert shape * scale == pytest.approx(diversity, rel=1e-6), "the mean must be Nd"
        predicted = coverage(shape, scale, lr)
        residuals.append(predicted - published_c)
    assert all(0.0 < r < 0.05 for r in residuals), residuals


@pytest.mark.no_db
def test_fit_puts_95_percent_coverage_at_lrstar() -> None:
    """The second constraint, checked on its own: the model reaches 0.95 at LRstar."""
    for *_, lr_star, diversity in MEGATEST_ROWS:
        shape, scale = fit_model(diversity, lr_star)
        assert coverage(shape, scale, lr_star) == pytest.approx(0.95, abs=1e-4)


@pytest.mark.no_db
def test_effort_grid_is_decimated_and_spans_the_projection() -> None:
    """The `profile` kind is never backend-sampled, so the recipe owns the budget."""
    grid = effort_grid(1e8, 2.8e9, 200)
    assert len(grid) == 200
    assert grid == sorted(grid)
    assert grid[0] < 1e8 < 2.8e9 < grid[-1]


@pytest.mark.no_db
def test_libraries_are_attributed_to_their_samplesheet_sample() -> None:
    """Nonpareil names rows after the library; the links are keyed on the sample."""
    sheet = pl.DataFrame(
        {
            "sample": ["MOCK_003_Illumina_Hiseq_3000", "MOCK_003_Illumina_Hiseq_3000"],
            "run_accession": [1, 2],
            "instrument_platform": ["ILLUMINA", "ILLUMINA"],
        }
    )
    lookup = samplesheet_lookup(sheet)
    assert attribute_library("MOCK_003_Illumina_Hiseq_3000_2", lookup) == (
        "MOCK_003_Illumina_Hiseq_3000",
        "ILLUMINA",
    )
    # A library from a sample the sheet does not carry keeps its own id rather
    # than being attributed to a prefix that happens to be shorter.
    assert attribute_library("OTHER_1", lookup) == ("OTHER_1", "unknown")


@pytest.mark.no_db
def test_curves_recipe_expands_the_summary() -> None:
    """End to end on the recipe itself, with the megatest summary as the source."""
    from depictio.recipes import load_recipe, validate_schema

    module = load_recipe("nonpareil/curves.py")
    summaries = pl.DataFrame(
        MEGATEST_ROWS,
        schema=["library", "kappa", "coverage", "lr", "model_r", "lr_star", "diversity"],
        orient="row",
    )
    result = module.transform({"summaries": summaries, "samples": None})
    validate_schema(result, module.EXPECTED_SCHEMA, "nonpareil/curves.py")
    assert result.height == len(MEGATEST_ROWS) * module.POINTS
    assert result["coverage"].min() >= 0.0
    assert result["coverage"].max() <= 1.0
    per_series = result.group_by("library").len()["len"].to_list()
    assert set(per_series) == {module.POINTS}
    assert module.POINTS <= 200, "the profile contract caps a series at 200 points"
