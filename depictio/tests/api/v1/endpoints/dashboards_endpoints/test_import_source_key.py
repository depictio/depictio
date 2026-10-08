"""The real YAML/JSON import routes, against mongomock collections.

Covers:
- a refresh finds the dashboard it made by `source_key`, so a rename (in the
  viewer, or by `--dashboard-name`) updates it in place instead of adding a
  second family;
- the title fallback, which also gives a key to dashboards imported before keys;
- `keep_titles`: a refresh keeps the titles given in the viewer, and `main_title`
  (`--dashboard-name`) still titles the main dashboard; a child tab file finds a
  renamed parent by `parent_source_key`;
- a project id that does not exist is a 404, not an orphan dashboard;
- an exported image dashboard imports again (it used to fail with a 500);
- a save from the viewer can neither drop nor copy the key;
- `existing=keep` (`ingest --update-config`): a dashboard the project has is left
  as edited in the viewer, `main_title` only renames it, a missing one is created,
  a kept multi-tab family gains the tabs it lacks; `existing=replace` is
  `overwrite`, and every response says which it was;
- what a match can be: a main dashboard only a main one, a tab only a tab of its
  parent, and by title only a dashboard without a key;
- `overwrite` deletes the family tabs the YAML no longer holds, not the tabs added
  in the viewer; `existing=keep` deletes none.
- every import is versioned: the state it replaces when no version holds it
  yet, then the state it made, one pair per family.
"""

import asyncio
from unittest.mock import patch

import mongomock
import pytest
import yaml
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.models.models.base import PyObjectId
from depictio.models.models.dashboards import DashboardData, DashboardDataLite
from depictio.models.models.users import Permission, UserBase

KEY = "nf-core/rnaseq:dashboards/base.yaml"


@pytest.fixture
def user():
    u = UserBase(id=ObjectId(), email="owner@example.com")
    u.is_admin = True
    u.is_anonymous = False
    return u


@pytest.fixture
def db(user):
    from depictio.api.v1.endpoints.dashboards_endpoints import version_store, versioning

    database = mongomock.MongoClient()["depictio_test"]
    # Imports and saves record versions; without these the capture reaches for
    # the real Mongo and waits out its server-selection timeout on every call.
    with (
        patch.object(dash_routes, "dashboards_collection", database["dashboards"]),
        patch.object(dash_routes, "projects_collection", database["projects"]),
        patch.object(dash_routes, "_should_enqueue_screenshot", return_value=False),
        patch.object(dash_routes, "delete_threads_for_dashboards", return_value=0),
        patch.object(versioning, "dashboards_collection", database["dashboards"]),
        patch.object(versioning, "deltatables_collection", database["deltatables"]),
        patch.object(
            version_store, "dashboard_versions_collection", database["dashboard_versions"]
        ),
        patch.object(
            version_store,
            "dashboard_version_counters_collection",
            database["dashboard_version_counters"],
        ),
    ):
        yield database


@pytest.fixture
def project_id(db, user):
    pid = ObjectId()
    db["projects"].insert_one(
        {
            "_id": pid,
            "name": "Images",
            "is_public": False,
            "permissions": {
                "owners": [{"_id": ObjectId(user.id), "email": user.email}],
                "editors": [],
                "viewers": [],
            },
            "workflows": [
                {
                    "_id": ObjectId(),
                    "name": "image_workflow",
                    "engine": {"name": "python"},
                    "data_collections": [
                        {
                            "_id": ObjectId(),
                            "data_collection_tag": "image_table",
                            "config": {
                                "type": "image",
                                "dc_specific_properties": {
                                    "s3_base_folder": "s3://depictio-bucket/images/",
                                    "image_column": "image_path",
                                },
                            },
                        }
                    ],
                }
            ],
        }
    )
    return pid


def _import(
    content,
    user,
    project_id=None,
    overwrite=False,
    source_key=None,
    keep_titles=False,
    main_title=None,
    parent_source_key=None,
    existing=None,
):
    return asyncio.run(
        dash_routes.import_dashboard_from_yaml(
            yaml_content=content,
            project_id=PyObjectId(project_id) if project_id else None,
            overwrite=overwrite,
            source_key=source_key,
            keep_titles=keep_titles,
            main_title=main_title,
            parent_source_key=parent_source_key,
            existing=existing,
            current_user=user,
        )
    )


def _single(title):
    return yaml.safe_dump({"title": title, "components": []})


def _child(title, parent):
    return yaml.safe_dump(
        {"title": title, "is_main_tab": False, "parent_dashboard_tag": parent, "components": []}
    )


def _multi(main_title, tab_titles):
    return yaml.safe_dump(
        {
            "main_dashboard": {"title": main_title, "components": []},
            "tabs": [{"title": t, "components": []} for t in tab_titles],
        }
    )


def _ids(db):
    return sorted(str(d["dashboard_id"]) for d in db["dashboards"].find())


class TestSourceKeyMatching:
    def test_renamed_title_refreshes_the_same_dashboard(self, db, user, project_id):
        first = _import(_single("RNA-seq"), user, project_id, source_key=KEY)

        # `--dashboard-name Renamed`: same file, new title.
        second = _import(_single("Renamed"), user, project_id, overwrite=True, source_key=KEY)

        assert second["updated"] is True
        assert second["dashboard_id"] == first["dashboard_id"]
        assert db["dashboards"].count_documents({}) == 1
        assert db["dashboards"].find_one()["title"] == "Renamed"

    def test_dashboard_renamed_in_the_viewer_is_refreshed_in_place(self, db, user, project_id):
        first = _import(_single("RNA-seq"), user, project_id, source_key=KEY)
        db["dashboards"].update_one({}, {"$set": {"title": "My study"}})

        second = _import(_single("RNA-seq"), user, project_id, overwrite=True, source_key=KEY)

        assert second["dashboard_id"] == first["dashboard_id"]
        assert db["dashboards"].count_documents({}) == 1

    def test_dashboard_imported_before_keys_adopts_one_by_title(self, db, user, project_id):
        legacy = _import(_single("RNA-seq"), user, project_id)
        assert db["dashboards"].find_one()["source_key"] is None

        refreshed = _import(_single("RNA-seq"), user, project_id, overwrite=True, source_key=KEY)

        assert refreshed["dashboard_id"] == legacy["dashboard_id"]
        assert db["dashboards"].find_one()["source_key"] == KEY

    def test_import_without_a_key_keeps_the_stored_one(self, db, user, project_id):
        _import(_single("RNA-seq"), user, project_id, source_key=KEY)

        _import(_single("RNA-seq"), user, project_id, overwrite=True)

        assert db["dashboards"].find_one()["source_key"] == KEY

    def test_same_key_without_overwrite_is_a_conflict_naming_the_dashboard(
        self, db, user, project_id
    ):
        _import(_single("RNA-seq"), user, project_id, source_key=KEY)
        db["dashboards"].update_one({}, {"$set": {"title": "My study"}})

        with pytest.raises(HTTPException) as exc:
            _import(_single("RNA-seq"), user, project_id, source_key=KEY)

        assert exc.value.status_code == 409
        assert "My study" in exc.value.detail
        assert db["dashboards"].count_documents({}) == 1

    def test_same_title_without_overwrite_is_still_a_conflict(self, db, user, project_id):
        _import(_single("RNA-seq"), user, project_id, source_key=KEY)

        with pytest.raises(HTTPException) as exc:
            _import(_single("RNA-seq"), user, project_id, source_key="file:other.yaml")

        assert exc.value.status_code == 409

    def test_multi_tab_family_survives_renames(self, db, user, project_id):
        first = _import(_multi("RNA-seq", ["QC", "Expression"]), user, project_id, source_key=KEY)
        before = _ids(db)
        assert len(before) == 3
        keys = {d["title"]: d["source_key"] for d in db["dashboards"].find()}
        assert keys == {"RNA-seq": KEY, "QC": f"{KEY}#QC", "Expression": f"{KEY}#Expression"}

        # A tab renamed in the viewer, then a refresh that renames the main one.
        db["dashboards"].update_one({"title": "QC"}, {"$set": {"title": "Quality"}})
        second = _import(
            _multi("Renamed", ["QC", "Expression"]),
            user,
            project_id,
            overwrite=True,
            source_key=KEY,
        )

        assert second["dashboard_id"] == first["dashboard_id"]
        assert _ids(db) == before
        main = db["dashboards"].find_one({"is_main_tab": True})
        assert main["title"] == "Renamed"
        tabs = list(db["dashboards"].find({"is_main_tab": False}))
        assert {t["parent_dashboard_id"] for t in tabs} == {main["dashboard_id"]}
        assert sorted(t["title"] for t in tabs) == ["Expression", "QC"]

    def test_overwrite_removes_the_tabs_the_yaml_no_longer_holds(self, db, user, project_id):
        _import(
            _multi("RNA-seq", ["QC", "Expression", "Splicing"]), user, project_id, source_key=KEY
        )
        main = db["dashboards"].find_one({"is_main_tab": True})
        # A tab added in the viewer has no key from this YAML.
        db["dashboards"].insert_one(
            {
                "_id": ObjectId(),
                "dashboard_id": ObjectId(),
                "title": "My notes",
                "is_main_tab": False,
                "parent_dashboard_id": main["dashboard_id"],
                "source_key": None,
            }
        )

        # The template renames "QC" and drops "Splicing".
        _import(
            _multi("RNA-seq", ["Quality", "Expression"]),
            user,
            project_id,
            overwrite=True,
            source_key=KEY,
        )

        tabs = {t["title"]: t["source_key"] for t in db["dashboards"].find({"is_main_tab": False})}
        assert tabs == {
            "Quality": f"{KEY}#Quality",
            "Expression": f"{KEY}#Expression",
            "My notes": None,
        }

    def test_keep_leaves_the_tabs_the_yaml_no_longer_holds(self, db, user, project_id):
        _import(_multi("RNA-seq", ["QC", "Splicing"]), user, project_id, source_key=KEY)

        _import(_multi("RNA-seq", ["QC"]), user, project_id, source_key=KEY, existing="keep")

        titles = sorted(t["title"] for t in db["dashboards"].find({"is_main_tab": False}))
        assert titles == ["QC", "Splicing"]


def _rename(db, title, new_title):
    """What a rename in the viewer does: only the stored title changes."""
    db["dashboards"].update_one({"title": title}, {"$set": {"title": new_title}})


def _titles(db):
    return {str(d["dashboard_id"]): d["title"] for d in db["dashboards"].find()}


class TestKeepTitles:
    """`ingest --update-config` sends keep_titles; only --dashboard-name renames."""

    MAIN_KEY = "file:dashboards/main.yaml"
    TAB_KEY = "file:dashboards/tab.yaml"

    def _refresh(self, content, user, project_id, **kwargs):
        return _import(content, user, project_id, overwrite=True, keep_titles=True, **kwargs)

    def test_main_renamed_in_the_viewer_keeps_its_title(self, db, user, project_id):
        first = _import(_single("RNA-seq overview"), user, project_id, source_key=KEY)
        _rename(db, "RNA-seq overview", "Projet Dupont : RNA-seq")

        second = self._refresh(_single("RNA-seq overview"), user, project_id, source_key=KEY)

        assert second["dashboard_id"] == first["dashboard_id"]
        assert second["title"] == "Projet Dupont : RNA-seq"
        assert _titles(db) == {first["dashboard_id"]: "Projet Dupont : RNA-seq"}

    def test_multi_tab_main_and_tab_renamed_in_the_viewer_keep_their_titles(
        self, db, user, project_id
    ):
        _import(_multi("RNA-seq overview", ["QC", "Expression"]), user, project_id, source_key=KEY)
        _rename(db, "RNA-seq overview", "Projet Dupont : RNA-seq")
        _rename(db, "QC", "Quality")
        before = _titles(db)

        result = self._refresh(
            _multi("RNA-seq overview", ["QC", "Expression"]), user, project_id, source_key=KEY
        )

        assert _titles(db) == before
        assert result["title"] == "Projet Dupont : RNA-seq"
        assert sorted(t["title"] for t in result["tabs"]) == ["Expression", "Quality"]

    def test_main_title_renames_the_main_and_the_tabs_keep_theirs(self, db, user, project_id):
        first = _import(
            _multi("RNA-seq overview", ["QC", "Expression"]), user, project_id, source_key=KEY
        )
        _rename(db, "RNA-seq overview", "Projet Dupont : RNA-seq")
        _rename(db, "QC", "Quality")
        ids = sorted(_titles(db))

        # --dashboard-name New: the CLI also writes it into the YAML.
        self._refresh(
            _multi("New", ["QC", "Expression"]),
            user,
            project_id,
            source_key=KEY,
            main_title="New",
        )

        assert sorted(_titles(db)) == ids
        main = db["dashboards"].find_one({"is_main_tab": True})
        assert main["dashboard_id"] == ObjectId(first["dashboard_id"])
        assert main["title"] == "New"
        tabs = db["dashboards"].find({"is_main_tab": False})
        assert sorted(t["title"] for t in tabs) == ["Expression", "Quality"]

    def test_main_title_renames_a_single_dashboard(self, db, user, project_id):
        first = _import(_single("RNA-seq overview"), user, project_id, source_key=KEY)
        _rename(db, "RNA-seq overview", "Projet Dupont : RNA-seq")

        second = self._refresh(_single("New"), user, project_id, source_key=KEY, main_title="New")

        assert _titles(db) == {first["dashboard_id"]: "New"}
        assert second["title"] == "New"

    def test_main_title_on_a_child_tab_is_a_400(self, db, user, project_id):
        _import(_single("Main"), user, project_id)

        with pytest.raises(HTTPException) as exc:
            _import(_child("Tab", "Main"), user, project_id, main_title="New")

        assert exc.value.status_code == 400
        assert db["dashboards"].count_documents({}) == 1

    def _main_and_child(self, user, project_id):
        main = _import(_single("Main"), user, project_id, source_key=self.MAIN_KEY)
        tab = _import(
            _child("Tab", "Main"),
            user,
            project_id,
            source_key=self.TAB_KEY,
            parent_source_key=self.MAIN_KEY,
        )
        return main["dashboard_id"], tab["dashboard_id"]

    def test_child_tab_file_keeps_its_title_and_its_renamed_parent(self, db, user, project_id):
        main_id, tab_id = self._main_and_child(user, project_id)
        _rename(db, "Main", "My study")
        _rename(db, "Tab", "My tab")

        self._refresh(_single("Main"), user, project_id, source_key=self.MAIN_KEY)
        self._refresh(
            _child("Tab", "Main"),
            user,
            project_id,
            source_key=self.TAB_KEY,
            parent_source_key=self.MAIN_KEY,
        )

        assert _titles(db) == {main_id: "My study", tab_id: "My tab"}
        tab = db["dashboards"].find_one({"dashboard_id": ObjectId(tab_id)})
        assert tab["parent_dashboard_id"] == ObjectId(main_id)

    def test_main_title_reaches_the_child_tab_file_by_key(self, db, user, project_id):
        main_id, tab_id = self._main_and_child(user, project_id)
        _rename(db, "Tab", "My tab")

        # --dashboard-name New re-points the child file's parent_dashboard_tag too.
        self._refresh(_single("New"), user, project_id, source_key=self.MAIN_KEY, main_title="New")
        self._refresh(
            _child("Tab", "New"),
            user,
            project_id,
            source_key=self.TAB_KEY,
            parent_source_key=self.MAIN_KEY,
        )

        assert _titles(db) == {main_id: "New", tab_id: "My tab"}
        tab = db["dashboards"].find_one({"dashboard_id": ObjectId(tab_id)})
        assert tab["parent_dashboard_id"] == ObjectId(main_id)

    def test_refreshed_child_stays_under_its_renamed_parent_without_a_parent_key(
        self, db, user, project_id
    ):
        main_id, tab_id = self._main_and_child(user, project_id)
        _rename(db, "Main", "My study")

        self._refresh(_child("Tab", "Main"), user, project_id, source_key=self.TAB_KEY)

        tab = db["dashboards"].find_one({"dashboard_id": ObjectId(tab_id)})
        assert tab["parent_dashboard_id"] == ObjectId(main_id)

    def test_new_child_tab_finds_a_renamed_parent_by_its_key(self, db, user, project_id):
        main = _import(_single("Main"), user, project_id, source_key=self.MAIN_KEY)
        _rename(db, "Main", "My study")

        with pytest.raises(HTTPException) as exc:
            self._refresh(_child("Tab", "Main"), user, project_id, source_key=self.TAB_KEY)
        assert exc.value.status_code == 400

        tab = self._refresh(
            _child("Tab", "Main"),
            user,
            project_id,
            source_key=self.TAB_KEY,
            parent_source_key=self.MAIN_KEY,
        )

        stored = db["dashboards"].find_one({"dashboard_id": ObjectId(tab["dashboard_id"])})
        assert stored["parent_dashboard_id"] == ObjectId(main["dashboard_id"])
        assert stored["title"] == "Tab"

    @pytest.mark.parametrize("keep_titles", [False, True])
    def test_first_import_takes_the_yaml_titles(self, db, user, project_id, keep_titles):
        _import(
            _multi("Main", ["QC"]),
            user,
            project_id,
            overwrite=True,
            source_key=KEY,
            keep_titles=keep_titles,
        )

        assert sorted(_titles(db).values()) == ["Main", "QC"]

    def test_without_keep_titles_the_yaml_titles_come_back(self, db, user, project_id):
        _import(_multi("Overview", ["QC"]), user, project_id, source_key=KEY)
        main_id, tab_id = self._main_and_child(user, project_id)
        for title in ("Overview", "QC", "Main", "Tab"):
            _rename(db, title, f"My {title}")

        _import(_multi("Overview", ["QC"]), user, project_id, overwrite=True, source_key=KEY)
        _import(_single("Main"), user, project_id, overwrite=True, source_key=self.MAIN_KEY)
        _import(
            _child("Tab", "Main"),
            user,
            project_id,
            overwrite=True,
            source_key=self.TAB_KEY,
            parent_source_key=self.MAIN_KEY,
        )

        assert sorted(_titles(db).values()) == ["Main", "Overview", "QC", "Tab"]
        assert _titles(db)[main_id] == "Main"
        tab = db["dashboards"].find_one({"dashboard_id": ObjectId(tab_id)})
        assert tab["title"] == "Tab"
        assert tab["parent_dashboard_id"] == ObjectId(main_id)


def _edit(db, title):
    """What a save from the viewer does to a dashboard: its layout and components change."""
    db["dashboards"].update_one(
        {"title": title},
        {
            "$set": {
                "stored_metadata": [{"index": "edited", "component_type": "text"}],
                "left_panel_layout_data": [{"i": "edited", "x": 0, "y": 0, "w": 4, "h": 2}],
            }
        },
    )
    return db["dashboards"].find_one({"title": title})


class TestExistingKeep:
    """`ingest` sends existing=keep (with overwrite, which an older server reads
    instead): a refresh leaves the dashboards edited in the viewer as they are."""

    MAIN_KEY = "file:dashboards/main.yaml"
    TAB_KEY = "file:dashboards/tab.yaml"

    def _keep(self, content, user, project_id, **kwargs):
        return _import(
            content,
            user,
            project_id,
            overwrite=True,
            keep_titles=True,
            existing="keep",
            **kwargs,
        )

    def test_an_edited_dashboard_is_left_as_it_is(self, db, user, project_id):
        first = _import(_single("RNA-seq"), user, project_id, source_key=KEY)
        before = _edit(db, "RNA-seq")

        result = self._keep(_single("RNA-seq"), user, project_id, source_key=KEY)

        assert result["status"] == "kept"
        assert result["updated"] is False
        assert result["dashboard_id"] == first["dashboard_id"]
        assert db["dashboards"].find_one() == before

    def test_it_is_found_by_its_key_once_renamed_in_the_viewer(self, db, user, project_id):
        first = _import(_single("RNA-seq"), user, project_id, source_key=KEY)
        _rename(db, "RNA-seq", "My study")
        before = _edit(db, "My study")

        result = self._keep(_single("RNA-seq"), user, project_id, source_key=KEY)

        assert (result["status"], result["title"]) == ("kept", "My study")
        assert result["dashboard_id"] == first["dashboard_id"]
        assert list(db["dashboards"].find()) == [before]

    def test_a_dashboard_the_project_lacks_is_created(self, db, user, project_id):
        _import(_single("RNA-seq"), user, project_id, source_key=KEY)

        result = self._keep(_single("QC"), user, project_id, source_key="file:qc.yaml")

        assert result["status"] == "created"
        assert sorted(_titles(db).values()) == ["QC", "RNA-seq"]

    def test_main_title_only_renames_a_kept_dashboard(self, db, user, project_id):
        _import(_single("RNA-seq"), user, project_id, source_key=KEY)
        before = _edit(db, "RNA-seq")

        result = self._keep(_single("New"), user, project_id, source_key=KEY, main_title="New")

        assert (result["status"], result["title"]) == ("kept", "New")
        assert db["dashboards"].find_one() == {**before, "title": "New"}

    def test_a_dashboard_imported_before_keys_is_kept_and_takes_one(self, db, user, project_id):
        legacy = _import(_single("RNA-seq"), user, project_id)

        result = self._keep(_single("RNA-seq"), user, project_id, source_key=KEY)

        assert (result["status"], result["dashboard_id"]) == ("kept", legacy["dashboard_id"])
        assert db["dashboards"].find_one()["source_key"] == KEY

    def test_a_kept_multi_tab_family_keeps_its_tabs_and_gains_those_it_lacks(
        self, db, user, project_id
    ):
        first = _import(_multi("RNA-seq", ["QC", "Expression"]), user, project_id, source_key=KEY)
        # Edited in the viewer: a tab renamed and edited, a tab removed, the main edited.
        _rename(db, "QC", "Quality")
        _edit(db, "Quality")
        db["dashboards"].delete_one({"title": "Expression"})
        _edit(db, "RNA-seq")
        before = list(db["dashboards"].find())

        result = self._keep(
            _multi("RNA-seq", ["QC", "Expression", "New tab"]), user, project_id, source_key=KEY
        )

        assert (result["status"], result["dashboard_id"]) == ("kept", first["dashboard_id"])
        assert result["tabs_added"] == 2
        # The removed tab comes back, as a single-file tab does; both after the last one.
        assert [tab["title"] for tab in result["tabs"]] == ["Quality", "Expression", "New tab"]
        for doc in before:
            assert db["dashboards"].find_one({"_id": doc["_id"]}) == doc
        added = {d["title"]: d for d in db["dashboards"].find({"title": {"$ne": "Quality"}})}
        main = added.pop("RNA-seq")
        assert {t["tab_order"] for t in added.values()} == {2, 3}
        assert added["Expression"]["tab_order"] < added["New tab"]["tab_order"]
        for title, tab in added.items():
            assert tab["parent_dashboard_id"] == main["dashboard_id"]
            assert tab["source_key"] == f"{KEY}#{title}"

    def test_a_kept_multi_tab_family_with_every_tab_adds_none(self, db, user, project_id):
        _import(_multi("RNA-seq", ["QC", "Expression"]), user, project_id, source_key=KEY)
        before = list(db["dashboards"].find())

        result = self._keep(
            _multi("RNA-seq", ["QC", "Expression"]), user, project_id, source_key=KEY
        )

        assert (result["status"], result["tabs_added"]) == ("kept", 0)
        assert result["message"] == "Dashboard kept as it is"
        assert list(db["dashboards"].find()) == before

    def test_a_tab_imported_before_keys_is_kept_and_takes_its_key(self, db, user, project_id):
        _import(_multi("RNA-seq", ["QC"]), user, project_id)
        tab_before = _edit(db, "QC")

        result = self._keep(_multi("RNA-seq", ["QC"]), user, project_id, source_key=KEY)

        assert result["tabs_added"] == 0
        assert db["dashboards"].find_one({"title": "QC"}) == {
            **tab_before,
            "source_key": f"{KEY}#QC",
        }

    def test_a_tab_pruned_at_the_first_import_comes_in_once_its_data_does(
        self, db, user, project_id
    ):
        """A kept nf-core family gains the tab an attached run brings the data for."""
        gallery = {
            "title": "Gallery",
            "components": [
                {
                    "tag": "qc-gallery",
                    "component_type": "image",
                    "workflow_tag": "python/image_workflow",
                    "data_collection_tag": "qc_images",
                    "image_column": "image_path",
                }
            ],
        }
        content = yaml.safe_dump(
            {
                "main_dashboard": {"title": "RNA-seq", "components": []},
                "tabs": [{"title": "QC", "components": []}, gallery],
            }
        )
        first = self._keep(content, user, project_id, source_key=KEY)
        # Its only component has no data collection yet: the tab is left out.
        assert [tab["title"] for tab in first["tabs"]] == ["QC"]

        self._keep(content, user, project_id, source_key=KEY)
        assert db["dashboards"].count_documents({"title": "Gallery"}) == 0

        db["projects"].update_one(
            {"_id": project_id},
            {
                "$push": {
                    "workflows.0.data_collections": {
                        "_id": ObjectId(),
                        "data_collection_tag": "qc_images",
                        "config": {
                            "type": "image",
                            "dc_specific_properties": {
                                "s3_base_folder": "s3://depictio-bucket/qc/",
                                "image_column": "image_path",
                            },
                        },
                    }
                }
            },
        )
        result = self._keep(content, user, project_id, source_key=KEY)

        assert (result["status"], result["tabs_added"]) == ("kept", 1)
        assert [tab["title"] for tab in result["tabs"]] == ["QC", "Gallery"]

    def test_a_multi_tab_family_the_project_lacks_is_created_whole(self, db, user, project_id):
        result = self._keep(
            _multi("RNA-seq", ["QC", "Expression"]), user, project_id, source_key=KEY
        )

        assert result["status"] == "created"
        assert sorted(t["title"] for t in result["tabs"]) == ["Expression", "QC"]
        assert db["dashboards"].count_documents({}) == 3

    def test_a_kept_child_tab_file_and_a_new_one_under_the_kept_parent(self, db, user, project_id):
        main = _import(_single("Main"), user, project_id, source_key=self.MAIN_KEY)
        _import(
            _child("Tab", "Main"),
            user,
            project_id,
            source_key=self.TAB_KEY,
            parent_source_key=self.MAIN_KEY,
        )
        _rename(db, "Main", "My study")
        tab_before = _edit(db, "Tab")

        kept = self._keep(
            _child("Tab", "Main"),
            user,
            project_id,
            source_key=self.TAB_KEY,
            parent_source_key=self.MAIN_KEY,
        )
        added = self._keep(
            _child("Tab 2", "Main"),
            user,
            project_id,
            source_key="file:dashboards/tab2.yaml",
            parent_source_key=self.MAIN_KEY,
        )

        assert kept["status"] == "kept"
        assert db["dashboards"].find_one({"title": "Tab"}) == tab_before
        assert added["status"] == "created"
        new_tab = db["dashboards"].find_one({"title": "Tab 2"})
        assert new_tab["parent_dashboard_id"] == ObjectId(main["dashboard_id"])

    def test_keep_wins_over_overwrite(self, db, user, project_id):
        _import(_single("RNA-seq"), user, project_id, source_key=KEY)
        before = _edit(db, "RNA-seq")

        result = _import(
            _single("RNA-seq"), user, project_id, overwrite=True, source_key=KEY, existing="keep"
        )

        assert result["status"] == "kept"
        assert db["dashboards"].find_one() == before

    def test_keep_alone_is_not_a_conflict(self, db, user, project_id):
        _import(_single("RNA-seq"), user, project_id, source_key=KEY)

        result = _import(_single("RNA-seq"), user, project_id, source_key=KEY, existing="keep")

        assert result["status"] == "kept"

    def test_replace_is_overwrite(self, db, user, project_id):
        first = _import(_single("RNA-seq"), user, project_id, source_key=KEY)
        _rename(db, "RNA-seq", "My study")
        _edit(db, "My study")

        result = _import(
            _single("RNA-seq"),
            user,
            project_id,
            source_key=KEY,
            keep_titles=True,
            existing="replace",
        )

        assert (result["status"], result["updated"]) == ("replaced", True)
        assert result["dashboard_id"] == first["dashboard_id"]
        stored = db["dashboards"].find_one()
        assert stored["title"] == "My study"
        assert stored["stored_metadata"] == []

    def test_without_existing_the_responses_say_created_and_replaced(self, db, user, project_id):
        created = _import(_multi("RNA-seq", ["QC"]), user, project_id, source_key=KEY)
        replaced = _import(
            _multi("RNA-seq", ["QC"]), user, project_id, overwrite=True, source_key=KEY
        )

        assert (created["status"], replaced["status"]) == ("created", "replaced")
        with pytest.raises(HTTPException) as exc:
            _import(_single("Other"), user, project_id, source_key=KEY)
        assert exc.value.status_code == 409


class TestMatchScope:
    """What an import can take for the dashboard it refreshes: a main dashboard
    only a main one, a tab only one of its parent's, and by title only one
    imported before keys existed."""

    REFRESH = {"overwrite": True, "keep_titles": True}

    @pytest.mark.parametrize("existing", ["keep", "replace"])
    def test_a_main_dashboard_does_not_take_a_tab_of_another_family(
        self, db, user, project_id, existing
    ):
        _import(_multi("Overview", ["QC"]), user, project_id)
        tab = db["dashboards"].find_one({"title": "QC"})

        result = _import(
            _single("QC"),
            user,
            project_id,
            source_key="file:qc.yaml",
            existing=existing,
            **self.REFRESH,
        )

        assert result["status"] == "created"
        assert result["dashboard_id"] != str(tab["dashboard_id"])
        assert db["dashboards"].find_one({"_id": tab["_id"]}) == tab

    def test_a_multi_tab_main_does_not_take_a_tab_of_another_family(self, db, user, project_id):
        _import(_multi("Overview", ["QC"]), user, project_id, source_key="file:a.yaml")
        tab = db["dashboards"].find_one({"title": "QC"})

        result = _import(
            _multi("QC", ["Details"]),
            user,
            project_id,
            source_key="file:b.yaml",
            existing="keep",
            **self.REFRESH,
        )

        assert result["status"] == "created"
        assert db["dashboards"].find_one({"_id": tab["_id"]}) == tab
        assert db["dashboards"].count_documents({"title": "Details"}) == 1

    def test_a_main_dashboard_with_the_title_of_a_tab_is_not_a_conflict(self, db, user, project_id):
        _import(_multi("Overview", ["QC"]), user, project_id)

        result = _import(_single("QC"), user, project_id)

        assert result["status"] == "created"

    @pytest.mark.parametrize("existing", ["keep", "replace"])
    def test_a_child_tab_file_does_not_take_a_tab_of_another_family(
        self, db, user, project_id, existing
    ):
        _import(_multi("Overview", ["QC"]), user, project_id)
        other = db["dashboards"].find_one({"title": "QC"})
        main = _import(_single("Main"), user, project_id, source_key="file:main.yaml")

        result = _import(
            _child("QC", "Main"),
            user,
            project_id,
            source_key="file:qc.yaml",
            parent_source_key="file:main.yaml",
            existing=existing,
            **self.REFRESH,
        )

        assert result["status"] == "created"
        assert db["dashboards"].find_one({"_id": other["_id"]}) == other
        stored = db["dashboards"].find_one({"dashboard_id": ObjectId(result["dashboard_id"])})
        assert stored["parent_dashboard_id"] == ObjectId(main["dashboard_id"])

    def test_a_child_tab_file_takes_a_tab_of_its_parent_imported_before_keys(
        self, db, user, project_id
    ):
        _import(_single("Main"), user, project_id)
        legacy = _import(_child("QC", "Main"), user, project_id)

        result = _import(
            _child("QC", "Main"),
            user,
            project_id,
            source_key="file:qc.yaml",
            existing="keep",
            **self.REFRESH,
        )

        assert (result["status"], result["dashboard_id"]) == ("kept", legacy["dashboard_id"])
        assert db["dashboards"].find_one({"title": "QC"})["source_key"] == "file:qc.yaml"

    @pytest.mark.parametrize("existing", ["keep", "replace"])
    def test_the_title_does_not_take_a_dashboard_keyed_to_another_source(
        self, db, user, project_id, existing
    ):
        first = _import(_single("Overview"), user, project_id, source_key="file:a.yaml")

        result = _import(
            _single("Overview"),
            user,
            project_id,
            source_key="file:b.yaml",
            existing=existing,
            **self.REFRESH,
        )

        assert result["status"] == "created"
        keys = {d["source_key"] for d in db["dashboards"].find()}
        assert keys == {"file:a.yaml", "file:b.yaml"}
        assert (
            db["dashboards"].find_one({"dashboard_id": ObjectId(first["dashboard_id"])})[
                "source_key"
            ]
            == "file:a.yaml"
        )

    def test_a_tab_renamed_to_the_title_of_another_is_not_overwritten_by_it(
        self, db, user, project_id
    ):
        _import(_multi("Main", ["QC"]), user, project_id, source_key=KEY)
        _rename(db, "QC", "Quality")

        _import(_multi("Main", ["QC", "Quality"]), user, project_id, source_key=KEY, **self.REFRESH)

        keys = sorted(d["source_key"] for d in db["dashboards"].find({"is_main_tab": False}))
        assert keys == [f"{KEY}#QC", f"{KEY}#Quality"]

    def test_a_tab_key_is_looked_up_in_its_own_family(self, db, user, project_id):
        _import(_multi("Other", ["QC"]), user, project_id, source_key="file:other.yaml")
        other_main = db["dashboards"].find_one({"title": "Other"})
        other_tab = db["dashboards"].find_one({"title": "QC"})
        # A tab of another family that carries the key a tab of this one gets.
        db["dashboards"].update_one({"_id": other_tab["_id"]}, {"$set": {"source_key": "K#QC"}})
        other_tab = db["dashboards"].find_one({"_id": other_tab["_id"]})

        _import(_multi("Fresh", ["QC"]), user, project_id, source_key="K", existing="replace")

        assert db["dashboards"].find_one({"_id": other_tab["_id"]}) == other_tab
        fresh = db["dashboards"].find_one({"title": "Fresh"})
        assert db["dashboards"].count_documents({"parent_dashboard_id": fresh["dashboard_id"]}) == 1
        assert db["dashboards"].count_documents({"parent_dashboard_id": other_main["_id"]}) == 1


class TestUnknownProject:
    def test_yaml_import_into_a_missing_project_is_a_404(self, db, user):
        with pytest.raises(HTTPException) as exc:
            _import(_single("Orphan"), user, "000000000000000000000000")

        assert exc.value.status_code == 404
        assert "000000000000000000000000 not found" in exc.value.detail
        assert db["dashboards"].count_documents({}) == 0

    def test_multi_tab_import_into_a_missing_project_is_a_404(self, db, user):
        with pytest.raises(HTTPException) as exc:
            _import(_multi("Orphan", ["Tab"]), user, "000000000000000000000000")

        assert exc.value.status_code == 404
        assert db["dashboards"].count_documents({}) == 0

    @pytest.mark.parametrize("project_id", ["000000000000000000000000", "notanid"])
    def test_json_import_into_a_missing_project_is_a_404(self, db, user, project_id):
        content = {"_depictio_export_version": "1.0", "dashboard": {"title": "Orphan"}}
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                dash_routes.import_dashboard_from_json(
                    json_content=content,
                    project_id=project_id,
                    validate_integrity=False,
                    current_user=user,
                )
            )

        assert exc.value.status_code == 404
        assert f"{project_id} not found" in exc.value.detail


class TestImageRoundTrip:
    YAML = yaml.safe_dump(
        {
            "title": "Gallery",
            "components": [
                {
                    "tag": "image-gallery-1",
                    "component_type": "image",
                    "workflow_tag": "python/image_workflow",
                    "data_collection_tag": "image_table",
                    "image_column": "image_path",
                }
            ],
        }
    )

    def test_exported_image_dashboard_imports_again(self, db, user, project_id):
        _import(self.YAML, user, project_id)
        stored = db["dashboards"].find_one()
        assert stored["stored_metadata"][0]["s3_base_folder"] == "s3://depictio-bucket/images/"

        # What GET /{id}/yaml sends: the export leaves s3_base_folder out.
        lite = DashboardDataLite.from_full(stored)
        lite.project_tag = "Images"
        exported = lite.to_yaml()
        assert "s3_base_folder" not in exported

        result = _import(exported, user, project_id, overwrite=True)

        assert result["updated"] is True
        image = db["dashboards"].find_one()["stored_metadata"][0]
        assert image["s3_base_folder"] == "s3://depictio-bucket/images/"


class TestSaveKeepsTheKey:
    def test_save_without_the_key_keeps_it(self, db, user, project_id):
        result = _import(_single("RNA-seq"), user, project_id, source_key=KEY)
        dashboard_id = PyObjectId(result["dashboard_id"])

        asyncio.run(
            dash_routes.save_dashboard(
                dashboard_id=dashboard_id,
                data=DashboardData(
                    dashboard_id=dashboard_id,
                    title="Edited",
                    project_id=project_id,
                    permissions=Permission(owners=[user]),
                ),
                current_user=user,
            )
        )

        stored = db["dashboards"].find_one({"dashboard_id": ObjectId(dashboard_id)})
        assert stored["title"] == "Edited"
        assert stored["source_key"] == KEY

    def test_duplicate_does_not_inherit_the_key(self, db, user, project_id):
        _import(_single("RNA-seq"), user, project_id, source_key=KEY)
        copy_id = PyObjectId()

        # The viewer's duplicate spreads the source document, key included.
        asyncio.run(
            dash_routes.save_dashboard(
                dashboard_id=copy_id,
                data=DashboardData(
                    dashboard_id=copy_id,
                    title="RNA-seq (copy)",
                    project_id=project_id,
                    permissions=Permission(owners=[user]),
                    source_key=KEY,
                ),
                current_user=user,
            )
        )

        copy = db["dashboards"].find_one({"dashboard_id": ObjectId(copy_id)})
        assert copy.get("source_key") is None
        assert db["dashboards"].count_documents({"source_key": KEY}) == 1


def _kinds(db):
    return [v["kind"] for v in db["dashboard_versions"].find().sort("seq", 1)]


def _versions(db):
    return list(db["dashboard_versions"].find().sort("seq", 1))


class TestImportIsVersioned:
    """An import rewrites a family wholesale, so what it replaced must stay restorable."""

    def test_a_first_import_is_the_family_first_version(self, db, user, project_id):
        _import(_single("RNA-seq"), user, project_id, source_key=KEY)

        assert _kinds(db) == ["import"]

    def test_a_reimport_over_hand_edits_records_them_first(self, db, user, project_id):
        _import(_single("RNA-seq"), user, project_id, source_key=KEY)
        _edit(db, "RNA-seq")

        _import(_single("RNA-seq"), user, project_id, overwrite=True, source_key=KEY)

        assert _kinds(db) == ["import", "explicit", "import"]
        edited = _versions(db)[1]["tabs"][0]
        assert edited["stored_metadata"][0]["index"] == "edited"
        assert _versions(db)[2]["tabs"][0]["stored_metadata"] == []

    def test_an_identical_reimport_is_marked_but_not_duplicated_before(self, db, user, project_id):
        _import(_single("RNA-seq"), user, project_id, source_key=KEY)

        _import(_single("RNA-seq"), user, project_id, overwrite=True, source_key=KEY)

        assert _kinds(db) == ["import", "import"]

    def test_a_multi_tab_overwrite_is_one_pair_on_the_main_tab(self, db, user, project_id):
        first = _import(_multi("RNA-seq", ["QC", "Expression"]), user, project_id, source_key=KEY)
        _edit(db, "QC")

        _import(
            _multi("RNA-seq", ["QC", "Expression"]),
            user,
            project_id,
            overwrite=True,
            source_key=KEY,
        )

        assert _kinds(db) == ["import", "explicit", "import"]
        assert {v["family_id"] for v in _versions(db)} == {first["dashboard_id"]}
        assert [v["tab_count"] for v in _versions(db)] == [3, 3, 3]

    def test_keep_with_nothing_to_add_records_nothing(self, db, user, project_id):
        _import(_multi("RNA-seq", ["QC"]), user, project_id, source_key=KEY)
        _edit(db, "QC")

        _import(
            _multi("RNA-seq", ["QC"]),
            user,
            project_id,
            overwrite=True,
            keep_titles=True,
            existing="keep",
            source_key=KEY,
        )

        assert _kinds(db) == ["import"]

    def test_keep_adding_a_tab_records_the_hand_edits_before_it(self, db, user, project_id):
        _import(_multi("RNA-seq", ["QC"]), user, project_id, source_key=KEY)
        _edit(db, "QC")

        _import(
            _multi("RNA-seq", ["QC", "New tab"]),
            user,
            project_id,
            overwrite=True,
            keep_titles=True,
            existing="keep",
            source_key=KEY,
        )

        assert _kinds(db) == ["import", "explicit", "import"]
        assert [v["tab_count"] for v in _versions(db)] == [2, 2, 3]

    def test_a_child_tab_file_is_versioned_with_its_parent(self, db, user, project_id):
        main = _import(_single("RNA-seq"), user, project_id, source_key=KEY)

        _import(_child("QC", "RNA-seq"), user, project_id, source_key="file:qc.yaml")

        versions = _versions(db)
        assert [v["kind"] for v in versions] == ["import", "import"]
        assert {v["family_id"] for v in versions} == {main["dashboard_id"]}
        assert versions[-1]["tab_count"] == 2

    def test_a_json_import_records_only_the_import(self, db, user, project_id):
        content = {"_depictio_export_version": "1.0", "dashboard": {"title": "From JSON"}}

        result = asyncio.run(
            dash_routes.import_dashboard_from_json(
                json_content=content,
                project_id=str(project_id),
                validate_integrity=False,
                current_user=user,
            )
        )

        versions = _versions(db)
        assert [v["kind"] for v in versions] == ["import"]
        assert versions[0]["family_id"] == result["dashboard_id"]
