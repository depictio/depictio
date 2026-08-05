"""Pin the code-mode prologue transpiler (RFC §7, phase 6).

Four guards:

1. **Allowlist** — every recognised Polars form compiles to the *exact* pinned
   JSON the TypeScript interpreter reads. These assertions are literal JSON, not
   round-trips through the models, because the wire shape is the contract.
2. **Rejection** — everything outside the grammar returns ``None``. A wrong IR
   silently renders wrong data; ``None`` merely freezes the figure.
3. **Classification** — free / prologue / frozen.
4. **Differential** — for every case in the committed cross-language fixture:
   running the *original Polars code* through ``exec`` equals running the IR
   through the fixture generator's ``apply_ops`` equals the committed expected
   output, and ``transpile(code)`` reproduces the case's hand-written IR
   byte-for-byte. That closes the loop Python-side; the vitest suite closes it
   TypeScript-side against the same two JSON files.
"""

import importlib.util
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from pydantic import TypeAdapter

from depictio.models.models.serverless import PrologueOp
from depictio.serverless.prologue import classify, transpile

REPO_ROOT = Path(__file__).resolve().parents[4]
STATIC_CORE = REPO_ROOT / "packages" / "depictio-static-core"
FIXTURE_PATH = STATIC_CORE / "fixtures" / "prologue-fixture.json"
EXPECTED_PATH = STATIC_CORE / "fixtures" / "prologue-expected.json"
GENERATOR_PATH = STATIC_CORE / "scripts" / "generate_prologue_fixture.py"

_OPS = TypeAdapter(list[PrologueOp])


def _load_generator():
    """Import the fixture generator by path — it owns the reference semantics."""
    spec = importlib.util.spec_from_file_location("_prologue_fixture_gen", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _load_generator()
FIXTURE = json.loads(FIXTURE_PATH.read_text())
EXPECTED = json.loads(EXPECTED_PATH.read_text())


def ir(code: str) -> list[dict[str, Any]] | None:
    """``transpile`` down to plain JSON — what actually lands in the manifest."""
    ops = transpile(code)
    if ops is None:
        return None
    return _OPS.dump_python(ops, mode="json")


def figure(prep: str = "", frame: str = "df") -> str:
    """Wrap a prep chain in the constrained code-mode shape."""
    lines = [prep] if prep else []
    lines.append(f"fig = px.bar({frame}.to_pandas(), x='habitat', y='value')")
    return "\n".join(lines)


def _last_target(prep: str) -> str:
    """The variable the prep's final statement binds — what the fig line reads."""
    return prep.split("\n")[-1].split(" =")[0].strip()


# ---------------------------------------------------------------------------
# 1. allowlist: exact pinned JSON
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prep,expected",
    [
        # -- filter: comparisons ------------------------------------------
        (
            "df_modified = df.filter(pl.col('q_val') < 0.05)",
            [{"op": "filter", "pred": {"cmp": {"col": "q_val", "op": "<", "value": 0.05}}}],
        ),
        (
            "df_modified = df.filter(pl.col('n') >= 10)",
            [{"op": "filter", "pred": {"cmp": {"col": "n", "op": ">=", "value": 10}}}],
        ),
        (
            "df_modified = df.filter(pl.col('lfc') > -1.5)",
            [{"op": "filter", "pred": {"cmp": {"col": "lfc", "op": ">", "value": -1.5}}}],
        ),
        (
            "df_modified = df.filter(pl.col('habitat') != '')",
            [{"op": "filter", "pred": {"cmp": {"col": "habitat", "op": "!=", "value": ""}}}],
        ),
        (
            "df_modified = df.filter(pl.col('significant') == True)",
            [{"op": "filter", "pred": {"cmp": {"col": "significant", "op": "==", "value": True}}}],
        ),
        (
            # Mirrored literal-on-the-left form.
            "df_modified = df.filter(0.05 > pl.col('q_val'))",
            [{"op": "filter", "pred": {"cmp": {"col": "q_val", "op": "<", "value": 0.05}}}],
        ),
        # -- filter: null / membership ------------------------------------
        (
            "df_modified = df.filter(pl.col('value').is_not_null())",
            [{"op": "filter", "pred": {"is_not_null": {"col": "value"}}}],
        ),
        (
            "df_modified = df.filter(pl.col('value').is_null())",
            [{"op": "filter", "pred": {"is_null": {"col": "value"}}}],
        ),
        (
            "df_modified = df.filter(pl.col('batch').is_in([1, 3]))",
            [{"op": "filter", "pred": {"is_in": {"col": "batch", "values": [1, 3]}}}],
        ),
        (
            "df_modified = df.filter(~pl.col('value').is_null())",
            [{"op": "filter", "pred": {"not": {"is_null": {"col": "value"}}}}],
        ),
        # -- filter: boolean algebra, flattened ---------------------------
        (
            "df_modified = df.filter((pl.col('a') > 1) & (pl.col('b') < 2) & (pl.col('c') == 3))",
            [
                {
                    "op": "filter",
                    "pred": {
                        "and": [
                            {"cmp": {"col": "a", "op": ">", "value": 1}},
                            {"cmp": {"col": "b", "op": "<", "value": 2}},
                            {"cmp": {"col": "c", "op": "==", "value": 3}},
                        ]
                    },
                }
            ],
        ),
        (
            "df_modified = df.filter((pl.col('a') > 1) | (pl.col('b') < 2))",
            [
                {
                    "op": "filter",
                    "pred": {
                        "or": [
                            {"cmp": {"col": "a", "op": ">", "value": 1}},
                            {"cmp": {"col": "b", "op": "<", "value": 2}},
                        ]
                    },
                }
            ],
        ),
        (
            # Several positional predicates AND together (Polars semantics).
            "df_modified = df.filter(pl.col('a').is_not_null(), pl.col('b') > 0)",
            [
                {
                    "op": "filter",
                    "pred": {
                        "and": [
                            {"is_not_null": {"col": "a"}},
                            {"cmp": {"col": "b", "op": ">", "value": 0}},
                        ]
                    },
                }
            ],
        ),
        # -- group_by / agg ------------------------------------------------
        (
            "df_modified = df.group_by(['habitat']).agg(pl.col('value').mean().alias('value'))",
            [
                {
                    "op": "group_by",
                    "by": ["habitat"],
                    "agg": [{"col": "value", "fn": "mean", "alias": "value"}],
                }
            ],
        ),
        (
            # Bare aggregation: Polars names the output after the column.
            "df_modified = df.group_by('habitat').agg(pl.col('value').mean())",
            [
                {
                    "op": "group_by",
                    "by": ["habitat"],
                    "agg": [{"col": "value", "fn": "mean", "alias": "value"}],
                }
            ],
        ),
        (
            "df_modified = df.group_by('g', maintain_order=True).agg([pl.col('x').n_unique(), pl.col('y').count()])",
            [
                {
                    "op": "group_by",
                    "by": ["g"],
                    "agg": [
                        {"col": "x", "fn": "nunique", "alias": "x"},
                        {"col": "y", "fn": "count", "alias": "y"},
                    ],
                }
            ],
        ),
        # -- group_by: len (group size) -------------------------------------
        (
            # Bare `pl.len()`: no source column, Polars names it "len".
            "df_modified = df.group_by('g').agg(pl.len())",
            [
                {
                    "op": "group_by",
                    "by": ["g"],
                    "agg": [{"col": None, "fn": "len", "alias": "len"}],
                }
            ],
        ),
        (
            # Bare `pl.count()`: same group size, but Polars names it "count"
            # (deprecated since 0.20.5, still functional on the repo's 1.42.1).
            "df_modified = df.group_by('g').agg(pl.count())",
            [
                {
                    "op": "group_by",
                    "by": ["g"],
                    "agg": [{"col": None, "fn": "len", "alias": "count"}],
                }
            ],
        ),
        (
            # `pl.col(c).len()` is STILL the group size, but keeps `c` — Polars
            # names the output after it and raises when it is missing.
            "df_modified = df.group_by('g').agg(pl.col('x').len())",
            [
                {
                    "op": "group_by",
                    "by": ["g"],
                    "agg": [{"col": "x", "fn": "len", "alias": "x"}],
                }
            ],
        ),
        (
            # The seed shape: aliased group size next to a real non-null count.
            "df_modified = df.group_by('lineage').agg(pl.count().alias('count'),"
            " pl.col('x').count().alias('n_x'))",
            [
                {
                    "op": "group_by",
                    "by": ["lineage"],
                    "agg": [
                        {"col": None, "fn": "len", "alias": "count"},
                        {"col": "x", "fn": "count", "alias": "n_x"},
                    ],
                }
            ],
        ),
        (
            # pl.<fn>("col") shorthand.
            "df_modified = df.group_by(by=['a', 'b']).agg(pl.mean('z'), pl.std('z').alias('sd'))",
            [
                {
                    "op": "group_by",
                    "by": ["a", "b"],
                    "agg": [
                        {"col": "z", "fn": "mean", "alias": "z"},
                        {"col": "z", "fn": "std", "alias": "sd"},
                    ],
                }
            ],
        ),
        # -- sort -----------------------------------------------------------
        ("df_modified = df.sort('value')", [{"op": "sort", "by": ["value"], "desc": [False]}]),
        (
            "df_modified = df.sort('count', descending=True)",
            [{"op": "sort", "by": ["count"], "desc": [True]}],
        ),
        (
            "df_modified = df.sort(['a', 'b'], descending=[True, False])",
            [{"op": "sort", "by": ["a", "b"], "desc": [True, False]}],
        ),
        (
            # Scalar `descending` broadcasts across every key.
            "df_modified = df.sort(['a', 'b'], descending=True)",
            [{"op": "sort", "by": ["a", "b"], "desc": [True, True]}],
        ),
        # -- rename ---------------------------------------------------------
        (
            "df_modified = df.rename({'bill_length_mm': 'count'})",
            [{"op": "rename", "map": {"bill_length_mm": "count"}}],
        ),
        # -- unpivot / melt -------------------------------------------------
        (
            "df_modified = df.unpivot(on=['shannon', 'faith_pd'], index=['sample_id', 'habitat'],"
            " variable_name='metric', value_name='value')",
            [
                {
                    "op": "unpivot",
                    "on": ["shannon", "faith_pd"],
                    "index": ["sample_id", "habitat"],
                    "variable": "metric",
                    "value": "value",
                }
            ],
        ),
        (
            # Defaults: no index, Polars' default variable/value names.
            "df_modified = df.unpivot(on=['a', 'b'])",
            [
                {
                    "op": "unpivot",
                    "on": ["a", "b"],
                    "index": [],
                    "variable": "variable",
                    "value": "value",
                }
            ],
        ),
        (
            # Legacy melt spelling maps onto the same op.
            "df_modified = df.melt(id_vars=['id'], value_vars=['a', 'b'],"
            " variable_name='metric', value_name='value')",
            [
                {
                    "op": "unpivot",
                    "on": ["a", "b"],
                    "index": ["id"],
                    "variable": "metric",
                    "value": "value",
                }
            ],
        ),
        # -- identity conversions drop out ----------------------------------
        (
            "df_modified = df.lazy().filter(pl.col('a') > 0).collect()",
            [{"op": "filter", "pred": {"cmp": {"col": "a", "op": ">", "value": 0}}}],
        ),
        # -- chains and sequential reassignment -----------------------------
        (
            "df_modified = df.filter(pl.col('a') > 0).group_by('g').agg(pl.col('v').sum()).sort('v', descending=True)",
            [
                {"op": "filter", "pred": {"cmp": {"col": "a", "op": ">", "value": 0}}},
                {
                    "op": "group_by",
                    "by": ["g"],
                    "agg": [{"col": "v", "fn": "sum", "alias": "v"}],
                },
                {"op": "sort", "by": ["v"], "desc": [True]},
            ],
        ),
        (
            # Sequential reassignment onto `df` itself.
            "df = df.filter(pl.col('a') > 0)\ndf = df.sort('a')",
            [
                {"op": "filter", "pred": {"cmp": {"col": "a", "op": ">", "value": 0}}},
                {"op": "sort", "by": ["a"], "desc": [False]},
            ],
        ),
        (
            # Intermediate variables, in order.
            "df_a = df.filter(pl.col('a') > 0)\ndf_modified = df_a.rename({'a': 'b'})",
            [
                {"op": "filter", "pred": {"cmp": {"col": "a", "op": ">", "value": 0}}},
                {"op": "rename", "map": {"a": "b"}},
            ],
        ),
    ],
)
def test_allowlist_emits_pinned_json(prep, expected):
    assert ir(figure(prep, _last_target(prep))) == expected


def test_no_prep_is_an_empty_program():
    assert ir(figure()) == []
    assert ir(figure("df_pd = df.to_pandas()", "df_pd")) == []


# ---------------------------------------------------------------------------
# 2. rejection: anything outside the grammar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prep",
    [
        # computed columns
        "df_modified = df.with_columns(pl.col('lfc').abs().alias('abs_lfc'))",
        "df_modified = df.filter(pl.col('a') + pl.col('b') > 0)",
        "df_modified = df.filter(pl.col('a') > pl.col('b'))",
        # lambdas / callables
        "df_modified = df.filter(lambda r: r['a'] > 0)",
        "df_modified = df.group_by('g').agg(pl.col('v').map_elements(lambda v: v * 2))",
        # indexing
        "df_modified = df.to_pandas().groupby('habitat')['faith_pd'].agg(['mean', 'std'])",
        "df_modified = df[df['a'] > 0]",
        # pandas reshaping (different null/order semantics — see module docstring)
        "df_modified = df.to_pandas().groupby(['island', 'species']).agg({'m': 'mean'}).reset_index()",
        "df_modified = df.to_pandas().sort_values('a', ascending=False)",
        # unlisted methods
        "df_modified = df.head(10)",
        "df_modified = df.drop_nulls()",
        "df_modified = df.pivot(on='metric', index='sample', values='value')",
        "df_modified = df.join(other, on='id')",
        "df_modified = df.group_by('g').head(3)",
        "df_modified = df.unique(subset=['a'])",
        # `pl.len` takes no column argument — `pl.len('x')` is not a Polars API
        # (unlike `pl.count('x')`, which IS the non-null count of 'x').
        "df_modified = df.group_by('lineage').agg(pl.len('x'))",
        "df_modified = df.group_by('lineage').agg(pl.len(pl.col('x')))",
        # unknown / unsupported kwargs
        "df_modified = df.sort('a', nulls_last=True)",
        "df_modified = df.sort('a', reverse=True)",
        "df_modified = df.filter(habitat='Soil')",
        "df_modified = df.unpivot(on=['a'], index=['b'], streamable=True)",
        # unpivot without `on` needs the schema
        "df_modified = df.unpivot(index=['b'])",
        # Python boolean operators instead of & / |
        "df_modified = df.filter((pl.col('a') > 0) and (pl.col('b') > 0))",
        # non-literal operands
        "df_modified = df.filter(pl.col('a') > threshold)",
        "df_modified = df.filter(pl.col('a').is_in(values))",
        "df_modified = df.sort(sort_key)",
        "df_modified = df.rename(mapping)",
        # chained comparison
        "df_modified = df.filter(0 < pl.col('a') < 10)",
        # group_by without agg
        "df_modified = df.group_by('g')",
        # multi-column pl.col
        "df_modified = df.filter(pl.col('a', 'b').is_not_null())",
        # unknown root frame
        "df_modified = other.filter(pl.col('a') > 0)",
        # non-assignment statement in the prologue
        "print('hi')\ndf_modified = df.sort('a')",
        # tuple unpacking target
        "df_modified, extra = df.sort('a'), 1",
    ],
)
def test_rejects_outside_allowlist(prep):
    code = figure(prep, _last_target(prep))
    assert transpile(code) is None
    assert classify(code) == "frozen"


def test_partial_recognition_rejects_the_whole_program():
    """One unrecognised statement freezes the figure — no partial IR."""
    code = (
        "df_a = df.filter(pl.col('a') > 0)\n"
        "df_modified = df_a.with_columns(pl.col('b').abs().alias('c'))\n"
        "fig = px.bar(df_modified.to_pandas(), x='a', y='c')"
    )
    assert transpile(code) is None


def test_rejects_when_fig_ignores_the_final_frame():
    """Compiling ops the scaffold never saw would mis-render the figure."""
    code = (
        "df_a = df.filter(pl.col('a') > 0)\n"
        "df_modified = df_a.sort('a')\n"
        "fig = px.bar(df_a.to_pandas(), x='a', y='b')"
    )
    assert transpile(code) is None


@pytest.mark.parametrize(
    "code",
    [
        "",
        "   \n\n",
        "df_modified = df.sort('a')",  # no fig line at all
        "df_modified = df.filter(pl.col('a' > 0)",  # syntax error
    ],
)
def test_rejects_non_constrained_code(code):
    assert transpile(code) is None
    assert classify(code) == "frozen"


# ---------------------------------------------------------------------------
# 3. classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,verdict",
    [
        (figure(), "free"),
        (figure("df_pd = df.to_pandas()", "df_pd"), "free"),
        (figure("df_modified = df.sort('value')", "df_modified"), "prologue"),
        (figure("df_modified = df.head(3)", "df_modified"), "frozen"),
    ],
)
def test_classify(code, verdict):
    assert classify(code) == verdict


def test_seed_corpus_classification_is_stable():
    """The measured split over the committed seeds (see measure_prologue.py).

    A change here is a real capability change — intended or a regression — and
    should be looked at, not silently re-baselined.
    """
    from collections import Counter

    from depictio.serverless.scripts.measure_prologue import code_mode_figures

    counts = Counter(
        classify(component.get("code_content") or "") for _, component in code_mode_figures()
    )
    assert sum(counts.values()) == 18
    # `len` (group size) landed in the phase-6 IR: the four viralrecon
    # `pl.count().alias('count')` figures moved frozen -> prologue.
    assert counts == {"free": 4, "prologue": 11, "frozen": 3}


# ---------------------------------------------------------------------------
# 4. differential: code == apply_ops == committed expectation
# ---------------------------------------------------------------------------

#: The original Polars source each fixture case's IR was written for. Every
#: chain terminates in ``df_modified`` so the differential test can pick the
#: result out of the exec namespace.
CASE_CODE: dict[str, str] = {
    "filter_cmp_lt": "df_modified = df.filter(pl.col('q_val') < 0.05)",
    "filter_cmp_eq_string": "df_modified = df.filter(pl.col('habitat') == 'Sediment')",
    "filter_cmp_ne_null_drop": "df_modified = df.filter(pl.col('habitat') != 'Sediment')",
    "filter_is_null": "df_modified = df.filter(pl.col('value').is_null())",
    "filter_is_not_null": "df_modified = df.filter(pl.col('habitat').is_not_null())",
    "filter_is_in_int": "df_modified = df.filter(pl.col('batch').is_in([1, 3]))",
    "filter_is_in_bool": "df_modified = df.filter(pl.col('flag').is_in([True]))",
    "filter_pred_tree": (
        "df_modified = df.filter("
        "(pl.col('habitat').is_in(['Riverwater', 'Marsh']) | (pl.col('value') >= 2.0))"
        " & ~pl.col('value').is_null()"
        " & (pl.col('q_val') <= 0.08))"
    ),
    "unpivot_three_metrics": (
        "df_modified = df.unpivot(on=['shannon', 'faith_pd', 'evenness'],"
        " index=['sample_id', 'habitat'], variable_name='metric', value_name='value')"
    ),
    "unpivot_no_index_defaults": "df_modified = df.unpivot(on=['shannon', 'evenness'])",
    "group_by_habitat_all_aggs": (
        "df_modified = df.group_by('habitat', maintain_order=True).agg("
        "pl.col('value').sum().alias('sum'),"
        "pl.col('value').mean().alias('mean'),"
        "pl.col('value').median().alias('median'),"
        "pl.col('value').min().alias('min'),"
        "pl.col('value').max().alias('max'),"
        "pl.col('value').count().alias('count'),"
        "pl.col('value').n_unique().alias('nunique'),"
        "pl.col('value').std().alias('std'),"
        "pl.col('value').var().alias('var'),"
        "pl.col('value').first().alias('first'),"
        "pl.col('value').last().alias('last'))"
    ),
    "group_by_two_keys": (
        "df_modified = df.group_by(['habitat', 'batch'], maintain_order=True).agg("
        "pl.col('value').mean(), pl.col('n_reads').sum().alias('reads'))"
    ),
    "group_by_singleton_groups": (
        "df_modified = df.group_by('sample_id', maintain_order=True).agg("
        "pl.col('value').std().alias('std'),"
        "pl.col('value').var().alias('var'),"
        "pl.col('value').count().alias('count'))"
    ),
    "group_by_non_numeric_aggs": (
        "df_modified = df.group_by('batch', maintain_order=True).agg("
        "pl.col('label').first().alias('first_label'),"
        "pl.col('label').last().alias('last_label'),"
        "pl.col('label').min().alias('min_label'),"
        "pl.col('label').max().alias('max_label'),"
        "pl.col('label').n_unique().alias('n_labels'),"
        "pl.col('event_time').min().alias('first_seen'),"
        "pl.col('event_time').max().alias('last_seen'),"
        "pl.col('flag').count().alias('flag_count'),"
        "pl.col('flag').n_unique().alias('flag_nunique'))"
    ),
    "group_by_len_vs_count_nulls": (
        "df_modified = df.group_by('habitat', maintain_order=True).agg("
        "pl.len().alias('n_rows'),"
        "pl.col('value').count().alias('n_value'),"
        "pl.col('n_reads').count().alias('n_reads'),"
        "pl.col('value').len().alias('len_value'))"
    ),
    "group_by_len_default_aliases": (
        "df_modified = df.group_by('batch', maintain_order=True).agg("
        "pl.len(), pl.count(), pl.col('value').len())"
    ),
    "group_by_len_after_filter": (
        "df_modified = (df.filter(pl.col('q_val') < 0.05)"
        ".group_by('habitat', maintain_order=True)"
        ".agg(pl.len().alias('n_rows'), pl.col('value').count().alias('n_value')))"
    ),
    "chain_group_len_sort_desc": (
        "df_modified = (df.group_by('habitat', maintain_order=True)"
        ".agg(pl.count().alias('count'))"
        ".sort(['count', 'habitat'], descending=[True, False]))"
    ),
    "sort_label_asc": "df_modified = df.sort('label')",
    "sort_value_nulls_then_id": "df_modified = df.sort(['value', 'sample_id'])",
    "sort_value_desc_then_id": (
        "df_modified = df.sort(['value', 'sample_id'], descending=[True, False])"
    ),
    "sort_multi_mixed_direction": (
        "df_modified = df.sort(['habitat', 'q_val'], descending=[True, False])"
    ),
    "sort_datetime_desc": "df_modified = df.sort('event_time', descending=True)",
    "rename_two_columns": ("df_modified = df.rename({'value': 'measurement', 'habitat': 'site'})"),
    "chain_filter_unpivot_group_sort": (
        "df_modified = (df.filter(pl.col('habitat').is_not_null())"
        ".unpivot(on=['shannon', 'faith_pd', 'evenness'], index=['sample_id', 'habitat'],"
        " variable_name='metric', value_name='value')"
        ".group_by(['habitat', 'metric'], maintain_order=True)"
        ".agg(pl.col('value').mean(), pl.col('value').count().alias('n'))"
        ".sort('value', descending=True))"
    ),
    "chain_group_rename_sort": (
        "df_modified = (df.group_by('habitat', maintain_order=True)"
        ".agg(pl.col('value').mean())"
        ".rename({'value': 'mean_value'})"
        ".sort('habitat'))"
    ),
    "chain_empty_after_filter": (
        "df_modified = (df.filter(pl.col('q_val') > 99.0)"
        ".group_by('habitat', maintain_order=True)"
        ".agg(pl.col('value').mean())"
        ".sort('habitat'))"
    ),
}

FIXTURE_CASES = {case["name"]: case for case in FIXTURE["cases"]}
EXPECTED_CASES = {case["name"]: case for case in EXPECTED["cases"]}


class _PxStub:
    """``px.<anything>(...)`` -> ``None``: the suffix is not under test here."""

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def _exec_prologue(code: str, df: pl.DataFrame) -> pl.DataFrame:
    namespace: dict[str, Any] = {"pl": pl, "df": df, "px": _PxStub()}
    exec(compile(code, "<case>", "exec"), namespace)  # noqa: S102 - fixture-owned source
    result = namespace["df_modified"]
    assert isinstance(result, pl.DataFrame)
    return result


def test_case_code_covers_every_fixture_case():
    assert set(CASE_CODE) == set(FIXTURE_CASES) == set(EXPECTED_CASES)


def test_generator_output_matches_committed_fixture():
    """The committed fixture is not stale relative to the generator."""
    df = GEN.build_input()
    assert GEN.columns_payload(df) == FIXTURE["input"]["columns"]
    for name, case in FIXTURE_CASES.items():
        out = GEN.apply_ops(df, case["ops"])
        expected = EXPECTED_CASES[name]["output"]
        assert out.height == expected["length"], name
        assert GEN.columns_payload(out) == expected["columns"], name


@pytest.mark.parametrize("name", sorted(CASE_CODE))
def test_code_transpiles_to_the_case_ir_and_runs_identically(name):
    case = FIXTURE_CASES[name]
    prep = CASE_CODE[name]
    code = figure(prep, "df_modified")

    # code -> IR == the hand-written IR the fixture ships.
    assert ir(code) == case["ops"], name

    df = GEN.build_input()
    from_code = _exec_prologue(prep, df)
    from_ir = GEN.apply_ops(df, case["ops"])

    # code == IR execution == committed expectation.
    assert from_code.equals(from_ir), name
    payload = GEN.columns_payload(from_code)
    assert payload == EXPECTED_CASES[name]["output"]["columns"], name
    assert from_code.height == EXPECTED_CASES[name]["output"]["length"], name


def test_fixture_ops_validate_against_the_model():
    """The fixture is the TypeScript side's contract — it must be legal IR."""
    for case in FIXTURE["cases"]:
        ops = _OPS.validate_python(case["ops"])
        assert _OPS.dump_python(ops, mode="json") == case["ops"], case["name"]


def test_fixture_json_has_no_nan_tokens():
    for path in (FIXTURE_PATH, EXPECTED_PATH):
        text = path.read_text()
        assert "NaN" not in text and "Infinity" not in text, path
