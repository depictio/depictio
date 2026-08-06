"""AST-allowlist executor: what runs, what's blocked, how failures surface.

Everything is pure — no DB, no LLM, no network. The executor must NEVER
raise: failures come back as ExecutionStep(status="error") so the analyze
trace stays renderable end-to-end.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.api.v1.endpoints.ai_endpoints.executor import execute_polars


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


class TestFailureSurface:
    def test_empty_code_is_warning(self, df):
        step = execute_polars("", df)
        assert step.status == "warning"

    def test_missing_column_is_error_not_raise(self, df):
        step = execute_polars("df.filter(pl.col('nope') > 1)", df)
        assert step.status == "error"
        assert "nope" in step.output
