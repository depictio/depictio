"""Which tables a reader may label: metadata tables linked to the data, never joined."""

from depictio.api.v1.endpoints.dashboards_endpoints.annotation_tables import classify_tables
from depictio.api.v1.endpoints.datacollections_endpoints.table_edit import MAX_EDITABLE_ROWS

SHEET, META, STATS, JOINED, LEFT, RIGHT, MQC = (f"64{i:022d}" for i in range(7))


def _dc(dc_id, tag, type_="table", **config):
    return {"_id": dc_id, "data_collection_tag": tag, "config": {"type": type_, **config}}


def _project(**overrides):
    project = {
        "workflows": [
            {
                "name": "ampliseq",
                "data_collections": [
                    _dc(SHEET, "samplesheet"),
                    _dc(META, "metadata", metatype="Metadata"),
                    _dc(STATS, "read_tracking", metatype="Aggregate"),
                    _dc(JOINED, "joined", source="joined"),
                    _dc(LEFT, "left_sheet", metatype="Metadata"),
                    _dc(RIGHT, "right_table"),
                    _dc(MQC, "multiqc_data", type_="multiqc"),
                ],
            }
        ],
        "links": [
            {"source_dc_id": SHEET, "source_column": "sampleID", "target_dc_id": MQC},
            {"source_dc_id": META, "source_column": "sample", "target_dc_id": MQC},
            {"source_dc_id": META, "source_column": "sample", "target_dc_id": STATS},
            {"source_dc_id": STATS, "source_column": "sample", "target_dc_id": MQC},
            {"source_dc_id": JOINED, "source_column": "sample", "target_dc_id": MQC},
            {"source_dc_id": LEFT, "source_column": "sample", "target_dc_id": MQC},
        ],
        "joins": [{"name": "j", "left_dc": "left_sheet", "right_dc": "right_table"}],
    }
    project.update(overrides)
    return project


def _by_tag(project, rows=lambda _dc_id: 10):
    return {t["tag"]: t for t in classify_tables(project, rows)}


def test_samplesheet_without_metatype_and_metadata_sheet_are_eligible():
    tables = _by_tag(_project())
    assert tables["samplesheet"]["eligible"] is True
    assert tables["samplesheet"]["key_columns"] == ["sampleID"]
    assert tables["metadata"]["eligible"] is True
    # One key column even when several links use it.
    assert tables["metadata"]["key_columns"] == ["sample"]


def test_aggregate_table_is_not_metadata():
    assert _by_tag(_project())["read_tracking"]["code"] == "not_metadata"


def test_join_result_and_join_input_are_refused():
    tables = _by_tag(_project())
    assert tables["joined"]["code"] == "derived_table"
    assert tables["left_sheet"]["code"] == "join_input"


def test_join_result_named_by_the_join_is_refused():
    project = _project(
        joins=[{"name": "j", "left_dc": "x", "right_dc": "y", "result_dc_id": SHEET}]
    )
    assert _by_tag(project)["samplesheet"]["code"] == "derived_table"


def test_scoped_join_reference():
    project = _project(joins=[{"name": "j", "left_dc": "ampliseq.samplesheet", "right_dc": "y"}])
    assert _by_tag(project)["samplesheet"]["code"] == "join_input"
    other = _project(joins=[{"name": "j", "left_dc": "other.samplesheet", "right_dc": "y"}])
    assert _by_tag(other)["samplesheet"]["eligible"] is True


def test_table_without_link_is_refused():
    assert _by_tag(_project())["right_table"]["code"] == "join_input"
    project = _project(joins=[])
    assert _by_tag(project)["right_table"]["code"] == "not_linked"


def test_disabled_link_does_not_count():
    links = [{"source_dc_id": SHEET, "source_column": "sampleID", "enabled": False}]
    assert _by_tag(_project(links=links))["samplesheet"]["code"] == "not_linked"


def test_several_key_columns_are_listed():
    links = [
        {"source_dc_id": SHEET, "source_column": "sampleID"},
        {"source_dc_id": SHEET, "source_column": "fastq_1"},
    ]
    assert _by_tag(_project(links=links))["samplesheet"]["key_columns"] == ["sampleID", "fastq_1"]


def test_row_limit():
    rows = {SHEET: MAX_EDITABLE_ROWS, META: MAX_EDITABLE_ROWS + 1}
    tables = _by_tag(_project(), lambda dc_id: rows.get(dc_id, 1))
    assert tables["samplesheet"]["eligible"] is True
    assert tables["metadata"]["code"] == "table_too_large"
    assert str(MAX_EDITABLE_ROWS) in tables["metadata"]["reason"]


def test_unreadable_table_has_no_data():
    assert _by_tag(_project(), lambda _dc_id: None)["samplesheet"]["code"] == "no_data"


def test_rows_are_counted_only_for_candidates():
    asked: list[str] = []

    def rows(dc_id):
        asked.append(dc_id)
        return 1

    classify_tables(_project(), rows)
    assert sorted(asked) == sorted([SHEET, META])


def test_non_tables_are_not_listed():
    assert "multiqc_data" not in _by_tag(_project())
