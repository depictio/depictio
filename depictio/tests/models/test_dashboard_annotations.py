"""Caps and shape of the session annotations a viewer stores on a dashboard."""

import pytest
from pydantic import ValidationError

from depictio.models.models.dashboard_annotations import (
    MAX_ANNOTATION_COLUMNS,
    MAX_ANNOTATION_KEYS,
    MAX_LABEL_LENGTH,
    DashboardAnnotationsPayload,
)

DC = "646b0f3c1e4a2d7f5c8e9a01"


def _col(cid, name, values=None, **extra):
    return {
        "id": cid,
        "name": name,
        "dcId": DC,
        "keyColumn": "sample",
        "values": values or {},
        **extra,
    }


def _payload(**overrides):
    body = {
        "version": 2,
        "columns": [_col("c1", "response", {"S1": "responder"})],
        "activeColumnId": "c1",
    }
    body.update(overrides)
    return body


def test_round_trips_in_the_client_shape():
    model = DashboardAnnotationsPayload.model_validate(_payload())
    assert model.columns[0].key_column == "sample"
    assert model.model_dump(by_alias=True) == _payload()


def test_unknown_field_is_refused():
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(extra=True))


def test_unknown_column_field_is_refused():
    cols = [_col("c1", "r", color="red")]
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(columns=cols))


def test_only_version_two():
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(version=1))


def test_a_column_names_its_table_and_key():
    for missing in ("dcId", "keyColumn"):
        col = _col("c1", "r")
        del col[missing]
        with pytest.raises(ValidationError):
            DashboardAnnotationsPayload.model_validate(_payload(columns=[col]))


def test_active_column_may_name_a_shared_column():
    """A reader compares by a column shared on the dashboard, which is not in
    their own labels."""
    model = DashboardAnnotationsPayload.model_validate(_payload(activeColumnId="shared-1"))
    assert model.active_column_id == "shared-1"
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(activeColumnId="x" * 65))


def test_shared_labels_payload_caps():
    from depictio.models.models.dashboard_annotations import SharedLabelsPayload

    ok = SharedLabelsPayload.model_validate({"columns": [_col("c1", "r")]})
    assert ok.columns[0].key_column
    with pytest.raises(ValidationError):
        SharedLabelsPayload.model_validate({"columns": [_col("c1", "r"), _col("c2", "r")]})
    with pytest.raises(ValidationError):
        SharedLabelsPayload.model_validate({"columns": [_col("c1", "r")], "extra": 1})


def test_no_active_column_is_fine():
    model = DashboardAnnotationsPayload.model_validate(_payload(activeColumnId=None))
    assert model.active_column_id is None


def test_column_ids_and_names_unique():
    dup_id = [_col("c1", "a"), _col("c1", "b")]
    dup_name = [_col("c1", "a"), _col("c2", "a")]
    for cols in (dup_id, dup_name):
        with pytest.raises(ValidationError):
            DashboardAnnotationsPayload.model_validate(_payload(columns=cols, activeColumnId=None))


def test_column_cap():
    cols = [_col(f"c{i}", f"n{i}") for i in range(MAX_ANNOTATION_COLUMNS + 1)]
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(columns=cols, activeColumnId=None))


def test_key_cap():
    values = {f"S{i}": "x" for i in range(MAX_ANNOTATION_KEYS + 1)}
    cols = [_col("c1", "r", values)]
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(columns=cols))


def test_label_cap_is_the_group_name_cap():
    from depictio.api.v1.services.figure.groups import MAX_NAME_LENGTH

    assert MAX_LABEL_LENGTH == MAX_NAME_LENGTH
    ok = [_col("c1", "r", {"S1": "x" * MAX_LABEL_LENGTH})]
    DashboardAnnotationsPayload.model_validate(_payload(columns=ok))
    long = [_col("c1", "r", {"S1": "x" * (MAX_LABEL_LENGTH + 1)})]
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(columns=long))


def test_total_size_cap():
    # 20 columns x 10,000 keys of long keys and labels: within the per-field caps, over 1 MB.
    values = {f"{'k' * 40}{i}": "y" * MAX_LABEL_LENGTH for i in range(MAX_ANNOTATION_KEYS)}
    cols = [_col("c1", "r", values)]
    with pytest.raises(ValidationError, match="too large"):
        DashboardAnnotationsPayload.model_validate(_payload(columns=cols))
