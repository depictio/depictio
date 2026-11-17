"""Which links are proposed for a table, from the values it shares."""

from depictio.api.v1.endpoints.links_endpoints.routes import _suggestions_for_source

SOURCE = {"id": "s", "tag": "samples"}


def table(tag: str, **columns: set[str]) -> dict:
    return {"id": tag, "tag": tag, "type": "table", "columns": columns}


def test_a_table_is_linked_on_the_column_that_holds_the_values():
    found = _suggestions_for_source(
        SOURCE,
        {"sample": {"a", "b", "c"}, "note": {"x", "y"}},
        [table("counts", sample_id={"a", "b", "c", "d"}, other={"z"})],
    )

    assert [(s.source_column, s.target_field, s.resolver) for s in found] == [
        ("sample", "sample_id", "direct")
    ]
    assert (found[0].matched, found[0].total) == (3, 3)


def test_a_multiqc_target_is_matched_on_its_samples():
    target = {"id": "m", "tag": "qc", "type": "multiqc", "mappings": {"a": [], "b": []}}

    found = _suggestions_for_source(SOURCE, {"sample": {"a", "b"}}, [target])

    assert [(s.target_type, s.resolver, s.target_field) for s in found] == [
        ("multiqc", "sample_mapping", None)
    ]


def test_a_coincidence_is_not_proposed():
    one_value = table("one", c={"a"})
    mostly_absent = table("few", c={"a", "b"})

    found = _suggestions_for_source(
        SOURCE, {"sample": {"a", "b", "c", "d", "e"}}, [one_value, mostly_absent]
    )

    assert found == []


def test_the_best_targets_come_first_and_are_capped():
    targets = [table(f"t{i}", c={"a", "b"}) for i in range(7)]
    targets.append(table("full", c={"a", "b", "c"}))

    found = _suggestions_for_source(SOURCE, {"sample": {"a", "b", "c"}}, targets)

    assert len(found) == 5
    assert found[0].target_dc_tag == "full"


def test_a_multiqc_report_is_not_crowded_out_by_derived_tables():
    targets = [table(f"t{i}", c={"a", "b"}) for i in range(7)]
    targets.append({"id": "m", "tag": "z_qc", "type": "multiqc", "mappings": {"a": [], "b": []}})

    found = _suggestions_for_source(SOURCE, {"sample": {"a", "b"}}, targets)

    assert found[0].target_dc_tag == "z_qc"


def test_examples_show_what_the_link_reaches_and_what_it_misses():
    found = _suggestions_for_source(
        SOURCE, {"sample": {"a", "b", "c", "lost"}}, [table("counts", c={"a", "b", "c"})]
    )

    assert [(e.source, e.targets) for e in found[0].examples] == [
        ("a", ["a"]),
        ("b", ["b"]),
        ("c", ["c"]),
        ("lost", []),
    ]
