"""What an independent QA pass of the UI joins found, each pinned by a test.

Key columns of an outer / right join, columns both tables hold, a cleared
source, the run a joined row carries, the dashboards a join feeds, and what a
table write tells about the joins that read it.
"""

from __future__ import annotations

import shutil
from unittest.mock import MagicMock

import polars as pl
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.datacollections_endpoints import table_manage
from depictio.api.v1.endpoints.joins_endpoints import service


def _partial(env) -> tuple[str, str]:
    """Ids 1..4 on the left, 3..6 on the right: two matches, two strays each side."""
    left = env.add_table("left_partial", pl.DataFrame({"id": [1, 2, 3, 4], "colour": list("abcd")}))
    right = env.add_table(
        "right_partial", pl.DataFrame({"id": [3, 4, 5, 6], "size": [30, 40, 50, 60]})
    )
    return left, right


def _visible(frame: pl.DataFrame) -> list[str]:
    return [c for c in frame.columns if c not in service.BOOKKEEPING_COLUMNS]


def _clear(env, dc_id: str, monkeypatch) -> dict:
    """Manage data, Clear: the Delta files go (here, the directory), then the rebuild."""
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": f"{dc_id}/part-0.parquet"}]}
    ]
    monkeypatch.setattr(table_manage, "s3_client", client)
    monkeypatch.setattr(
        table_manage, "delete_keys", lambda _c, _b, _k: shutil.rmtree(env.where(dc_id))
    )
    return table_manage.clear_table_data(data_collection_id=dc_id, current_user=env.owner)


class TestOneKeyColumn:
    @pytest.mark.parametrize("how", ["left", "inner", "outer", "right"])
    def test_every_join_type_has_one_key_column_and_no_empty_key(self, env, how):
        left, right = _partial(env)
        body = env.preview(left_dc_id=left, right_dc_id=right, on_columns=["id"], how=how).json()
        assert body["joined_columns"] == ["id", "colour", "size"]
        ids = [row["id"] for row in body["sample_rows"]]
        assert None not in ids
        expected = {"left": [1, 2, 3, 4], "inner": [3, 4], "outer": [1, 2, 3, 4, 5, 6]}
        assert sorted(ids) == expected.get(how, [3, 4, 5, 6])

    def test_the_stored_outer_join_has_one_key_column(self, env):
        left, right = _partial(env)
        created = env.create_ok(
            name="all_ids", left_dc_id=left, right_dc_id=right, on_columns=["id"], how="outer"
        )
        stored = env.read(created["data_collection_id"])
        assert _visible(stored) == ["id", "colour", "size"]
        assert sorted(stored["id"].to_list()) == [1, 2, 3, 4, 5, 6]

    def test_multi_column_keys_are_one_column_each(self, env):
        a = env.add_table(
            "multi_a",
            pl.DataFrame(
                {"sample": ["s1", "s1", "s2", "s2"], "lane": [1, 2, 1, 2], "reads": [1, 2, 3, 4]}
            ),
        )
        b = env.add_table(
            "multi_b",
            pl.DataFrame(
                {"sample": ["s1", "s1", "s2", "s3"], "lane": [1, 2, 2, 1], "qc": list("wxyz")}
            ),
        )
        body = env.preview(
            left_dc_id=a, right_dc_id=b, on_columns=["sample", "lane"], how="outer"
        ).json()
        assert body["joined_columns"] == ["sample", "lane", "reads", "qc"]
        assert body["joined_rows"] == 5
        assert all(r["sample"] and r["lane"] for r in body["sample_rows"])


class TestSharedColumns:
    def test_a_column_of_both_tables_is_kept_from_both(self, env):
        a = env.add_table("shared_a", pl.DataFrame({"id": [1, 2, 3], "note": ["L1", "L2", "L3"]}))
        b = env.add_table(
            "shared_b", pl.DataFrame({"id": [1, 2, 4], "note": ["R1", "R2", "R4"], "z": [1, 2, 4]})
        )
        body = env.preview(left_dc_id=a, right_dc_id=b, on_columns=["id"]).json()
        assert body["joined_columns"] == ["id", "note", "note_right", "z"]
        assert body["renamed_columns"] == [{"column": "note", "renamed_to": "note_right"}]
        assert body["warnings"] == [
            "Column note is in both tables: the copy from 'shared_b' is kept as note_right."
        ]
        assert body["sample_rows"][0] == {"id": 1, "note": "L1", "note_right": "R1", "z": 1}


class TestSuggestedKey:
    def test_a_unique_column_is_preferred(self, env):
        assert env.preview(on_columns=[]).json()["on_columns"] == ["individual_id"]

    def test_two_columns_when_one_alone_repeats_rows(self, env):
        a = env.add_table(
            "multi_a",
            pl.DataFrame(
                {"sample": ["s1", "s1", "s2", "s2"], "lane": [1, 2, 1, 2], "reads": [1, 2, 3, 4]}
            ),
        )
        b = env.add_table(
            "multi_b",
            pl.DataFrame(
                {"sample": ["s1", "s1", "s2", "s3"], "lane": [1, 2, 2, 1], "qc": list("wxyz")}
            ),
        )
        body = env.preview(left_dc_id=a, right_dc_id=b, on_columns=[]).json()
        assert body["suggested_on_columns"] == ["sample", "lane"]
        assert body["warnings"] == []


class TestClearedSource:
    @pytest.fixture()
    def joined(self, env) -> str:
        return env.create_ok()["data_collection_id"]

    def test_a_cleared_right_table_leaves_the_left_rows_with_empty_columns(
        self, env, joined, monkeypatch
    ):
        result = _clear(env, env.phys, monkeypatch)

        assert [(r["join"], r["status"]) for r in result["joins"]] == [("demo_phys", "rebuilt")]
        stored = env.read(joined)
        assert stored.height == 6
        assert _visible(stored) == [
            "individual_id",
            "island",
            "sex",
            "year",
            "species",
            "bill_length_mm",
            "flipper_length_mm",
        ]
        assert stored["bill_length_mm"].null_count() == 6
        assert env.join("demo_phys")["last_error"] is None
        assert env.aggregations(joined)[-1]["rows_total"] == 6

    def test_a_cleared_left_table_empties_a_left_join(self, env, joined, monkeypatch):
        result = _clear(env, env.demo, monkeypatch)

        assert result["joins"][0]["status"] == "rebuilt"
        assert env.read(joined).height == 0
        assert "bill_length_mm" in env.read(joined).columns
        assert env.aggregations(joined)[-1]["rows_total"] == 0

    def test_a_cleared_side_empties_an_inner_join(self, env, monkeypatch):
        inner = env.create_ok(name="both", how="inner")["data_collection_id"]
        _clear(env, env.phys, monkeypatch)
        assert env.read(inner).height == 0

    def test_data_back_in_the_cleared_table_comes_back_in_the_join(self, env, joined, monkeypatch):
        from depictio.tests.api.v1.endpoints.joins_endpoints.conftest import physical_features

        _clear(env, env.phys, monkeypatch)
        env.append(env.phys, physical_features())
        stored = env.read(joined)
        assert stored.height == 6
        assert stored["bill_length_mm"].null_count() == 1  # id 6 has no measurements


class TestRunOfAJoinedRow:
    def test_a_joined_row_carries_its_left_rows_run_and_never_the_right_ones(self, env):
        from depictio.tests.api.v1.endpoints.joins_endpoints.test_rebuild_guards import (
            _measures,
            _new_individuals,
        )

        joined = env.create_ok()["data_collection_id"]
        assert set(env.read(joined)["depictio_run_id"].to_list()) == {
            "demographic_data-single-file-scan"
        }
        # Census first: the left table loses its runs (a web append keeps none) ...
        env.append(env.demo, _new_individuals(8))
        assert "depictio_run_id" not in env.read(joined).columns
        # ... and the right table's never stands in for them.
        env.append(env.phys, _measures(8))
        assert "depictio_run_id" not in env.read(joined).columns
        tags = [a.get("run_tags") or [] for a in env.aggregations(joined)]
        assert tags[0] == ["demographic_data-single-file-scan"]
        assert all(t == [] for t in tags[1:])


class TestDashboardsOfAJoin:
    def test_the_list_names_the_dashboards_reading_a_joined_table(self, env):
        joined = env.create_ok()["data_collection_id"]
        main, other = ObjectId(), ObjectId()
        grant = {"owners": [{"_id": env.owner.id, "email": env.owner.email}]}
        env.db["dashboards"].insert_many(
            [
                {
                    "dashboard_id": main,
                    "title": "Penguins",
                    "project_id": env.project_oid,
                    "permissions": grant,
                    "stored_metadata": [{"dc_id": ObjectId(joined)}],
                },
                {  # a tab of it, reading the same table: still one dashboard
                    "dashboard_id": ObjectId(),
                    "title": "Tab 2",
                    "parent_dashboard_id": main,
                    "project_id": env.project_oid,
                    "permissions": grant,
                    "stored_metadata": [{"dc_id": joined}],
                },
                {  # somebody else's
                    "dashboard_id": other,
                    "title": "Private",
                    "project_id": env.project_oid,
                    "permissions": {"owners": [{"_id": ObjectId(), "email": "x@example.org"}]},
                    "stored_metadata": [{"dc_id": joined}],
                },
                {  # reads a source, not the join
                    "dashboard_id": ObjectId(),
                    "title": "Sources",
                    "project_id": env.project_oid,
                    "permissions": grant,
                    "stored_metadata": [{"dc_id": env.demo}],
                },
            ]
        )

        (entry,) = env.request(env.owner, "GET", "").json()["joins"]

        assert entry["dashboards"] == [
            {"id": str(main), "title": "Penguins"},
            {"id": None, "title": "A dashboard you cannot open"},
        ]

    def test_no_dashboard(self, env):
        env.create_ok()
        assert env.request(env.owner, "GET", "").json()["joins"][0]["dashboards"] == []


class TestWritesReportTheirJoins:
    def test_an_append_answers_the_rebuild_of_each_join(self, env):
        from depictio.tests.api.v1.endpoints.joins_endpoints.test_rebuild_guards import (
            _new_individuals,
        )

        joined = env.create_ok()["data_collection_id"]
        result = env.append(env.demo, _new_individuals(8))
        (report,) = result["joins"]
        assert report["join"] == "demo_phys"
        assert report["status"] == "rebuilt"
        assert report["rows"] == 7
        assert report["data_collection_id"] == joined

    def test_a_table_no_join_reads_answers_none(self, env):
        from depictio.tests.api.v1.endpoints.joins_endpoints.test_rebuild_guards import (
            _new_individuals,
        )

        assert env.append(env.demo, _new_individuals(8))["joins"] == []


class TestKeyTypes:
    def test_a_number_key_joined_to_a_text_key_is_said(self, env):
        text_ids = env.add_table(
            "text_ids",
            pl.DataFrame({"individual_id": ["1", "2", "9"], "colour": ["red", "blue", "green"]}),
        )
        preview = env.preview(right_dc_id=text_ids).json()

        assert (
            "individual_id is a whole number in 'demographic_data' and text in 'text_ids': "
            "compared as text."
        ) in preview["warnings"]
        assert preview["matched_keys"] == 2  # still compared, as text

    def test_keys_of_the_same_kind_say_nothing(self, env):
        preview = env.preview().json()
        assert not [w for w in preview["warnings"] if "compared as text" in w]
