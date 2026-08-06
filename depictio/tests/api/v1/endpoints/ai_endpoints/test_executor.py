"""AST-allowlist executor: what runs, what's blocked, how failures surface.

Everything is pure — no DB, no LLM, no network. The executor must NEVER
raise: failures come back as ExecutionStep(status="error") so the analyze
trace stays renderable end-to-end.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from depictio.api.v1.endpoints.ai_endpoints.executor import (
    MAX_OUTPUT_ROWS,
    execute_polars,
    grammar_block,
)


@pytest.fixture()
def df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "sample": ["a", "b", "c", "d"],
            "depth": [10, 20, 30, 40],
            "quality": [0.9, 0.8, 0.7, 0.6],
        }
    )


class TestAllowedExpressions:
    def test_simple_filter(self, df):
        step = execute_polars("df.filter(pl.col('depth') >= 30)", df)
        assert step.status == "success"
        assert "30" in step.output

    def test_group_by_agg(self, df):
        step = execute_polars(
            "df.group_by('sample').agg(pl.col('depth').mean())",
            df,
        )
        assert step.status == "success"

    def test_describe(self, df):
        step = execute_polars("df.describe()", df)
        assert step.status == "success"

    def test_chained_sort_head(self, df):
        step = execute_polars("df.sort('quality').head(2)", df)
        assert step.status == "success"


class TestBlockedExpressions:
    @pytest.mark.parametrize(
        "code",
        [
            "__import__('os')",
            "import os",
            "open('/etc/passwd')",
            "df.__class__",
            "df.filter(lambda x: True)",
            "[x for x in range(3)]",
            "print('hi')",
            "getattr(df, 'filter')",
            "df.write_csv('/tmp/x.csv')",
            "pl.read_csv('/etc/passwd')",
            "exec('1+1')",
        ],
    )
    def test_blocked(self, code, df):
        step = execute_polars(code, df)
        assert step.status == "error"
        assert "BlockedByPolicy" in step.output or "SyntaxError" in step.output

    def test_unknown_name(self, df):
        step = execute_polars("os.path.join('a', 'b')", df)
        assert step.status == "error"


class TestWidenedGrammar:
    """The verbs level 2 needs, and the namespace dispatch behind them."""

    @pytest.mark.parametrize(
        "code",
        [
            # windowing: compare a row to its own group
            "df.with_columns(pl.col('depth').mean().over('sample').alias('grp'))",
            # quantiles, in the loop rather than via the threshold path
            "df.select(pl.col('depth').quantile(0.9))",
            # correlation, which the model reaches for unprompted
            "df.select(pl.corr('depth', 'quality'))",
            # reshape: any matrix or heatmap
            "df.pivot(values='depth', index='sample', on='sample')",
            "df.unpivot(index='sample')",
            # cleanup
            "df.with_columns(pl.col('depth').fill_null(0).abs().round(2))",
            "df.filter(pl.col('depth').is_between(10, 30))",
            "df.top_k(2, by='depth')",
            # when/then/otherwise: `when` was allowlisted but unusable
            # without its continuations, so this is the regression guard.
            "df.with_columns(pl.when(pl.col('depth') > 20).then(pl.lit('hi')).otherwise(pl.lit('lo')).alias('band'))",
        ],
    )
    def test_allowed(self, code, df):
        step = execute_polars(code, df)
        assert step.status == "success", step.output


class TestNamespaces:
    def test_str_namespace_allowed(self, df):
        step = execute_polars("df.filter(pl.col('sample').str.contains('a'))", df)
        assert step.status == "success", step.output

    def test_dt_namespace_allowed(self):
        frame = pl.DataFrame({"d": pl.date_range(date(2024, 1, 1), date(2024, 1, 4), eager=True)})
        step = execute_polars("df.select(pl.col('d').dt.year())", frame)
        assert step.status == "success", step.output

    def test_unlisted_namespace_method_still_blocked(self, df):
        # `.str` is reachable; that must not make every method under it so.
        step = execute_polars("df.select(pl.col('sample').str.to_titlecase())", df)
        assert step.status == "error"
        assert "disallowed .str method" in step.output

    def test_namespace_does_not_smuggle_a_frame_method(self, df):
        step = execute_polars("df.select(pl.col('sample').str.write_csv('/tmp/x'))", df)
        assert step.status == "error"
        assert "BlockedByPolicy" in step.output


class TestExprAndFrameSetsAreSeparate:
    def test_pl_helper_is_not_a_frame_method(self, df):
        # Pre-split, `when`/`Int64` lived in the set unioned into the frame
        # check, so `df.when(...)` validated and only failed at runtime.
        step = execute_polars("df.when(pl.col('depth') > 1)", df)
        assert step.status == "error"
        assert "disallowed method 'when'" in step.output

    def test_to_pandas_is_gone(self, df):
        step = execute_polars("df.to_pandas()", df)
        assert step.status == "error"
        assert "BlockedByPolicy" in step.output


class TestOutputCaps:
    def test_tall_frame_is_capped_by_rows(self):
        frame = pl.DataFrame({"n": list(range(MAX_OUTPUT_ROWS * 3))})
        step = execute_polars("df", frame)
        assert step.status == "success"
        assert "rows not shown" in step.output

    def test_to_dicts_is_capped_by_items(self):
        frame = pl.DataFrame({"n": list(range(MAX_OUTPUT_ROWS * 3))})
        step = execute_polars("df.to_dicts()", frame)
        assert step.status == "success"
        assert "items not shown" in step.output

    def test_small_result_is_not_annotated(self, df):
        step = execute_polars("df.head(2)", df)
        assert step.status == "success"
        assert "not shown" not in step.output


class TestMultiDCScope:
    """`dc["tag"]` — the multi-collection scope. `join` was always in the
    allowlist; what was missing was a second frame to join against."""

    @pytest.fixture()
    def scope(self, df) -> dict[str, pl.DataFrame]:
        return {
            "obs": df,
            "meta": pl.DataFrame({"sample": ["a", "b"], "site": ["x", "y"]}),
        }

    def test_cross_dc_join(self, df, scope):
        step = execute_polars(
            "dc['obs'].join(dc['meta'], on='sample', how='inner').height",
            df,
            scope=scope,
        )
        assert step.status == "success", step.output
        assert step.output == "2"

    def test_df_still_aliases_the_default(self, df, scope):
        step = execute_polars("df.height", df, scope=scope)
        assert step.status == "success"
        assert step.output == "4"

    def test_unknown_tag_names_the_available_ones(self, df, scope):
        step = execute_polars("dc['nope'].height", df, scope=scope)
        assert step.status == "error"
        assert "unknown data collection 'nope'" in step.output
        assert "meta" in step.output and "obs" in step.output

    def test_dc_method_calls_are_still_gated(self, df, scope):
        # Rooting at `dc` must not open anything the `df` root would block.
        step = execute_polars("dc['obs'].write_csv('/tmp/x.csv')", df, scope=scope)
        assert step.status == "error"
        assert "BlockedByPolicy" in step.output

    def test_no_scope_means_helpful_error_not_crash(self, df):
        step = execute_polars("dc['anything'].height", df)
        assert step.status == "error"
        assert "unknown data collection" in step.output


class TestGrammarBlock:
    """The prompt recital is generated, so it cannot drift from the policy."""

    def test_lists_allowed_verbs(self):
        block = grammar_block()
        for verb in ("over", "quantile", "pivot", "then", "otherwise"):
            assert verb in block

    def test_does_not_advertise_what_policy_rejects(self, df):
        block = grammar_block()
        for verb in ("read_csv", "write_csv", "to_pandas"):
            assert verb not in block

    def test_every_advertised_df_method_is_accepted_by_the_validator(self):
        from depictio.api.v1.endpoints.ai_endpoints import executor

        block = grammar_block()
        for name in executor.ALLOWED_DF_METHODS:
            assert name in block

    def test_tags_advertise_the_dc_scope(self):
        block = grammar_block(["obs", "meta"])
        assert 'dc["obs"]' in block and 'dc["meta"]' in block
        assert "alias for the first" in block

    def test_no_tags_keeps_the_single_frame_wording(self):
        assert "dc[" not in grammar_block()


class TestFailureSurface:
    def test_empty_code_is_warning(self, df):
        step = execute_polars("", df)
        assert step.status == "warning"

    def test_missing_column_is_error_not_raise(self, df):
        step = execute_polars("df.filter(pl.col('nope') > 1)", df)
        assert step.status == "error"
        assert "nope" in step.output
