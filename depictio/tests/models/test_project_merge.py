"""A CLI save must not delete what the browser added, and vice versa."""

from depictio.models.project_merge import (
    merge_project_data_collections,
    merge_project_workflows,
)


def _wf(wf_id: str, *dc_ids: str) -> dict:
    return {
        "_id": wf_id,
        "workflow_tag": f"wf-{wf_id}",
        "data_collections": [{"_id": dc, "data_collection_tag": f"dc-{dc}"} for dc in dc_ids],
    }


class TestMergeProjectWorkflows:
    def test_workflow_absent_from_the_payload_survives(self):
        """The bug this module exists for.

        The browser pushes a synthetic workflow per uploaded data collection.
        The CLI then round-trips a project.yaml that has never heard of it.
        """
        stored = [_wf("cli-1"), _wf("browser-1")]
        incoming = [_wf("cli-1")]

        merged = merge_project_workflows(stored, incoming)

        assert [wf["_id"] for wf in merged] == ["cli-1", "browser-1"]

    def test_payload_wins_for_a_workflow_it_does_mention(self):
        stored = [{"_id": "wf-1", "workflow_tag": "old", "data_collections": []}]
        incoming = [{"_id": "wf-1", "workflow_tag": "new", "data_collections": []}]

        assert merge_project_workflows(stored, incoming)[0]["workflow_tag"] == "new"

    def test_new_workflows_are_added(self):
        merged = merge_project_workflows([_wf("a")], [_wf("a"), _wf("b")])

        assert [wf["_id"] for wf in merged] == ["a", "b"]

    def test_payload_order_is_kept_and_preserved_entries_are_appended(self):
        """A CLI-driven reordering still takes effect."""
        stored = [_wf("a"), _wf("keep"), _wf("b")]
        incoming = [_wf("b"), _wf("a")]

        merged = merge_project_workflows(stored, incoming)

        assert [wf["_id"] for wf in merged] == ["b", "a", "keep"]

    def test_data_collections_merge_inside_a_matched_workflow(self):
        """Defensive: browser uploads make their own workflow today, but the
        rule has to hold at both levels or it is not a rule."""
        stored = [_wf("wf-1", "cli-dc", "browser-dc")]
        incoming = [_wf("wf-1", "cli-dc")]

        merged = merge_project_workflows(stored, incoming)

        assert [dc["_id"] for dc in merged[0]["data_collections"]] == ["cli-dc", "browser-dc"]

    def test_the_incoming_payload_is_not_mutated(self):
        incoming = [_wf("wf-1", "cli-dc")]

        merge_project_workflows([_wf("wf-1", "cli-dc", "browser-dc")], incoming)

        assert [dc["_id"] for dc in incoming[0]["data_collections"]] == ["cli-dc"]

    def test_empty_payload_keeps_everything(self):
        stored = [_wf("a"), _wf("b")]

        assert [wf["_id"] for wf in merge_project_workflows(stored, [])] == ["a", "b"]

    def test_none_on_either_side(self):
        assert merge_project_workflows(None, None) == []
        assert [wf["_id"] for wf in merge_project_workflows(None, [_wf("a")])] == ["a"]
        assert [wf["_id"] for wf in merge_project_workflows([_wf("a")], None)] == ["a"]

    def test_stored_entries_without_an_id_are_dropped_rather_than_duplicated(self):
        """An id-less stored entry cannot be matched, so keeping it would
        re-add a copy on every single save."""
        stored = [{"workflow_tag": "no-id", "data_collections": []}]

        assert merge_project_workflows(stored, [_wf("a")]) == [_wf("a")]

    def test_objectid_and_string_ids_compare_equal(self):
        from bson import ObjectId

        oid = ObjectId()
        stored = [{"_id": oid, "workflow_tag": "stored", "data_collections": []}]
        incoming = [{"_id": str(oid), "workflow_tag": "incoming", "data_collections": []}]

        merged = merge_project_workflows(stored, incoming)

        assert len(merged) == 1
        assert merged[0]["workflow_tag"] == "incoming"


class TestMergeProjectDataCollections:
    def test_top_level_data_collection_absent_from_the_payload_survives(self):
        stored = [{"_id": "a"}, {"_id": "kept"}]

        merged = merge_project_data_collections(stored, [{"_id": "a"}])

        assert [dc["_id"] for dc in merged] == ["a", "kept"]

    def test_none_on_either_side(self):
        assert merge_project_data_collections(None, None) == []
