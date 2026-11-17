"""A file dropped on a table: POST /datacollections/{id}/merge_file.

Same harness as the cell edits: a real Delta table, a mongomock project and the
real router, so a preview and an apply are checked against what lands on disk.
"""

from __future__ import annotations

from unittest.mock import patch

import polars as pl
import pytest

from depictio.api.v1.endpoints.datacollections_endpoints import table_manage, table_merge
from depictio.models.models.deltatables import latest_complete_aggregation
from depictio.tests.api.v1.endpoints.datacollections_endpoints.test_table_edit import (
    DC_ID,
    _user,
    env,  # noqa: F401  (fixture)
)


@pytest.fixture(autouse=True)
def merge_env(env):  # noqa: F811
    with patch.object(table_merge, "_delta_location_for", lambda _dc: env.location):
        yield env


def _nulls(env_):
    """The table with gaps: s1 lacks an age, s2 a name."""
    pl.DataFrame(
        {
            "sample": ["s1", "s2", "s3"],
            "age": [None, 20, 30],
            "tissue": ["liver", None, "lung"],
            "aggregation_time": ["2025-01-01 00:00:00"] * 3,
        },
        schema_overrides={"age": pl.Int64},
    ).write_delta(env_.location, mode="overwrite", delta_write_options={"schema_mode": "overwrite"})


def _post(env_, csv: str, *, name="meta.csv", dry_run=True, base=None, **fields):
    data = {
        "dry_run": str(dry_run).lower(),
        "base_version": str(env_.version() if base is None else base),
        **fields,
    }
    return env_.client.post(
        f"/datacollections/{DC_ID}/merge_file",
        files={"file": (name, csv.encode(), "text/csv")},
        data=data,
    )


class TestPreview:
    def test_writes_nothing_and_finds_the_key(self, merge_env):
        merge_env.project(owners=[merge_env.user])
        before = merge_env.version()

        response = _post(merge_env, "sample,batch\ns2,B\ns1,A\nzz,Q\n", mode="add_columns")

        assert response.status_code == 200, response.text
        body = response.json()
        assert merge_env.version() == before
        assert body["key"] == "sample"
        assert body["new_columns"] == ["batch"]
        assert body["matched_rows"] == 2
        assert body["unmatched_file_rows"] == 1
        assert body["unmatched_file_sample"] == ["zz"]
        assert [r["batch"] for r in body["rows"]] == ["A", "B", None]
        assert next(c for c in body["columns"] if c["name"] == "batch")["is_new"] is True

    def test_auto_prefers_new_columns_then_gaps_then_replace(self, merge_env):
        merge_env.project(owners=[merge_env.user])
        _nulls(merge_env)

        assert _post(merge_env, "sample,batch\ns1,A\n").json()["mode"] == "add_columns"
        assert _post(merge_env, "sample,age\ns1,11\n").json()["mode"] == "fill_missing"
        assert _post(merge_env, "other,thing\n1,2\n").json()["mode"] == "replace"

    def test_a_number_key_matches_its_text_form(self, merge_env):
        merge_env.project(owners=[merge_env.user])

        body = _post(merge_env, "age,batch\n10.0,A\n20,B\n", mode="add_columns").json()

        assert body["key"] == "age"
        assert body["matched_rows"] == 2

    def test_nothing_to_link_cannot_be_applied(self, merge_env):
        merge_env.project(owners=[merge_env.user])

        body = _post(merge_env, "other,thing\n1,2\n", mode="add_columns").json()

        assert body["can_apply"] is False
        assert "No column links" in body["reason"]


class TestApply:
    def test_add_columns_keeps_rows_and_records_specs(self, merge_env):
        merge_env.project(owners=[merge_env.user])
        before = merge_env.version()

        response = _post(
            merge_env, "sample,batch,age\ns3,C,99\ns1,A,99\n", mode="add_columns", dry_run=False
        )

        assert response.status_code == 200, response.text
        assert merge_env.version() == before + 1
        after = merge_env.read()
        assert after["sample"].to_list() == ["s1", "s2", "s3"]
        assert after["batch"].to_list() == ["A", None, "C"]
        assert after["age"].to_list() == [10, 20, 30]
        assert "aggregation_time" in after.columns
        assert response.json()["ignored_columns"] == ["age"]
        assert merge_env.invalidated == [str(DC_ID)]
        doc = merge_env.db["deltatables"].find_one({"data_collection_id": DC_ID})
        specs = latest_complete_aggregation(doc["aggregation"])["aggregation_columns_specs"]
        assert "batch" in {s["name"] for s in specs}

    def test_fill_missing_only_touches_empty_cells(self, merge_env):
        merge_env.project(owners=[merge_env.user])
        _nulls(merge_env)

        response = _post(
            merge_env,
            "sample,age,tissue\ns1,11,kept?\ns2,99,heart\n",
            mode="fill_missing",
            dry_run=False,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["filled_cells"] == 2
        assert body["conflicts"] == 2
        after = merge_env.read()
        assert after["age"].to_list() == [11, 20, 30]
        assert after["tissue"].to_list() == ["liver", "heart", "lung"]
        assert after.schema["age"] == pl.Int64

    def test_fill_missing_skips_a_value_that_does_not_fit(self, merge_env):
        merge_env.project(owners=[merge_env.user])
        _nulls(merge_env)

        body = _post(merge_env, "sample,age\ns1,notanumber\n", mode="fill_missing").json()

        assert body["filled_cells"] == 0
        assert body["can_apply"] is False
        assert len(body["warnings"]) == 1

    def test_replace_warns_of_removed_columns(self, merge_env):
        merge_env.project(owners=[merge_env.user])

        response = _post(merge_env, "sample,batch\nx,A\ny,B\n", mode="replace", dry_run=False)

        assert response.status_code == 200, response.text
        assert "age" in response.json()["removed_columns"]
        after = merge_env.read()
        assert after["sample"].to_list() == ["x", "y"]
        assert "age" not in after.columns

    def test_nothing_new_is_refused(self, merge_env):
        merge_env.project(owners=[merge_env.user])

        response = _post(merge_env, "sample,age\ns1,1\n", mode="add_columns", dry_run=False)

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "nothing_to_apply"


class TestRefusals:
    def test_a_key_with_duplicates_is_named(self, merge_env):
        merge_env.project(owners=[merge_env.user])

        response = _post(merge_env, "sample,batch\ns1,A\ns1,B\n", mode="add_columns", key="sample")

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "invalid_key"
        assert "s1" in detail["message"]

    def test_a_duplicated_column_is_no_candidate(self, merge_env):
        merge_env.project(owners=[merge_env.user])

        body = _post(merge_env, "sample,age,batch\ns1,10,A\ns1,20,B\n").json()

        assert [c["column"] for c in body["key_candidates"]] == ["age"]

    def test_stale_version(self, merge_env):
        merge_env.project(owners=[merge_env.user])

        response = _post(merge_env, "sample,batch\ns1,A\n", dry_run=False, base=99)

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "stale_version"

    def test_unsupported_file(self, merge_env):
        merge_env.project(owners=[merge_env.user])

        response = _post(merge_env, "x", name="notes.pdf")

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "unsupported_file"

    def test_viewer_is_refused(self, merge_env):
        viewer = _user()
        merge_env.project(owners=[merge_env.user], viewers=[viewer])
        merge_env.current = viewer

        assert _post(merge_env, "sample,batch\ns1,A\n").status_code == 403

    def test_a_viewer_is_refused_before_the_size_check(self, merge_env):
        viewer = _user()
        merge_env.project(owners=[merge_env.user], viewers=[viewer])
        merge_env.current = viewer

        with patch.object(table_manage, "_MAX_PER_FILE_BYTES", 4):
            assert _post(merge_env, "sample,batch\ns1,A\n").status_code == 403

    def test_a_file_over_the_limit_is_refused(self, merge_env):
        merge_env.project(owners=[merge_env.user])

        with patch.object(table_manage, "_MAX_PER_FILE_BYTES", 4):
            response = _post(merge_env, "sample,batch\ns1,A\n")

        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "file_too_large"

    def test_pipeline_table_is_refused(self, merge_env):
        merge_env.project(owners=[merge_env.user], config={"type": "table", "source": "native"})

        assert _post(merge_env, "sample,batch\ns1,A\n").status_code == 403

    def test_published_project_is_refused(self, merge_env):
        merge_env.project(owners=[merge_env.user], locked=True)

        assert _post(merge_env, "sample,batch\ns1,A\n").status_code == 409
