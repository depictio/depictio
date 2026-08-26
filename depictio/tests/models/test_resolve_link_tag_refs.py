"""Read-time resolution of template ``tag:`` link placeholders.

A project ingested with ``--skip-sync`` keeps its links pointing at
``tag:<dc_tag>`` placeholders; every consumer that matches links on real DC
ids must see them resolved against the project's own data collections.
"""

from depictio.models.models.links import resolve_link_tag_refs


def _project(links):
    return {
        "links": links,
        "workflows": [
            {
                "data_collections": [
                    {"data_collection_tag": "metadata", "_id": "65a000000000000000000001"},
                    {"data_collection_tag": "taxonomy_rel_abundance", "id": "65a000000000000000000002"},
                ]
            }
        ],
    }


def test_tag_placeholders_resolve_to_dc_ids():
    project = _project(
        [
            {
                "source_dc_id": "tag:metadata",
                "source_dc_tag": "metadata",
                "target_dc_id": "tag:taxonomy_rel_abundance",
                "target_dc_tag": "taxonomy_rel_abundance",
            }
        ]
    )
    resolve_link_tag_refs(project)
    link = project["links"][0]
    assert link["source_dc_id"] == "65a000000000000000000001"
    # ``id`` (already-serialised doc) works as well as Mongo's ``_id``.
    assert link["target_dc_id"] == "65a000000000000000000002"


def test_empty_id_with_tag_resolves():
    project = _project([{"source_dc_id": "", "source_dc_tag": "metadata", "target_dc_id": "x"}])
    resolve_link_tag_refs(project)
    assert project["links"][0]["source_dc_id"] == "65a000000000000000000001"


def test_resolved_ids_left_untouched():
    links = [{"source_dc_id": "abc", "target_dc_id": "def", "source_dc_tag": "metadata"}]
    project = _project(links)
    resolve_link_tag_refs(project)
    assert project["links"][0]["source_dc_id"] == "abc"
    assert project["links"][0]["target_dc_id"] == "def"


def test_unknown_tag_left_untouched():
    project = _project([{"source_dc_id": "tag:nope", "source_dc_tag": "nope", "target_dc_id": "x"}])
    resolve_link_tag_refs(project)
    assert project["links"][0]["source_dc_id"] == "tag:nope"


def test_no_links_is_a_noop():
    assert resolve_link_tag_refs({"links": []}) == {"links": []}
