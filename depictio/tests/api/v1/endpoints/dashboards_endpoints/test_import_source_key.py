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
- a save from the viewer can neither drop nor copy the key.
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
    database = mongomock.MongoClient()["depictio_test"]
    with (
        patch.object(dash_routes, "dashboards_collection", database["dashboards"]),
        patch.object(dash_routes, "projects_collection", database["projects"]),
        patch.object(dash_routes, "_should_enqueue_screenshot", return_value=False),
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
