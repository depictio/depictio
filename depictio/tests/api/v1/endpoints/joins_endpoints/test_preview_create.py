"""Previewing and creating a join of two uploaded tables (the workshop's penguins).

``demographic_data`` has 6 individuals, ``physical_features`` 6 too: id 6 has no
measurements and id 7 has no demographics. Each carries a ``depictio_run_id`` of
its own (``<tag>-single-file-scan``), as UI uploads do, which must not stop rows
meeting.
"""

from __future__ import annotations

import polars as pl
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.joins_endpoints.service import (
    SAMPLE_ROWS,
    UNMATCHED_SAMPLE,
    suggest_on_columns,
)
from depictio.tests.api.v1.endpoints.joins_endpoints.conftest import (
    demographic_data,
    physical_features,
)

BOOKKEEPING = {"aggregation_time", "depictio_run_id", "join_timestamp"}


def _value(x):
    return getattr(x, "value", x)


class TestPreview:
    def test_the_key_is_suggested_when_none_is_given(self, env):
        body = env.preview(on_columns=[]).json()
        assert body["suggested_on_columns"] == ["individual_id"]
        assert body["on_columns"] == ["individual_id"]
        assert body["shared_columns"] == ["individual_id"]

    def test_a_given_key_wins_over_the_suggestion(self, env):
        env.write(env.phys, physical_features().with_columns(pl.col("individual_id").alias("k")))
        env.write(env.demo, demographic_data().with_columns(pl.col("individual_id").alias("k")))
        body = env.preview(on_columns=["k"]).json()
        assert body["on_columns"] == ["k"]
        assert set(body["shared_columns"]) == {"individual_id", "k"}

    def test_a_left_join_keeps_every_left_row(self, env):
        body = env.preview(how="left").json()
        assert (body["left"]["rows"], body["right"]["rows"]) == (6, 6)
        assert body["joined_rows"] == 6
        assert body["matched_keys"] == 5
        assert body["how"] == "left"

    @pytest.mark.parametrize(
        ("how", "rows"), [("inner", 5), ("left", 6), ("right", 6), ("outer", 7)]
    )
    def test_the_row_count_follows_the_join_type(self, env, how, rows):
        assert env.preview(how=how).json()["joined_rows"] == rows

    def test_unmatched_rows_are_counted_and_named_on_each_side(self, env):
        body = env.preview().json()
        assert body["left"]["unmatched_rows"] == 1
        assert body["left"]["unmatched_sample"] == ["6"]
        assert body["right"]["unmatched_rows"] == 1
        assert body["right"]["unmatched_sample"] == ["7"]

    def test_the_sides_are_described(self, env):
        body = env.preview().json()
        assert body["left"]["data_collection_id"] == env.demo
        assert body["left"]["tag"] == "demographic_data"
        assert body["left"]["columns"] == ["individual_id", "island", "sex", "year", "species"]
        assert body["right"]["tag"] == "physical_features"
        assert body["right"]["columns"] == ["individual_id", "bill_length_mm", "flipper_length_mm"]

    def test_unmatched_samples_are_capped_and_distinct(self, env):
        many = pl.DataFrame({"individual_id": list(range(100, 120)) * 2, "x": [1] * 40})
        env.write(env.phys, many.with_columns(pl.lit("r").alias("depictio_run_id")))
        body = env.preview(how="outer").json()
        sample = body["right"]["unmatched_sample"]
        assert len(sample) == UNMATCHED_SAMPLE == len(set(sample))
        assert body["right"]["unmatched_rows"] == 40

    def test_bookkeeping_columns_are_never_shown(self, env):
        body = env.preview().json()
        assert not BOOKKEEPING & set(body["joined_columns"])
        assert not BOOKKEEPING & set(body["left"]["columns"] + body["right"]["columns"])
        assert not BOOKKEEPING & set(body["shared_columns"])
        assert all(not BOOKKEEPING & set(row) for row in body["sample_rows"])
        assert body["joined_columns"] == [
            "individual_id",
            "island",
            "sex",
            "year",
            "species",
            "bill_length_mm",
            "flipper_length_mm",
        ]

    def test_run_ids_that_differ_do_not_stop_rows_meeting(self, env):
        runs = (
            env.read(env.demo)["depictio_run_id"].unique().to_list()
            + env.read(env.phys)["depictio_run_id"].unique().to_list()
        )
        assert runs == ["demographic_data-single-file-scan", "physical_features-single-file-scan"]
        body = env.preview().json()
        assert body["matched_keys"] == 5
        by_id = {row["individual_id"]: row for row in body["sample_rows"]}
        assert by_id[1]["bill_length_mm"] == 39.1
        assert by_id[6]["bill_length_mm"] is None  # the one without a partner

    def test_the_sample_is_capped(self, env):
        many = pl.DataFrame({"individual_id": list(range(50)), "v": list(range(50))})
        env.write(env.demo, many.with_columns(pl.lit("d").alias("depictio_run_id")))
        env.write(
            env.phys, many.rename({"v": "w"}).with_columns(pl.lit("p").alias("depictio_run_id"))
        )
        body = env.preview().json()
        assert body["joined_rows"] == 50
        assert len(body["sample_rows"]) == SAMPLE_ROWS

    def test_nothing_is_written(self, env):
        before = env.project()
        env.preview()
        assert env.project() == before
        assert env.db["deltatables"].count_documents({}) == 0
        assert sorted(p.name for p in env.root.iterdir()) == sorted([env.demo, env.phys])

    def test_a_key_with_nothing_in_common_is_warned_about(self, env):
        env.write(
            env.phys,
            physical_features()
            .with_columns(pl.col("individual_id") + 1000)
            .with_columns(pl.lit("p").alias("depictio_run_id")),
        )
        body = env.preview().json()
        assert body["suggested_on_columns"] == []
        assert body["on_columns"] == ["individual_id"]  # falls back to the first shared column
        assert body["matched_keys"] == 0
        assert any("nothing matches" in w for w in body["warnings"])

    def test_a_repeated_key_on_the_right_is_warned_about(self, env):
        doubled = pl.concat([physical_features(), physical_features().head(1)])
        env.write(env.phys, doubled.with_columns(pl.lit("p").alias("depictio_run_id")))
        body = env.preview().json()
        assert body["joined_rows"] == 7
        # One plain sentence, not a second one in jargon.
        assert body["warnings"] == [
            "Some values of individual_id are on more than one row of 'physical_features': "
            "a row is repeated once per match, which gives 7 rows."
        ]

    def test_no_warning_for_unique_keys(self, env):
        assert env.preview().json()["warnings"] == []

    def test_keys_of_different_types_still_meet(self, env):
        as_text = physical_features().with_columns(pl.col("individual_id").cast(pl.String))
        env.write(env.phys, as_text.with_columns(pl.lit("p").alias("depictio_run_id")))
        body = env.preview().json()
        assert body["matched_keys"] == 5
        assert body["joined_rows"] == 6
        assert body["left"]["unmatched_sample"] == ["6"]

    def test_empty_keys_never_match(self, env):
        left = demographic_data().with_columns(
            pl.when(pl.col("individual_id") == 6)
            .then(None)
            .otherwise(pl.col("individual_id"))
            .alias("individual_id")
        )
        env.write(env.demo, left.with_columns(pl.lit("d").alias("depictio_run_id")))
        body = env.preview().json()
        assert body["left"]["unmatched_rows"] == 1
        assert body["left"]["unmatched_sample"] == ["(empty)"]


class TestSuggestOnColumns:
    def test_most_values_in_common_wins(self):
        left = pl.DataFrame({"a": [1, 2, 3], "b": [1, 1, 1]})
        right = pl.DataFrame({"a": [3, 4, 5], "b": [1, 2, 3]})
        assert suggest_on_columns(left, right, ["a", "b"]) == ["a"] or True
        # a: {3} in common; b: {1} in common; tie -> unique on the left -> a
        assert suggest_on_columns(left, right, ["a", "b"]) == ["a"]

    def test_a_column_with_more_in_common_beats_a_unique_one(self):
        left = pl.DataFrame({"id": [1, 2, 3, 4], "grp": ["x", "x", "y", "y"]})
        right = pl.DataFrame({"id": [9], "grp": ["x"]})
        # id shares nothing; grp shares one value
        assert suggest_on_columns(left, right, ["id", "grp"]) == ["grp"]

    def test_nothing_in_common_suggests_nothing(self):
        left = pl.DataFrame({"a": [1]})
        right = pl.DataFrame({"a": [2]})
        assert suggest_on_columns(left, right, ["a"]) == []

    def test_no_shared_column_suggests_nothing(self):
        assert suggest_on_columns(pl.DataFrame({"a": [1]}), pl.DataFrame({"b": [1]}), []) == []

    def test_numbers_match_their_text_form(self):
        left = pl.DataFrame({"a": [1, 2]})
        right = pl.DataFrame({"a": ["1", "2"]})
        assert suggest_on_columns(left, right, ["a"]) == ["a"]


class TestCreate:
    def test_the_response_carries_the_new_collection(self, env):
        body = env.create_ok()
        assert body["success"] is True
        assert body["rows"] == 6
        assert body["delta_version"] == 0
        assert body["data_collection_tag"] == "joined_demo_phys"
        assert ObjectId.is_valid(body["data_collection_id"])
        assert body["join"]["name"] == "demo_phys"
        assert body["join"]["result_dc_id"] == body["data_collection_id"]

    def test_the_join_is_stored_on_the_project(self, env):
        body = env.create_ok(description="penguins, measured")
        (stored,) = env.joins()
        assert stored["name"] == "demo_phys"
        assert stored["left_dc"] == "demographic_data"
        assert stored["right_dc"] == "physical_features"
        assert stored["on_columns"] == ["individual_id"]
        assert _value(stored["how"]) == "left"
        assert stored["description"] == "penguins, measured"
        assert stored["persist"] is True
        assert stored["match_run_ids"] is False
        assert stored["workflow_name"] == env.workflow_of(env.demo)["name"]
        assert stored["result_dc_id"] == ObjectId(body["data_collection_id"])
        assert stored["result_dc_tag"] == "joined_demo_phys"
        assert stored["row_count"] == 6
        assert stored["last_error"] is None
        assert stored["last_checked_at"] is not None

    def test_a_joined_table_collection_sits_in_the_left_tables_workflow(self, env):
        body = env.create_ok()
        dc = env.dc_doc(body["data_collection_id"])
        assert dc is not None
        assert dc["data_collection_tag"] == "joined_demo_phys"
        assert dc["config"]["type"] == "table"
        assert _value(dc["config"]["source"]) == "joined"
        assert dc["config"]["scan"] is None
        left_workflow = env.workflow_of(env.demo)
        assert body["data_collection_id"] in {
            str(c["_id"]) for c in left_workflow["data_collections"]
        }
        # ... and only once; the right table's workflow is left alone.
        assert env.tags().count("joined_demo_phys") == 1
        assert [
            c["data_collection_tag"] for c in env.workflow_of(env.phys)["data_collections"]
        ] == ["physical_features"]
        assert len(env.project()["workflows"]) == 2

    def test_the_table_is_written_as_a_left_join(self, env):
        body = env.create_ok()
        frame = env.read(body["data_collection_id"])
        assert frame.height == 6
        assert frame.sort("individual_id")["bill_length_mm"].to_list() == [
            39.1,
            46.5,
            49.0,
            50.2,
            45.3,
            None,
        ]
        assert "join_timestamp" in frame.columns
        assert set(frame["individual_id"].to_list()) == {1, 2, 3, 4, 5, 6}  # no id 7
        assert env.version(body["data_collection_id"]) == 0

    def test_the_aggregation_records_the_version_and_the_rows(self, env):
        body = env.create_ok()
        (aggregation,) = env.aggregations(body["data_collection_id"])
        assert aggregation["delta_version"] == 0
        assert aggregation["rows_total"] == 6
        assert aggregation["aggregation_version"] == 1
        assert aggregation["write_mode"] == "overwrite"
        assert aggregation["trigger"] == "ui"
        assert aggregation["aggregation_by"]["email"] == env.owner.email
        specs = {s["name"] for s in aggregation["aggregation_columns_specs"]}
        assert {"individual_id", "bill_length_mm", "flipper_length_mm"} <= specs
        assert env.invalidated == [body["data_collection_id"]]

    def test_the_size_of_the_table_is_recorded_on_its_collection(self, env):
        body = env.create_ok()
        metadata = env.dc_doc(body["data_collection_id"])["flexible_metadata"]
        assert metadata["deltatable_size_bytes"] > 0
        assert metadata["deltatable_size_mb"] >= 0

    def test_create_succeeds_when_the_collection_has_null_metadata(self, env):
        """persist_joined_table builds the collection with ``flexible_metadata: null``.

        MongoDB refuses to set a field of a null, so the size is recorded by first
        turning it into a document; the stand-in refuses the same way here.
        """
        env.projects.strict_null = True
        body = env.create_ok()
        dc_id = body["data_collection_id"]
        assert env.aggregations(dc_id)  # registered: the create did not fail halfway
        metadata = env.dc_doc(dc_id)["flexible_metadata"]
        assert metadata["deltatable_size_bytes"] > 0
        assert metadata["deltatable_size_mb"] >= 0

        env.append(
            env.demo,
            pl.DataFrame(
                {
                    "individual_id": [8],
                    "island": ["Dream"],
                    "sex": ["male"],
                    "year": [2010],
                    "species": ["Adelie"],
                }
            ),
        )
        assert env.version(dc_id) == 1  # and a rebuild records its size too
        assert env.join("demo_phys")["last_error"] is None

    def test_a_size_that_cannot_be_recorded_does_not_fail_the_join(self, env, monkeypatch):
        real = env.projects.update_one

        def refuse_sizes(flt, update, *args, **kwargs):
            if any("flexible_metadata" in path for path in update.get("$set", {})):
                raise RuntimeError("no size for you")
            return real(flt, update, *args, **kwargs)

        monkeypatch.setattr(env.projects, "update_one", refuse_sizes)
        body = env.create_ok()
        assert env.aggregations(body["data_collection_id"])
        assert env.joins()[0]["last_error"] is None

    def test_run_ids_that_differ_do_not_stop_rows_meeting(self, env):
        body = env.create_ok()
        frame = env.read(body["data_collection_id"])
        assert frame.filter(pl.col("bill_length_mm").is_not_null()).height == 5

    def test_the_sources_are_left_as_they_were(self, env):
        before = (env.version(env.demo), env.version(env.phys))
        env.create_ok()
        assert (env.version(env.demo), env.version(env.phys)) == before
        assert env.read(env.demo).height == 6 and env.read(env.phys).height == 6
        assert env.aggregations(env.demo) == [] and env.aggregations(env.phys) == []

    def test_an_inner_join_keeps_only_matches(self, env):
        body = env.create_ok(how="inner")
        assert body["rows"] == 5
        assert _value(env.join("demo_phys")["how"]) == "inner"

    def test_two_joins_of_one_pair_need_two_names(self, env):
        first = env.create_ok(name="a")
        second = env.create_ok(name="b", how="inner")
        assert first["data_collection_id"] != second["data_collection_id"]
        assert [j["name"] for j in env.joins()] == ["a", "b"]
        assert {"joined_a", "joined_b"} <= set(env.tags())

    def test_a_join_of_a_table_whose_tag_exists_twice_is_scoped_by_workflow(self, env):
        twin = env.add_table("physical_features", physical_features())
        env.create_ok(right_dc_id=twin)
        stored = env.join("demo_phys")
        assert stored["left_dc"] == "demographic_data"
        assert stored["right_dc"].endswith(".physical_features")
        assert "." in stored["right_dc"]
        assert env.request(env.owner, "GET", "").json()["joins"][0]["right_dc_id"] == twin


class TestCreateFailureRollsBack:
    def _assert_nothing_left(self, env):
        assert env.joins() == []
        assert env.tags() == ["demographic_data", "physical_features"]
        assert env.db["deltatables"].count_documents({}) == 0

    def test_a_table_that_cannot_be_written(self, env, monkeypatch):
        from depictio.cli.cli.utils import joins as cli_joins

        monkeypatch.setattr(
            cli_joins,
            "write_delta_table",
            lambda **kw: {"result": "error", "message": "disk full"},
        )
        response = env.create()
        assert response.status_code == 500
        assert response.json()["detail"]["code"] == "join_failed"
        assert "disk full" in response.json()["detail"]["message"]
        self._assert_nothing_left(env)
        # The name is free again.
        monkeypatch.undo()

    def test_a_registration_that_fails_after_the_project_was_updated(self, env, monkeypatch):
        """The join and its collection are on the project by then: both go, and so do the files."""
        from depictio.api.v1.endpoints.datacollections_endpoints import table_manage

        def boom(*args, **kwargs):
            raise RuntimeError("mongo is gone")

        monkeypatch.setattr(table_manage, "_bump_table_dc_aggregation", boom)
        response = env.create()
        assert response.status_code == 500
        assert "mongo is gone" in response.json()["detail"]["message"]
        self._assert_nothing_left(env)
        assert len(env.cleaned) == 1  # the written Delta files were asked to be removed

    def test_an_unexpected_error_is_a_join_failed_too(self, env, monkeypatch):
        from depictio.cli.cli.utils import joins as cli_joins

        def boom(*args, **kwargs):
            raise ValueError("kaboom")

        monkeypatch.setattr(cli_joins, "execute_join", boom)
        response = env.create()
        assert response.status_code == 500
        assert response.json()["detail"]["code"] == "join_failed"
        self._assert_nothing_left(env)

    def test_the_name_can_be_used_again_after_a_failure(self, env, monkeypatch):
        from depictio.api.v1.endpoints.datacollections_endpoints import table_manage

        real = table_manage._bump_table_dc_aggregation
        monkeypatch.setattr(table_manage, "_bump_table_dc_aggregation", lambda *a, **k: 1 / 0)
        assert env.create().status_code == 500
        monkeypatch.setattr(table_manage, "_bump_table_dc_aggregation", real)
        assert env.create().status_code == 200
        assert [j["name"] for j in env.joins()] == ["demo_phys"]
        assert env.tags().count("joined_demo_phys") == 1
