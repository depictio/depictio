"""Export of an advanced viz's extra data collections: ids become tags.

A dashboard saved or ingested by a local stack can hold a viz config's
`<x>_dc_id` / `<x>_wf_id` as ObjectIds. The multi-tab export dumped them as
JSON and failed (`Unable to serialize unknown type: ObjectId`), and nothing
turned them into the tags the import resolves.
"""

from bson import ObjectId

from depictio.models.yaml_serialization.utils import enrich_component_config_dc_tags

WF_ID = ObjectId()
TREE_DC = ObjectId()
META_DC = ObjectId()


class _Projects:
    """The one collection call the enrichment makes: `find()` over projects."""

    def find(self):
        return [
            {
                "workflows": [
                    {
                        "_id": WF_ID,
                        "data_collections": [
                            {"_id": TREE_DC, "data_collection_tag": "tree"},
                            {"_id": META_DC, "data_collection_tag": "tree_meta"},
                        ],
                    }
                ]
            }
        ]


def _phylogeny(**config):
    return {
        "component_type": "advanced_viz",
        "viz_kind": "phylogenetic",
        "config": {"viz_kind": "phylogenetic", **config},
    }


def test_object_ids_become_strings_and_tags_are_added():
    comp = _phylogeny(
        tree_wf_id=WF_ID,
        tree_dc_id=TREE_DC,
        metadata_wf_id=WF_ID,
        metadata_dc_id=META_DC,
    )

    enrich_component_config_dc_tags(comp, {}, _Projects())

    cfg = comp["config"]
    assert cfg["tree_dc_id"] == str(TREE_DC)
    assert cfg["tree_wf_id"] == str(WF_ID)
    assert cfg["tree_dc_tag"] == "tree"
    assert cfg["metadata_dc_tag"] == "tree_meta"


def test_an_existing_tag_is_kept():
    comp = _phylogeny(tree_wf_id=str(WF_ID), tree_dc_id=str(TREE_DC), tree_dc_tag="mine")

    enrich_component_config_dc_tags(comp, {}, _Projects())

    assert comp["config"]["tree_dc_tag"] == "mine"


def test_a_viz_without_a_tag_field_gets_no_tag():
    # complex_heatmap's matrix_dc_id is deprecated and has no matrix_dc_tag; its
    # config forbids unknown keys, so adding one would break the import.
    comp = {
        "component_type": "advanced_viz",
        "viz_kind": "complex_heatmap",
        "config": {
            "viz_kind": "complex_heatmap",
            "matrix_wf_id": WF_ID,
            "matrix_dc_id": TREE_DC,
        },
    }

    enrich_component_config_dc_tags(comp, {}, _Projects())

    assert comp["config"]["matrix_dc_id"] == str(TREE_DC)
    assert "matrix_dc_tag" not in comp["config"]


def test_an_unknown_collection_leaves_the_id_without_a_tag():
    comp = _phylogeny(tree_wf_id=WF_ID, tree_dc_id=ObjectId())

    enrich_component_config_dc_tags(comp, {}, _Projects())

    assert "tree_dc_tag" not in comp["config"]
    assert isinstance(comp["config"]["tree_dc_id"], str)


def test_a_component_without_a_config_is_left_alone():
    comp = {"component_type": "figure"}

    enrich_component_config_dc_tags(comp, {}, _Projects())

    assert comp == {"component_type": "figure"}
