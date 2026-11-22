"""A join follows its sources, and the sources and the result are guarded.

Every write of a table through the web UI ends in ``commit_table_frame`` (or
``clear_table_data``), which re-runs the joins reading it. The tables are real
Delta tables, so "a new version" and "no new version" are read off the disk.
"""

from __future__ import annotations

import asyncio
import shutil
from unittest.mock import MagicMock

import polars as pl
import pytest
from fastapi import HTTPException

from depictio.api.v1.endpoints.datacollections_endpoints import table_manage
from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.api.v1.endpoints.joins_endpoints import service
from depictio.cli.cli.utils import joins as cli_joins
from depictio.tests.api.v1.endpoints.joins_endpoints.conftest import BOOKKEEPING, island_info


def _new_individuals(*ids: int) -> pl.DataFrame:
    """Demographics of individuals the table does not hold yet."""
    return pl.DataFrame(
        {
            "individual_id": list(ids),
            "island": ["Dream"] * len(ids),
            "sex": ["female"] * len(ids),
            "year": [2010] * len(ids),
            "species": ["Adelie"] * len(ids),
        }
    )


def _measures(*ids: int) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "individual_id": list(ids),
            "bill_length_mm": [40.0 + i for i in ids],
            "flipper_length_mm": [200 + i for i in ids],
        }
    )


def _by_id(frame: pl.DataFrame) -> dict[int, dict]:
    return {row["individual_id"]: row for row in frame.iter_rows(named=True)}


@pytest.fixture()
def joined(env) -> str:
    """The id of the collection ``demo_phys`` (a left join of the two tables)."""
    return env.create_ok()["data_collection_id"]


class TestRebuildOnAppend:
    def test_new_rows_of_the_left_table_reach_the_joined_table(self, env, joined):
        env.append(env.demo, _new_individuals(8, 9))

        assert env.version(joined) == 1
        frame = env.read(joined)
        assert frame.height == 8
        rows = _by_id(frame)
        assert rows[8]["species"] == "Adelie"
        assert rows[8]["bill_length_mm"] is None and rows[9]["bill_length_mm"] is None
        assert rows[1]["bill_length_mm"] == 39.1  # the rest is untouched

    def test_the_rebuild_is_recorded_like_any_write(self, env, joined):
        env.append(env.demo, _new_individuals(8, 9))

        first, second = env.aggregations(joined)
        assert (first["delta_version"], first["rows_total"]) == (0, 6)
        assert (second["delta_version"], second["rows_total"]) == (1, 8)
        assert second["aggregation_version"] == 2
        assert second["trigger"] == "ui"
        assert second["aggregation_columns_specs"]
        assert joined in env.invalidated
        assert env.join("demo_phys")["row_count"] == 8
        assert env.join("demo_phys")["last_error"] is None

    def test_left_rows_come_first_with_empty_right_values_then_the_right_append_fills_them(
        self, env, joined
    ):
        env.append(env.demo, _new_individuals(8, 9))
        waiting = _by_id(env.read(joined))
        assert waiting[8]["bill_length_mm"] is None
        assert waiting[9]["flipper_length_mm"] is None

        env.append(env.phys, _measures(8, 9))

        assert env.version(joined) == 2
        frame = env.read(joined)
        assert frame.height == 8  # a left join: still one row per individual
        resolved = _by_id(frame)
        assert resolved[8]["bill_length_mm"] == 48.0
        assert resolved[9]["flipper_length_mm"] == 209
        assert [a["rows_total"] for a in env.aggregations(joined)] == [6, 8, 8]

    def test_rows_of_the_right_table_alone_change_nothing_in_a_left_join(self, env, joined):
        """Id 99 is in no demographics row: the left join's rows are the same."""
        env.append(env.phys, _measures(99))

        assert env.version(joined) == 0
        assert len(env.aggregations(joined)) == 1
        assert env.join("demo_phys")["last_error"] is None

    def test_a_rebuild_that_changes_no_row_writes_no_version(self, env, joined):
        versions = env.version(joined)
        aggregations = len(env.aggregations(joined))

        reports = service.rebuild_dependent_joins(env.demo, env.owner)

        (report,) = reports
        assert report["status"] == "unchanged"
        assert report["join"] == "demo_phys"
        assert report["delta_version"] == versions == 0
        assert env.version(joined) == versions
        assert len(env.aggregations(joined)) == aggregations
        assert env.join("demo_phys")["last_error"] is None

    def test_a_second_rebuild_after_a_left_append_writes_nothing(self, env, joined):
        env.append(env.demo, _new_individuals(8))
        version = env.version(joined)

        (report,) = service.rebuild_dependent_joins(env.demo, env.owner)

        assert report["status"] == "unchanged"
        assert env.version(joined) == version

    def test_a_rebuild_that_changes_rows_reports_the_new_version(self, env, joined):
        env.write(env.phys, env.read(env.phys).with_columns(pl.col("bill_length_mm") + 1))

        (report,) = service.rebuild_dependent_joins(env.phys, env.owner)

        assert report["status"] == "rebuilt"
        assert report["data_collection_id"] == joined
        assert report["delta_version"] == 1
        assert report["rows"] == 6
        # Same row count, one value moved: still a change.
        assert _by_id(env.read(joined))[1]["bill_length_mm"] == 40.1

    def test_replacing_the_left_table_rebuilds_too(self, env, joined):
        table_manage.replace_table_uploads(
            data_collection_id=env.demo,
            decoded_files=[(_new_individuals(1, 2, 3).write_csv().encode(), "new.csv")],
            current_user=env.owner,
        )
        frame = env.read(joined)
        assert frame.height == 3
        assert env.version(joined) == 1
        assert _by_id(frame)[2]["bill_length_mm"] == 46.5

    def test_a_table_no_join_reads_triggers_nothing(self, env, joined):
        other = env.add_table("islands", island_info())
        env.append(other, pl.DataFrame({"island": ["Fiji"], "region": ["south"]}))
        assert env.version(joined) == 0
        assert service.rebuild_dependent_joins(other, env.owner) == []

    def test_a_project_without_joins_is_left_alone(self, env):
        assert service.rebuild_dependent_joins(env.demo, env.owner) == []
        env.append(env.demo, _new_individuals(8))  # nothing to rebuild, nothing raised

    @pytest.mark.parametrize("not_an_id", ["", "nope", "123"])
    def test_a_bad_id_rebuilds_nothing(self, env, joined, not_an_id):
        assert service.rebuild_dependent_joins(not_an_id, env.owner) == []


class TestRebuildFailure:
    def test_a_failed_rebuild_is_recorded_and_the_source_write_stands(
        self, env, joined, monkeypatch
    ):
        def boom(**kwargs):
            raise OSError("object store unreachable")

        monkeypatch.setattr(cli_joins, "write_delta_table", boom)

        result = env.append(env.demo, _new_individuals(8))  # does not raise

        assert result["rows_total"] == 7
        assert env.read(env.demo).height == 7
        stored = env.join("demo_phys")
        assert stored["last_error"] == (
            "An unexpected error stopped it (OSError: object store unreachable)."
        )
        assert result["joins"][0]["status"] == "failed"  # ... and the write says so
        assert result["joins"][0]["error"] == stored["last_error"]
        assert env.version(joined) == 0  # the joined table still shows the old rows
        assert env.read(joined).height == 6

    def test_the_next_good_rebuild_clears_the_error(self, env, joined, monkeypatch):
        with monkeypatch.context() as patched:
            patched.setattr(
                cli_joins, "write_delta_table", lambda **kw: {"result": "error", "message": "no"}
            )
            env.append(env.demo, _new_individuals(8))
        assert env.join("demo_phys")["last_error"] is not None

        env.append(env.demo, _new_individuals(9))

        assert env.join("demo_phys")["last_error"] is None
        assert env.read(joined).height == 8

    def test_the_write_that_fixes_a_failed_join_says_so(self, env, joined, monkeypatch):
        """Back to the data it was built from: the report says the join follows again."""
        before = env.read(env.demo).drop(BOOKKEEPING)
        with monkeypatch.context() as patched:
            patched.setattr(
                cli_joins, "write_delta_table", lambda **kw: {"result": "error", "message": "no"}
            )
            failed = env.append(env.demo, _new_individuals(8))
        assert failed["joins"][0]["status"] == "failed"

        fixed = table_manage.replace_table_uploads(
            data_collection_id=env.demo,
            decoded_files=[(before.write_csv().encode(), "demographic_data.csv")],
            current_user=env.owner,
        )

        # Rebuilt or, rows as stored, unchanged: either way the join is back.
        assert fixed["joins"][0]["status"] in ("rebuilt", "unchanged")
        assert fixed["joins"][0]["recovered"] is True
        assert env.join("demo_phys")["last_error"] is None

    def test_a_join_that_had_not_failed_is_not_recovered(self, env, joined):
        report = env.append(env.demo, _new_individuals(8))["joins"][0]
        assert report["status"] == "rebuilt"
        assert report["recovered"] is False

    def test_a_registration_that_fails_is_a_failed_rebuild(self, env, joined, monkeypatch):
        monkeypatch.setattr(
            table_manage, "_bump_table_dc_aggregation", MagicMock(side_effect=RuntimeError("db"))
        )
        (report,) = (
            service.rebuild_dependent_joins(env.phys, env.owner)
            or [None] * 0
            or [{"status": "unchanged"}]
        )
        # Nothing moved in the sources, so the join is unchanged and nothing is registered.
        assert report["status"] == "unchanged"
        env.write(env.phys, env.read(env.phys).with_columns(pl.col("bill_length_mm") + 1))
        (report,) = service.rebuild_dependent_joins(env.phys, env.owner)
        assert report["status"] == "failed"
        assert "registering it failed" in report["error"]
        assert "registering it failed" in env.join("demo_phys")["last_error"]

    def test_a_user_without_a_token_cannot_rebuild(self, env, joined):
        env.db["tokens"].delete_many({"user_id": env.editor.id})

        (report,) = service.rebuild_dependent_joins(env.demo, env.editor)

        assert report["status"] == "failed"
        assert "no usable access token" in report["error"]
        assert env.join("demo_phys")["last_error"] == report["error"]

    def test_a_source_and_a_join_that_both_lost_their_data_is_a_failed_rebuild(self, env, joined):
        shutil.rmtree(env.where(env.demo))
        shutil.rmtree(env.where(joined))

        (report,) = service.rebuild_dependent_joins(env.demo, env.owner)

        assert report["status"] == "failed"
        assert report["error"] == "The table 'demographic_data' holds no data."

    def test_rebuild_after_write_never_raises(self, env, joined, monkeypatch):
        def boom(*args):
            raise RuntimeError("everything is on fire")

        monkeypatch.setattr(service, "rebuild_dependent_joins", boom)

        (report,) = service.rebuild_after_write(env.demo, env.owner)
        assert report["status"] == "failed"
        assert report["error"] == "The joins reading this table were not rebuilt (RuntimeError)."
        # ... so the write that called it still succeeds.
        env.append(env.demo, _new_individuals(8))
        assert env.read(env.demo).height == 7

    def test_a_join_that_should_not_persist_is_skipped(self, env, joined):
        env.db["projects"].update_one(
            {"_id": env.project_oid}, {"$set": {"joins.0.persist": False}}
        )
        assert service.rebuild_dependent_joins(env.demo, env.owner) == []


class TestChainedJoins:
    @pytest.fixture()
    def chain(self, env, joined):
        islands = env.add_table("islands", island_info())
        outer = env.create_ok(
            name="with_region",
            left_dc_id=joined,
            right_dc_id=islands,
            on_columns=["island"],
        )["data_collection_id"]
        return joined, islands, outer

    def test_a_join_of_a_joined_table_is_created(self, env, chain):
        joined, islands, outer = chain
        assert env.read(outer).height == 6
        assert set(env.read(outer)["region"].to_list()) == {"north", "east", "west"}
        stored = env.join("with_region")
        assert stored["left_dc"] == "joined_demo_phys"
        assert stored["right_dc"] == "islands"
        assert env.dc_doc(outer)["data_collection_tag"] == "joined_with_region"

    def test_a_change_of_the_first_source_rebuilds_both_joins(self, env, chain):
        joined, _, outer = chain
        env.append(env.demo, _new_individuals(8))

        assert env.version(joined) == 1
        assert env.version(outer) == 1
        assert env.read(outer).height == 7
        assert _by_id(env.read(outer))[8]["region"] == "west"
        assert [a["rows_total"] for a in env.aggregations(outer)] == [6, 7]

    def test_the_reports_come_in_order_of_dependency(self, env, chain):
        env.write(env.phys, env.read(env.phys).with_columns(pl.col("bill_length_mm") + 1))

        reports = service.rebuild_dependent_joins(env.phys, env.owner)

        assert [r["join"] for r in reports] == ["demo_phys", "with_region"]
        assert [r["status"] for r in reports] == ["rebuilt", "rebuilt"]

    def test_the_second_join_alone_follows_its_own_source(self, env, chain):
        joined, islands, outer = chain
        env.append(islands, pl.DataFrame({"island": ["Dream"], "region": ["far west"]}))

        assert env.version(joined) == 0  # does not read the islands
        assert env.version(outer) == 1  # Dream's rows now meet two regions
        assert env.read(outer).height == 8

    def test_an_unchanged_first_join_does_not_rebuild_the_second(self, env, chain):
        _, _, outer = chain
        env.append(env.phys, _measures(99))  # no demographics row: nothing changes
        assert env.version(outer) == 0

    def test_a_join_that_others_read_cannot_be_deleted_first(self, env, chain):
        response = env.request(env.owner, "DELETE", "/demo_phys")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "join_in_use"
        assert "with_region" in response.json()["detail"]["message"]
        assert [j["name"] for j in env.joins()] == ["demo_phys", "with_region"]

    def test_deleting_from_the_outside_in_works(self, env, chain):
        assert env.request(env.owner, "DELETE", "/with_region").status_code == 200
        assert env.request(env.owner, "DELETE", "/demo_phys").status_code == 200
        assert env.joins() == []
        assert env.tags() == ["demographic_data", "physical_features", "islands"]


class TestGuards:
    def test_the_joined_table_cannot_be_appended_replaced_or_cleared(self, env, joined):
        upload = [(_new_individuals(8).write_csv().encode(), "x.csv")]
        calls = [
            lambda: table_manage.append_table_uploads(
                data_collection_id=joined, decoded_files=upload, current_user=env.owner
            ),
            lambda: table_manage.replace_table_uploads(
                data_collection_id=joined, decoded_files=upload, current_user=env.owner
            ),
            lambda: table_manage.clear_table_data(
                data_collection_id=joined, current_user=env.owner
            ),
        ]
        for call in calls:
            with pytest.raises(HTTPException) as caught:
                call()
            assert caught.value.status_code == 409
            assert "join of two other tables" in caught.value.detail
        assert env.read(joined).height == 6 and env.version(joined) == 0

    def test_a_source_a_join_reads_cannot_be_deleted(self, env, joined):
        for source in (env.demo, env.phys):
            with pytest.raises(HTTPException) as caught:
                asyncio.run(dc_utils._delete_data_collection_by_id(source, env.owner))
            assert caught.value.status_code == 409
            assert "demo_phys" in caught.value.detail
        assert {"demographic_data", "physical_features"} <= set(env.tags())

    def test_the_source_can_go_once_the_join_is_deleted(self, env, joined):
        assert env.request(env.owner, "DELETE", "/demo_phys").status_code == 200
        asyncio.run(dc_utils._delete_data_collection_by_id(env.demo, env.owner))
        assert "demographic_data" not in env.tags()

    def test_a_table_no_join_reads_can_be_deleted(self, env, joined):
        other = env.add_table("islands", island_info())
        asyncio.run(dc_utils._delete_data_collection_by_id(other, env.owner))
        assert "islands" not in env.tags()
        assert [j["name"] for j in env.joins()] == ["demo_phys"]

    def test_deleting_the_joined_table_takes_its_join_along(self, env, joined):
        asyncio.run(dc_utils._delete_data_collection_by_id(joined, env.owner))

        assert env.joins() == []
        assert "joined_demo_phys" not in env.tags()
        assert env.dc_doc(env.demo) is not None and env.dc_doc(env.phys) is not None
        # A later change of a source no longer writes it back.
        env.append(env.demo, _new_individuals(8))
        assert "joined_demo_phys" not in env.tags()
        assert env.db["deltatables"].find_one({"data_collection_id": joined}) is None or not any(
            a["rows_total"] == 7 for a in env.aggregations(joined)
        )

    def test_a_joined_table_another_join_reads_cannot_be_deleted(self, env, joined):
        islands = env.add_table("islands", island_info())
        env.create_ok(name="outer", left_dc_id=joined, right_dc_id=islands, on_columns=["island"])
        with pytest.raises(HTTPException) as caught:
            asyncio.run(dc_utils._delete_data_collection_by_id(joined, env.owner))
        assert caught.value.status_code == 409
        assert "outer" in caught.value.detail

    def test_only_an_owner_deletes_a_collection(self, env, joined):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(dc_utils._delete_data_collection_by_id(joined, env.editor))
        assert caught.value.status_code == 404
        assert len(env.joins()) == 1


class TestDeleteJoin:
    def test_the_join_its_table_and_its_records_go_and_the_sources_stay(self, env, joined):
        sizes = (env.read(env.demo).height, env.read(env.phys).height)

        response = env.request(env.owner, "DELETE", "/demo_phys")

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "name": "demo_phys",
            "data_collection_id": joined,
        }
        assert env.joins() == []
        assert env.dc_doc(joined) is None
        assert env.tags() == ["demographic_data", "physical_features"]
        assert env.aggregations(joined) == []
        assert env.db["deltatables"].count_documents({}) == 0
        assert env.cleaned == [joined]  # its Delta files are deleted by the route
        assert (env.read(env.demo).height, env.read(env.phys).height) == sizes

    def test_an_unknown_join_is_404(self, env):
        response = env.request(env.owner, "DELETE", "/nothing")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "unknown_join"

    def test_the_name_and_the_tag_are_free_again(self, env, joined):
        env.request(env.owner, "DELETE", "/demo_phys")
        again = env.create()
        assert again.status_code == 200
        # The same table id: a dashboard left reading it reads it again.
        assert again.json()["data_collection_id"] == joined
        assert env.read(joined).height == 6

    def test_a_join_without_a_result_is_removed_alone(self, env):
        env.db["projects"].update_one(
            {"_id": env.project_oid},
            {
                "$push": {
                    "joins": {
                        "name": "half_made",
                        "left_dc": "demographic_data",
                        "right_dc": "physical_features",
                        "on_columns": ["individual_id"],
                        "how": "left",
                    }
                }
            },
        )
        response = env.request(env.owner, "DELETE", "/half_made")
        assert response.status_code == 200
        assert response.json()["data_collection_id"] is None
        assert env.joins() == []
        assert env.cleaned == []


class TestRename:
    def _rename(self, env, dc_id: str, name: str) -> None:
        asyncio.run(dc_utils._update_data_collection_name(dc_id, name, env.owner))

    def test_renaming_the_left_source_keeps_the_join_pointed_at_it(self, env, joined):
        self._rename(env, env.demo, "demographics")

        assert env.join("demo_phys")["left_dc"] == "demographics"
        assert env.join("demo_phys")["right_dc"] == "physical_features"
        (entry,) = env.request(env.owner, "GET", "").json()["joins"]
        assert entry["left_dc_id"] == env.demo
        assert entry["left_tag"] == "demographics"
        # ... and the join still follows it.
        env.append(env.demo, _new_individuals(8))
        assert env.read(joined).height == 7
        assert env.join("demo_phys")["last_error"] is None

    def test_renaming_the_right_source_keeps_the_join_pointed_at_it(self, env, joined):
        self._rename(env, env.phys, "measurements")

        assert env.join("demo_phys")["right_dc"] == "measurements"
        assert env.join("demo_phys")["left_dc"] == "demographic_data"
        env.append(env.phys, _measures(6))
        assert _by_id(env.read(joined))[6]["bill_length_mm"] == 46.0

    def test_renaming_both_sources(self, env, joined):
        self._rename(env, env.demo, "demographics")
        self._rename(env, env.phys, "measurements")
        stored = env.join("demo_phys")
        assert (stored["left_dc"], stored["right_dc"]) == ("demographics", "measurements")
        (entry,) = env.request(env.owner, "GET", "").json()["joins"]
        assert (entry["left_dc_id"], entry["right_dc_id"]) == (env.demo, env.phys)

    def test_a_new_name_shared_with_another_table_is_scoped_by_workflow(self, env, joined):
        env.add_table("demographics", island_info())  # another workflow, same future tag

        self._rename(env, env.demo, "demographics")

        left = env.join("demo_phys")["left_dc"]
        assert left == f"{env.workflow_of(env.demo)['name']}.demographics"
        (entry,) = env.request(env.owner, "GET", "").json()["joins"]
        assert entry["left_dc_id"] == env.demo

    def test_renaming_an_unrelated_table_leaves_the_join_alone(self, env, joined):
        other = env.add_table("islands", island_info())
        before = env.join("demo_phys")
        self._rename(env, other, "archipelago")
        assert env.join("demo_phys") == before

    def test_renaming_the_joined_table_keeps_its_join(self, env, joined):
        self._rename(env, joined, "penguins_all")
        assert env.dc_doc(joined)["data_collection_tag"] == "penguins_all"
        assert [j["name"] for j in env.joins()] == ["demo_phys"]
        env.append(env.demo, _new_individuals(8))
        assert env.read(joined).height == 7

    def test_renaming_the_source_of_a_chain(self, env, joined):
        islands = env.add_table("islands", island_info())
        env.create_ok(name="outer", left_dc_id=joined, right_dc_id=islands, on_columns=["island"])
        self._rename(env, joined, "penguins_all")
        assert env.join("outer")["left_dc"] == "penguins_all"
        env.append(env.demo, _new_individuals(8))
        outer = env.join("outer")["result_dc_id"]
        assert env.read(str(outer)).height == 7
