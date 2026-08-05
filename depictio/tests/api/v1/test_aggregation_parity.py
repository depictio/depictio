"""The card's "which aggregations are valid" table exists three times — keep them agreeing.

The same knowledge is encoded in three places, each owned by a different layer:

* ``AGGREGATION_COMPATIBILITY`` (models) decides what Pydantic *accepts*,
* ``agg_functions[...]["card_methods"]`` (api) decides what precompute *stores*,
* ``aggFunctions.ts`` (viewer) decides what the builder *offers*.

They had already drifted: the builder offered ``unique`` on numeric columns while
the model only knew ``nunique``, so a card built in the UI rendered fine but threw
``Invalid aggregation 'unique'`` on YAML export. It also offered ``percentile`` on
integers, which the model rejected outright. Nothing failed until a user exported.

These tests fail loudly instead.
"""

import re
from pathlib import Path
from typing import get_args

import polars as pl
import pytest

from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
    _agg_value,
    _evenness,
    _spec_value,
)
from depictio.api.v1.utils import agg_functions
from depictio.models.components.constants import AGGREGATION_COMPATIBILITY
from depictio.models.components.types import AggregationFunction

AGG_FUNCTIONS_TS = (
    Path(__file__).resolve().parents[3] / "viewer" / "src" / "builder" / "aggFunctions.ts"
)

# Names that address the same underlying reduction. ``agg_functions`` predates the
# model layer and records numeric distinct-counts as ``unique``; the models and the
# compute path call it ``nunique``. Renaming the stored key would strand every
# already-ingested collection, so the alias is deliberate — but it is the *only*
# one, and this map is what stops a second alias creeping in unnoticed.
KNOWN_ALIASES = {"unique": "nunique", "mean": "average", "std": "std_dev", "var": "variance"}

# The builder normalizes raw polars type names before lookup; `utf8` is its alias
# for the model's `object`. The backend never emits it (strings surface as
# `object`), so it has no entry of its own in AGGREGATION_COMPATIBILITY.
TS_TYPE_ALIASES = {"utf8": "object"}


def _canonical(name: str) -> str:
    return KNOWN_ALIASES.get(name, name)


def _parse_ts_card_methods() -> dict[str, set[str]]:
    """Extract ``{column_type: {aggregation, ...}}`` from ``aggFunctions.ts``.

    A crude parse of a file we control the shape of. It is deliberately strict:
    if the file stops being a plain literal map the regexes stop matching and the
    tests below fail rather than silently vacuously pass.
    """
    source = AGG_FUNCTIONS_TS.read_text()

    def _keys_in(block: str) -> set[str]:
        # Method keys are `name: { description...`; skip nested object keys by
        # only taking those directly followed by `{ description`.
        return set(re.findall(r"(\w+):\s*\{\s*description", block))

    # Shared consts (e.g. NUMERIC_CARD) are referenced by name inside the map.
    shared: dict[str, set[str]] = {}
    for name, body in re.findall(
        r"const (\w+): Record<string, AggMethodMeta> = \{(.*?)\n\};", source, re.S
    ):
        shared[name] = _keys_in(body)

    out: dict[str, set[str]] = {}
    map_match = re.search(
        r"const AGG_BY_TYPE: Record<string, ColumnTypeMeta> = \{(.*)\n\};", source, re.S
    )
    assert map_match, f"could not locate AGG_BY_TYPE in {AGG_FUNCTIONS_TS}"
    body = map_match.group(1)

    # Each entry is `<type>: { title: ..., cardMethods: <ref or literal>, ... }`.
    for type_name, entry in re.findall(r"\n  (\w+):\s*\{(.*?)\n  \},", body, re.S):
        ref = re.search(r"cardMethods:\s*(\w+),", entry)
        if ref:
            out[type_name] = set(shared.get(ref.group(1), set()))
            continue
        literal = re.search(r"cardMethods:\s*\{(.*?)\n    \},", entry, re.S)
        if literal:
            out[type_name] = _keys_in(literal.group(1))
    return out


TS_CARD_METHODS = _parse_ts_card_methods()


def test_the_typescript_table_was_actually_parsed():
    """Guard the guard: a silently-empty parse would make everything below pass."""
    assert set(TS_CARD_METHODS) >= set(AGGREGATION_COMPATIBILITY), (
        f"parsed only {sorted(TS_CARD_METHODS)} from aggFunctions.ts"
    )
    assert all(TS_CARD_METHODS.values()), "some column types parsed with no methods"


@pytest.mark.parametrize("column_type", sorted(AGGREGATION_COMPATIBILITY))
def test_every_model_blessed_aggregation_is_computable(column_type):
    """Defect 3: an aggregation the model allows must never silently return None.

    ``skewness``/``kurtosis``/``percentile`` used to live only in the precompute
    table, so a card showed a value until the first filter was applied and then
    went blank. ``_agg_value`` is the last-resort path — if it can't answer, no
    filtered card can.
    """
    series = pl.Series("v", [1.0, 2.0, 2.0, 3.0, 4.0, 9.0])
    for agg in AGGREGATION_COMPATIBILITY[column_type]:
        if agg == "box_plot_stats":
            assert isinstance(_agg_value(series, agg), dict)
            continue
        assert _agg_value(series, agg) is not None, (
            f"{agg!r} is valid for {column_type!r} but _agg_value cannot compute it — "
            f"a card using it would blank out as soon as a filter is applied"
        )


@pytest.mark.parametrize("column_type", sorted(AGGREGATION_COMPATIBILITY))
def test_builder_never_offers_an_aggregation_the_model_rejects(column_type):
    """Defects 1 and 2: anything the dropdown offers must survive validation."""
    ts_types = {t for t, alias in TS_TYPE_ALIASES.items() if alias == column_type}
    ts_types.add(column_type)
    allowed = set(AGGREGATION_COMPATIBILITY[column_type])
    for ts_type in ts_types & set(TS_CARD_METHODS):
        offered = TS_CARD_METHODS[ts_type]
        extra = offered - allowed
        assert not extra, (
            f"aggFunctions.ts offers {sorted(extra)} for {ts_type!r}, which "
            f"CardLiteComponent rejects for column_type={column_type!r}. A card built "
            f"with it renders but fails YAML export."
        )


def test_model_aggregation_names_are_declared_in_the_literal():
    """Every compatible name must also be a member of ``AggregationFunction``."""
    declared = set(get_args(AggregationFunction))
    for column_type, aggs in AGGREGATION_COMPATIBILITY.items():
        undeclared = set(aggs) - declared
        assert not undeclared, f"{column_type}: {sorted(undeclared)} missing from the literal"


@pytest.mark.parametrize("column_type", sorted(AGGREGATION_COMPATIBILITY))
def test_precomputed_specs_can_serve_the_model_names(column_type):
    """The unfiltered fast path reads specs by name — aliases must resolve.

    ``agg_functions`` stores numeric distinct-counts under ``unique``; a card
    declares ``nunique``. ``_spec_value`` bridges the two, and without it the card
    would miss the fast path and force a Delta load on every render.
    """
    stored = set(agg_functions.get(column_type, {}).get("card_methods", {}))
    if not stored:
        pytest.skip(f"{column_type} has no precomputed card methods")
    canonical_stored = {_canonical(name) for name in stored}
    fake_specs = {name: 1 for name in stored}
    for agg in AGGREGATION_COMPATIBILITY[column_type]:
        if agg not in canonical_stored:
            # Not precomputed (e.g. q1/q3/box_plot_stats) — served by the
            # pushdown instead, which the test above already covers.
            continue
        assert _spec_value(fake_specs, agg) is not None, (
            f"{agg!r} is precomputed for {column_type!r} but _spec_value cannot find it"
        )


def test_no_undocumented_aliases_crept_in():
    """Any card method whose name the model doesn't know must be a known alias."""
    declared = set(get_args(AggregationFunction))
    for column_type, meta in agg_functions.items():
        for name in meta.get("card_methods", {}):
            assert name in declared or name in KNOWN_ALIASES, (
                f"agg_functions[{column_type!r}] stores specs under {name!r}, which is "
                f"neither an AggregationFunction nor a documented alias"
            )


class TestEvenness:
    """Pielou evenness backing the ``composition`` layout's caption."""

    def test_uniform_distribution_scores_one(self):
        assert _evenness([10, 10, 10, 10], 40) == pytest.approx(1.0)

    def test_one_dominant_value_scores_near_zero(self):
        assert _evenness([997, 1, 1, 1], 1000) < 0.1

    def test_more_skew_means_less_evenness(self):
        assert _evenness([50, 30, 20], 100) > _evenness([80, 15, 5], 100)

    @pytest.mark.parametrize("counts,total", [([50], 50), ([], 0), ([1, 1], 0)])
    def test_degenerate_inputs_return_none(self, counts, total):
        """Below two categories the measure says nothing — better than scoring 0,
        which the meter would render as "dominated"."""
        assert _evenness(counts, total) is None

    def test_result_stays_in_range(self):
        for counts in ([1, 2, 3, 4, 5], [1, 1, 1, 97], [500, 500], [1] * 50):
            value = _evenness(counts, sum(counts))
            assert value is not None and 0.0 <= value <= 1.0

    def test_zero_counts_do_not_break_the_log(self):
        """Polars can emit a zero-count group; log(0) would raise."""
        assert _evenness([10, 0, 10], 20) == pytest.approx(1.0)
