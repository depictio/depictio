"""The predicate emitter must agree with ``add_filter`` on every branch.

Each case builds the server's ``pl.Expr`` through ``add_filter`` and the
notebook's expression by ``eval``-ing the emitted source in the namespace the
generated imports cell provides; the two must select the same rows.
"""

from __future__ import annotations

import datetime

import polars as pl
import pytest

from depictio.api.v1.deltatables_utils import LINK_NO_MATCH, add_filter
from depictio.api.v1.services.notebook_export.predicates import (
    PredicateSource,
    emit_filter_expr,
    emit_predicate,
)
from depictio.models.components.filter_expr import build_filter_expr

FRAME = pl.DataFrame(
    {
        "s": ["a", "b", "c", None],
        "i": [1, 2, 3, None],
        "f": [1.5, 2.5, 3.5, None],
        "b": [True, False, True, None],
        "d": [
            datetime.date(2024, 1, 1),
            datetime.date(2024, 6, 1),
            datetime.date(2025, 1, 1),
            None,
        ],
        "dt": [
            datetime.datetime(2024, 1, 1, 12, 30, 45),
            datetime.datetime(2024, 6, 1, 0, 0, 0),
            datetime.datetime(2025, 1, 1, 8, 0, 0),
            None,
        ],
        "t": [datetime.time(1, 0), datetime.time(2, 0), datetime.time(3, 0), None],
        "txt": ["2024-01-01", "2024-06-01T00:00:00Z", "2025-01-01 08:00:00", None],
    }
)

NAMESPACE = {"pl": pl, "datetime": datetime, "col": pl.col, "lit": pl.lit}


def _eval(src: PredicateSource) -> pl.Expr:
    scope = dict(NAMESPACE)
    if src.prelude:
        exec("\n".join(src.prelude), scope)  # noqa: S102 - test evaluates generated source
    expr = eval(src.expr, scope)  # noqa: S307
    assert isinstance(expr, pl.Expr)
    return expr


def _server(itype: str, column: str, value, dtype) -> pl.Expr | None:
    out: list = []
    add_filter(out, itype, column, value, dtype=dtype)
    assert len(out) <= 1
    return out[0] if out else None


CASES = [
    # categorical, every dtype branch
    ("MultiSelect", "s", ["a", "c"], None),
    ("MultiSelect", "s", ["a", "c"], pl.String),
    ("Select", "s", "b", pl.String),
    ("SegmentedControl", "i", ["1", "3"], pl.Int64),
    ("MultiSelect", "i", [2], pl.Int64),
    ("MultiSelect", "f", ["1.5"], pl.Float64),
    ("MultiSelect", "d", ["2024-06-01"], pl.Date),
    ("MultiSelect", "dt", ["2024-01-01 12:30:45", "2025-01-01T08:00:00"], pl.Datetime("us")),
    ("MultiSelect", "t", ["01:00:00"], pl.Time),
    ("MultiSelect", "b", ["true"], pl.Boolean),  # unconvertible dtype → string-cast fallback
    ("MultiSelect", "i", ["abc"], pl.Int64),  # nothing converts → fallback
    ("MultiSelect", "i", ["1", "abc"], pl.Int64),  # partial conversion keeps the convertible
    # the other controls
    ("TextInput", "s", "a|c", None),
    ("Slider", "i", 2, None),
    ("RangeSlider", "f", [2.0, 3.5], None),
    ("RangeSlider", "i", [0, 2], pl.Int64),
    ("DateRangePicker", "d", ["2024-01-01", "2024-06-01"], pl.Date),
    ("DateRangePicker", "txt", ["2024-01-01", "2024-12-31"], pl.String),
    ("Timeline", "dt", ["2024-06-01T00:00:00Z", "2025-06-01T00:00:00.000"], pl.Datetime("us")),
    ("Timeline", "txt", ["2024-05-05T16:10:27Z", "2025-05-05T16:10:27Z"], pl.String),
    (LINK_NO_MATCH, "s", [], None),
]


@pytest.mark.parametrize("itype,column,value,dtype", CASES)
def test_emitted_source_matches_add_filter(itype, column, value, dtype):
    expected = _server(itype, column, value, dtype)
    emitted = emit_predicate(itype, column, value, dtype)
    assert expected is not None and emitted is not None
    got = FRAME.filter(_eval(emitted))
    want = FRAME.filter(expected)
    assert got.equals(want), f"{emitted.expr}\n got {got}\n want {want}"


# The options add_filter takes besides the value: a Slider's comparison, a
# TextInput's case and match mode. Each one changes which rows survive, so each
# one is checked against the server's own predicate.
OPTION_CASES = [
    ("Slider", "i", 2, None, {}),  # default: a ``>=`` threshold
    ("Slider", "i", 0, None, {}),  # 0 is a threshold, not "no filter"
    *[("Slider", "i", 2, None, {"slider_mode": m}) for m in ("gt", "lte", "lt", "eq", "ne")],
    ("TextInput", "s", "A", None, {}),  # case-insensitive by default
    ("TextInput", "s", "A", pl.String, {"case_sensitive": True}),
    ("TextInput", "s", "a.", None, {"match_mode": "contains"}),  # literal, not a regex
    ("TextInput", "i", "2", pl.Int64, {}),  # a non-string column is matched on its text
]


@pytest.mark.parametrize("itype,column,value,dtype,options", OPTION_CASES)
def test_filter_options_match_add_filter(itype, column, value, dtype, options):
    out: list = []
    add_filter(out, itype, column, value, dtype=dtype, **options)
    emitted = emit_predicate(itype, column, value, dtype, **options)
    assert len(out) == 1 and emitted is not None
    got = FRAME.filter(_eval(emitted))
    want = FRAME.filter(out[0])
    assert got.equals(want), f"{emitted.expr}\n got {got}\n want {want}"


@pytest.mark.parametrize(
    "itype,value",
    [
        ("MultiSelect", []),
        ("MultiSelect", None),
        ("TextInput", ""),
        ("Slider", None),
        ("RangeSlider", []),
        ("DateRangePicker", ["2024-01-01"]),  # not a pair → server skips it too
        ("Switch", True),  # no server branch at all
        ("Unknown", "x"),
    ],
)
def test_nothing_emitted_when_the_server_appends_nothing(itype, value):
    assert _server(itype, "s", value, None) is None
    assert emit_predicate(itype, "s", value, None) is None


def test_link_no_match_selects_no_rows():
    src = emit_predicate(LINK_NO_MATCH, "s", [], None)
    assert src is not None and src.expr == "pl.lit(False)"
    assert FRAME.filter(_eval(src)).height == 0


@pytest.mark.parametrize(
    "expr",
    [
        "col('i') > 1",
        "(col('i') >= 2) & (col('s') != 'c')",
        "col('s').is_in(['a', 'b'])",
        "col('f').is_between(2.0, 3.0)",
        "~col('s').is_null()",
    ],
)
def test_filter_expr_is_emitted_verbatim_and_evaluates_like_the_server(expr):
    src = emit_filter_expr(expr)
    got = FRAME.filter(eval(src, dict(NAMESPACE)))  # noqa: S307
    want = FRAME.filter(build_filter_expr(expr))
    assert got.equals(want)


def test_filter_expr_rejects_unsafe_source():
    with pytest.raises(ValueError):
        emit_filter_expr("__import__('os').system('x')")


def test_as_lines_produces_an_assignment():
    src = emit_predicate("MultiSelect", "s", ["a"], pl.String)
    assert src is not None
    assert src.as_lines("stage_1") == ["stage_1 = stage_1.filter(pl.col('s').is_in(['a']))"]


# ---------------------------------------------------------------------------
# What process_metadata_and_filter does around add_filter: the run column keeps
# rows with no run, a genome region compares chromosome names loosely.
# ---------------------------------------------------------------------------

RUNS = pl.DataFrame(
    {
        "depictio_run_id": ["run-a", "run-b", None],
        "chrom": ["1", "chr2", "MT"],
        "v": [1, 2, 3],
    }
)


def _server_entry(entry: dict, frame: pl.DataFrame) -> pl.DataFrame:
    from depictio.api.v1.deltatables_utils import process_metadata_and_filter

    exprs = process_metadata_and_filter([entry], dict(frame.schema))
    for expr in exprs:
        frame = frame.filter(expr)
    return frame


def _notebook_entry(entry: dict, frame: pl.DataFrame) -> pl.DataFrame:
    src = emit_predicate(
        entry["interactive_component_type"],
        entry["column_name"],
        entry["value"],
        frame.schema.get(entry["column_name"]),
        source=entry.get("source"),
    )
    return frame if src is None else frame.filter(_eval(src))


@pytest.mark.parametrize(
    "entry",
    [
        # One run selected: the run's rows and the run-less (aggregated) ones.
        {
            "interactive_component_type": "MultiSelect",
            "column_name": "depictio_run_id",
            "value": ["run-a"],
        },
        {
            "interactive_component_type": "Select",
            "column_name": "depictio_run_id",
            "value": "run-b",
        },
        # chr1 from an assembly, "1" in the table; M and MT are one.
        {
            "interactive_component_type": "MultiSelect",
            "column_name": "chrom",
            "value": ["chr1", "chrM"],
            "source": "genome_selection",
        },
        {
            "interactive_component_type": "Select",
            "column_name": "chrom",
            "value": "2",
            "source": "genome_selection",
        },
        # Without the region's source the names are compared as written.
        {"interactive_component_type": "MultiSelect", "column_name": "chrom", "value": ["chr1"]},
    ],
)
def test_the_run_column_and_region_names_match_the_server(entry):
    want = _server_entry(entry, RUNS)
    got = _notebook_entry(entry, RUNS)
    assert got.equals(want), f"\n got {got}\n want {want}"
    assert got.height > 0 or entry.get("source") is None


def test_the_chromosome_spellings_are_the_server_s():
    from depictio.api.v1.services.jbrowse.regions import canonical_chrom, chrom_name_variants
    from depictio.notebook import predicates as nb

    for value in (["1"], ["chr1"], ["chrM", "MT"], "X", ["Chr2", None]):
        assert nb.chrom_name_variants(value) == chrom_name_variants(value)
    for name in ("chr1", "CHRX", "M", " MT "):
        assert nb.canonical_chrom(name) == canonical_chrom(name)


def test_cards_read_the_frame_without_the_region_as_the_server_scopes_them():
    """``scope_region_filters`` keeps a region off cards and off figures that
    draw none of its columns; tables and a figure on the position keep it."""
    from depictio.api.v1.services.notebook_export.generator import (
        DCPlan,
        ExportPlan,
        StagePlan,
        generate_qmd,
    )
    from depictio.models.models.analysis_state import AnalysisState

    dc_id, dashboard = "6a" * 12, "6b" * 12
    region = [
        {
            "index": "region-chrom",
            "column_name": "chrom",
            "interactive_component_type": "MultiSelect",
            "value": ["chr1"],
            "source": "genome_selection",
            "metadata": {"dc_id": dc_id, "column_name": "chrom"},
        },
        {
            "index": "region-pos",
            "column_name": "pos",
            "interactive_component_type": "RangeSlider",
            "value": [1, 100],
            "source": "genome_selection",
            "metadata": {"dc_id": dc_id, "column_name": "pos"},
        },
    ]
    tab = {
        "dashboard_id": dashboard,
        "title": "Calls",
        "stored_metadata": [
            {
                "index": "card-1",
                "component_type": "card",
                "title": "Calls",
                "aggregation": "count",
                "column_name": "pos",
                "dc_id": dc_id,
            },
            {
                "index": "card-2",
                "component_type": "card",
                "title": "In view",
                "aggregation": "count",
                "column_name": "pos",
                "dc_id": dc_id,
                "follow_region_filter": True,
            },
            {"index": "tbl-1", "component_type": "table", "title": "Rows", "dc_id": dc_id},
        ],
    }
    state = AnalysisState.model_validate(
        {"filters": region, "context": {"dashboard_id": dashboard}}
    )
    stages = [
        StagePlan(
            index=f["index"],
            label=f["column_name"],
            column=f["column_name"],
            interactive_component_type=f["interactive_component_type"],
            value=f["value"],
            source_dc_id=dc_id,
            per_dc={dc_id: [{k: v for k, v in f.items() if k != "metadata"}]},
        )
        for f in region
    ]
    plan = ExportPlan(
        tabs=[tab],
        project=None,
        state=state,
        dcs=[DCPlan(dc_id=dc_id, tag="calls", dtypes={"chrom": pl.String, "pos": pl.Int64})],
        stages=stages,
        title="x",
    )
    src = generate_qmd(plan)
    assert "unregioned_calls = df_calls" in src and "region=False" in src
    assert "card_calls = unregioned_calls.select(" in src
    assert "card_in_view = final_calls.select(" in src
    assert "table_rows = final_calls" in src

    # And the frames agree with the server when the document runs.
    from depictio.notebook.funnel import funnel_rest, funnel_stage

    frame = pl.DataFrame({"chrom": ["1", "1", "2"], "pos": [5, 500, 5]})
    payload = state.model_dump(mode="json", exclude_none=True)
    full = funnel_rest(frame, payload, 0, dc_id=dc_id)
    assert full.height == 1  # "chr1" matched "1", then the window
    unregioned = funnel_stage(frame, payload, 1, dc_id=dc_id, region=False)
    unregioned = funnel_stage(unregioned, payload, 2, dc_id=dc_id, region=False)
    assert unregioned.height == 3
