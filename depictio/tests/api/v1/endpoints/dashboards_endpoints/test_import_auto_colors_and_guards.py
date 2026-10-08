"""What a YAML import resolves and prunes beyond the components' own tags.

- `category_colors: auto` becomes a colour per value of the column's data, a
  re-import keeping the colours values had;
- a text tile's live values get their `dc` tag resolved, and a list item citing
  one the run cannot compute is removed (the tile too when nothing is left);
- a highlight whose source tab or figure did not make it into the family is
  dropped, and its tab re-compacted.

Against mongomock, through the real import route. The column reads (Delta
tables) are monkeypatched.
"""

import asyncio
from unittest.mock import patch

import mongomock
import pytest
import yaml
from bson import ObjectId

from depictio.api.v1.endpoints.dashboards_endpoints import routes as dash_routes
from depictio.models.components.category_palette import CATEGORY_PALETTE as P
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import UserBase

WF_ID = ObjectId()
SAMPLES_DC = ObjectId()
REL_DC = ObjectId()
OTHER_TABLE_DC = ObjectId()


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
        patch.object(dash_routes, "get_project_visibility", return_value=False),
    ):
        yield database


@pytest.fixture
def project_id(db, user):
    pid = ObjectId()
    db["projects"].insert_one(
        {
            "_id": pid,
            "name": "Ampliseq run",
            "permissions": {
                "owners": [{"_id": ObjectId(user.id), "email": user.email}],
                "editors": [],
                "viewers": [],
            },
            "workflows": [
                {
                    "_id": WF_ID,
                    "name": "wf",
                    "engine": {"name": "python"},
                    "data_collections": [
                        {
                            "_id": OTHER_TABLE_DC,
                            "data_collection_tag": "asv_table",
                            "config": {"type": "table"},
                        },
                        {
                            "_id": SAMPLES_DC,
                            "data_collection_tag": "samplesheet",
                            "config": {"type": "table", "metatype": "Metadata"},
                        },
                        {
                            "_id": REL_DC,
                            "data_collection_tag": "rel_abundance",
                            "config": {"type": "table"},
                        },
                    ],
                }
            ],
        }
    )
    return pid


@pytest.fixture
def column_data():
    """The data the column reads see: `{dc_id: {column: [values]}}`, editable per test."""
    data = {
        str(SAMPLES_DC): {"habitat": ["soil", "lake"], "sample": ["S1", "S2"]},
        str(OTHER_TABLE_DC): {"habitat": ["soil", "lake", "x"]},
        str(REL_DC): {"Phylum": ["a", "b"]},
    }
    reads: list[tuple[str, str]] = []

    def names(dc_id):
        return set(data.get(str(dc_id), {})) or None

    def values(dc_id, column):
        reads.append((str(dc_id), column))
        return data.get(str(dc_id), {}).get(column)

    with (
        patch.object(dash_routes, "_dc_column_names", side_effect=names),
        patch.object(dash_routes, "_distinct_column_values", side_effect=values),
    ):
        yield data, reads


def _import(doc: dict, user, project_id, existing=None, source_key="tpl:base.yaml"):
    return asyncio.run(
        dash_routes.import_dashboard_from_yaml(
            yaml_content=yaml.safe_dump(doc, sort_keys=False),
            project_id=PyObjectId(project_id),
            overwrite=False,
            source_key=source_key,
            keep_titles=False,
            main_title=None,
            parent_source_key=None,
            existing=existing,
            current_user=user,
        )
    )


def _interactive(index: str, column: str, dc: str = "samplesheet", **extra) -> dict:
    return {
        "component_type": "interactive",
        "index": index,
        "workflow_tag": "python/wf",
        "data_collection_tag": dc,
        "interactive_component_type": "MultiSelect",
        "column_name": column,
        "column_type": "object",
        **extra,
    }


def _figure(index: str, dc: str = "rel_abundance", title: str = "", **layout) -> dict:
    return {
        "component_type": "figure",
        "index": index,
        "title": title,
        "workflow_tag": "python/wf",
        "data_collection_tag": dc,
        "visu_type": "bar",
        "dict_kwargs": {"x": "Phylum", "y": "abundance"},
        "layout": {"x": 0, "y": 0, "w": 8, "h": 4, **layout},
    }


def _main(db) -> dict:
    return db["dashboards"].find_one({"is_main_tab": True})


# --------------------------------------------------------------------------- #
# category_colors: auto
# --------------------------------------------------------------------------- #


class TestResolveAutoCategoryColors:
    def test_values_of_the_filtered_column_get_palette_slots(self, project_id, column_data):
        dashboard = {
            "category_colors": {"habitat": {"*": "auto"}, "Kingdom": {"B": "#1098ad"}},
            "stored_metadata": [
                {"component_type": "interactive", "column_name": "habitat", "dc_id": SAMPLES_DC}
            ],
        }
        dash_routes._resolve_auto_category_colors(dashboard, project_id)
        assert dashboard["category_colors"] == {
            "habitat": {"lake": P[0], "soil": P[1]},
            "Kingdom": {"B": "#1098ad"},
        }
        assert column_data[1] == [(str(SAMPLES_DC), "habitat")]

    def test_pins_and_previous_colours_hold(self, project_id, column_data):
        dashboard = {
            "category_colors": {"habitat": {"*": "auto", "soil": "#868e96"}},
            "stored_metadata": [],
        }
        column_data[0][str(SAMPLES_DC)]["habitat"] = ["soil", "lake", "marine"]
        dash_routes._resolve_auto_category_colors(
            dashboard, project_id, previous={"habitat": {"marine": P[0]}}
        )
        assert dashboard["category_colors"] == {
            "habitat": {"lake": P[1], "marine": P[0], "soil": "#868e96"}
        }

    def test_without_a_filter_a_metadata_table_is_read_first(self, project_id, column_data):
        dashboard = {"category_colors": {"habitat": {"*": "auto"}}, "stored_metadata": []}
        dash_routes._resolve_auto_category_colors(dashboard, project_id)
        # `asv_table` comes first in the project and has the column too.
        assert column_data[1] == [(str(SAMPLES_DC), "habitat")]

    def test_any_table_holding_the_column_otherwise(self, project_id, column_data):
        dashboard = {"category_colors": {"Phylum": {"*": "auto"}}, "stored_metadata": []}
        dash_routes._resolve_auto_category_colors(dashboard, project_id)
        assert dashboard["category_colors"] == {"Phylum": {"a": P[0], "b": P[1]}}

    def test_a_column_no_table_holds_is_dropped(self, project_id, column_data):
        dashboard = {
            "category_colors": {"nowhere": {"*": "auto", "x": "#000000"}},
            "stored_metadata": [],
        }
        dash_routes._resolve_auto_category_colors(dashboard, project_id)
        assert dashboard["category_colors"] is None


class TestAutoColorsAtImport:
    def _doc(self) -> dict:
        return {
            "main_dashboard": {
                "title": "Run",
                "category_colors": {"habitat": "auto"},
                "components": [_interactive("habitat-filter", "habitat")],
            },
            "tabs": [
                {
                    "title": "Tab",
                    "category_colors": {"sample": "auto"},
                    "components": [_interactive("s", "sample"), _figure("f")],
                }
            ],
        }

    def test_stored_colours_and_no_star(self, db, user, project_id, column_data):
        _import(self._doc(), user, project_id)
        assert _main(db)["category_colors"] == {"habitat": {"lake": P[0], "soil": P[1]}}
        tab = db["dashboards"].find_one({"is_main_tab": False})
        assert tab["category_colors"] == {"sample": {"S1": P[0], "S2": P[1]}}

    def test_a_reimport_keeps_the_colours_values_had(self, db, user, project_id, column_data):
        _import(self._doc(), user, project_id)
        column_data[0][str(SAMPLES_DC)]["habitat"] = ["aquifer", "lake", "soil"]
        _import(self._doc(), user, project_id, existing="replace")
        assert _main(db)["category_colors"] == {
            "habitat": {"aquifer": P[2], "lake": P[0], "soil": P[1]}
        }

    def test_a_child_tab_takes_the_main_tabs_colours_first(self, db, user, project_id, column_data):
        doc = self._doc()
        doc["tabs"][0]["category_colors"] = {"habitat": "auto"}
        doc["tabs"][0]["components"].append(_interactive("h2", "habitat"))
        column_data[0][str(SAMPLES_DC)]["habitat"] = ["soil", "lake"]
        _import(doc, user, project_id)
        tab = db["dashboards"].find_one({"is_main_tab": False})
        assert tab["category_colors"]["habitat"] == _main(db)["category_colors"]["habitat"]


# --------------------------------------------------------------------------- #
# Text tiles' live values
# --------------------------------------------------------------------------- #


def _text_doc(body: str, values: dict, title: str = "") -> dict:
    return {
        "title": "Run",
        "components": [
            _interactive("habitat-filter", "habitat"),
            {
                "component_type": "text",
                "index": "findings",
                "title": title,
                "values": values,
                "body": body,
                "layout": {"x": 0, "y": 0, "w": 4, "h": 3},
            },
            _figure("fig", w=4),
        ],
    }


TOP = {"dc": "rel_abundance", "column": "Phylum", "aggregation": "top"}
GONE = {"dc": "never_ingested", "column": "x", "aggregation": "count"}


def _stored_text(db) -> dict | None:
    return next(
        (c for c in _main(db)["stored_metadata"] if c["component_type"] == "text"),
        None,
    )


class TestTextValuesAtImport:
    def test_tags_resolve_to_ids(self, db, user, project_id, column_data):
        _import(_text_doc("- Dominant: {{top}}", {"top": TOP}), user, project_id)
        spec = _stored_text(db)["values"]["top"]
        # Stored as ObjectIds, as a component's own dc_id / wf_id are.
        assert spec["dc_id"] == REL_DC
        assert spec["wf_id"] == WF_ID

    def test_items_citing_an_absent_value_are_removed(self, db, user, project_id, column_data):
        body = (
            "### Key findings\n"
            "- Dominant: {{top}}\n"
            "- Absent: {{gone}}\n"
            "  its second line\n"
            "1. Also absent {{gone}} and {{top}}\n"
            "A sentence with {{top}}.\n"
        )
        _import(_text_doc(body, {"top": TOP, "gone": GONE}), user, project_id)
        text = _stored_text(db)
        assert text["body"] == "### Key findings\n- Dominant: {{top}}\nA sentence with {{top}}.\n"
        assert set(text["values"]) == {"top"}

    def test_a_tile_left_with_nothing_to_say_is_dropped(self, db, user, project_id, column_data):
        _import(
            _text_doc("### Key findings\n- Absent: {{gone}}\n", {"gone": GONE}), user, project_id
        )
        main = _main(db)
        assert _stored_text(db) is None
        assert "box-findings" not in {item["i"] for item in main["right_panel_layout_data"]}
        # The figure that shared its row is re-packed to the full width.
        fig = next(i for i in main["right_panel_layout_data"] if i["i"] == "box-fig")
        assert fig["w"] == 8

    def test_an_absent_value_in_prose_stays_unresolved(self, db, user, project_id, column_data):
        _import(_text_doc("Absent: {{gone}}", {"gone": GONE}), user, project_id)
        spec = _stored_text(db)["values"]["gone"]
        assert spec["dc_id"] is None and spec["wf_id"] is None

    def test_the_export_carries_no_ids(self, db, user, project_id, column_data):
        from depictio.models.models.dashboards import DashboardDataLite

        _import(_text_doc("- Dominant: {{top}}", {"top": TOP}), user, project_id)
        exported = DashboardDataLite.from_full(_main(db)).to_yaml()
        assert "dc_id" not in exported and str(REL_DC) not in exported
        assert "aggregation: top" in exported


# --------------------------------------------------------------------------- #
# Highlights whose source did not make it
# --------------------------------------------------------------------------- #


def _highlight(index: str, source_tab: str, source_component: str, x: int = 0) -> dict:
    return {
        "component_type": "highlight",
        "index": index,
        "source_tab": source_tab,
        "source_component": source_component,
        "layout": {"x": x, "y": 0, "w": 4, "h": 4},
    }


class TestHighlightPruning:
    def _family(self) -> dict:
        return {
            "main_dashboard": {
                "title": "Run",
                "components": [
                    _interactive("habitat-filter", "habitat"),
                    _highlight("keep-by-index", "Alpha", "alpha-fig"),
                    _highlight("keep-by-title", " alpha ", "ALPHA  diversity", x=4),
                    _highlight("tab-gone", "Not in the YAML", "alpha-fig"),
                    _highlight("figure-gone", "Alpha", "no-such-figure"),
                    _highlight("figure-pruned", "Alpha", "pruned-fig"),
                    _highlight("tab-pruned", "Empty tab", "lonely-fig"),
                ],
            },
            "tabs": [
                {
                    "title": "Alpha",
                    "components": [
                        _interactive("alpha-filter", "habitat"),
                        _figure("alpha-fig", title="Alpha diversity"),
                        _figure("pruned-fig", dc="never_ingested"),
                    ],
                },
                {
                    "title": "Empty tab",
                    "components": [
                        _interactive("e-filter", "habitat"),
                        _figure("lonely-fig", dc="never_ingested"),
                    ],
                },
            ],
        }

    def test_orphans_are_dropped_and_the_tab_recompacted(self, db, user, project_id, column_data):
        _import(self._family(), user, project_id)
        main = _main(db)
        highlights = {
            c["index"] for c in main["stored_metadata"] if c["component_type"] == "highlight"
        }
        assert highlights == {"keep-by-index", "keep-by-title"}
        boxes = {item["i"] for item in main["right_panel_layout_data"]}
        assert boxes == {"box-keep-by-index", "box-keep-by-title"}
        # The skipped tab really was skipped, which is why its highlight went.
        assert db["dashboards"].count_documents({"title": "Empty tab"}) == 0

    def test_a_single_file_import_keeps_a_highlight_whose_tab_may_follow(
        self, db, user, project_id, column_data
    ):
        doc = {
            "title": "Run",
            "components": [
                _interactive("habitat-filter", "habitat"),
                _highlight("later", "A tab imported next", "some-fig"),
                _figure("own-fig"),
                _highlight("own-gone", "Run", "no-such-figure", x=4),
            ],
        }
        _import(doc, user, project_id)
        highlights = {
            c["index"] for c in _main(db)["stored_metadata"] if c["component_type"] == "highlight"
        }
        # The tab is unknown yet; the dashboard itself is known, and lacks the figure.
        assert highlights == {"later"}
