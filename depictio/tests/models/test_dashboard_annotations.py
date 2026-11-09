"""Caps and shape of the session annotations a viewer stores on a dashboard."""

import pytest
from pydantic import ValidationError

from depictio.models.models.dashboard_annotations import (
    MAX_ANNOTATION_COLUMNS,
    MAX_ANNOTATION_KEYS,
    MAX_LABEL_LENGTH,
    DashboardAnnotationsPayload,
)


def _payload(**overrides):
    body = {
        "version": 1,
        "dcId": "646b0f3c1e4a2d7f5c8e9a01",
        "keyColumn": "sample",
        "columns": [{"id": "c1", "name": "response", "values": {"S1": "responder"}}],
        "activeColumnId": "c1",
    }
    body.update(overrides)
    return body


def test_round_trips_in_the_client_shape():
    model = DashboardAnnotationsPayload.model_validate(_payload())
    assert model.key_column == "sample"
    assert model.model_dump(by_alias=True) == _payload()


def test_unknown_field_is_refused():
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(extra=True))


def test_unknown_column_field_is_refused():
    cols = [{"id": "c1", "name": "r", "values": {}, "color": "red"}]
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(columns=cols))


def test_only_version_one():
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(version=2))


def test_active_column_must_exist():
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(activeColumnId="nope"))


def test_no_active_column_is_fine():
    model = DashboardAnnotationsPayload.model_validate(_payload(activeColumnId=None))
    assert model.active_column_id is None


def test_column_ids_and_names_unique():
    dup_id = [{"id": "c1", "name": "a", "values": {}}, {"id": "c1", "name": "b", "values": {}}]
    dup_name = [{"id": "c1", "name": "a", "values": {}}, {"id": "c2", "name": "a", "values": {}}]
    for cols in (dup_id, dup_name):
        with pytest.raises(ValidationError):
            DashboardAnnotationsPayload.model_validate(_payload(columns=cols, activeColumnId=None))


def test_column_cap():
    cols = [
        {"id": f"c{i}", "name": f"n{i}", "values": {}} for i in range(MAX_ANNOTATION_COLUMNS + 1)
    ]
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(columns=cols, activeColumnId=None))


def test_key_cap():
    values = {f"S{i}": "x" for i in range(MAX_ANNOTATION_KEYS + 1)}
    cols = [{"id": "c1", "name": "r", "values": values}]
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(columns=cols))


def test_label_cap_is_the_group_name_cap():
    from depictio.api.v1.services.figure.groups import MAX_NAME_LENGTH

    assert MAX_LABEL_LENGTH == MAX_NAME_LENGTH
    ok = [{"id": "c1", "name": "r", "values": {"S1": "x" * MAX_LABEL_LENGTH}}]
    DashboardAnnotationsPayload.model_validate(_payload(columns=ok))
    long = [{"id": "c1", "name": "r", "values": {"S1": "x" * (MAX_LABEL_LENGTH + 1)}}]
    with pytest.raises(ValidationError):
        DashboardAnnotationsPayload.model_validate(_payload(columns=long))


def test_total_size_cap():
    # 20 columns x 10,000 keys of long keys and labels: within the per-field caps, over 1 MB.
    values = {f"{'k' * 40}{i}": "y" * MAX_LABEL_LENGTH for i in range(MAX_ANNOTATION_KEYS)}
    cols = [{"id": "c1", "name": "r", "values": values}]
    with pytest.raises(ValidationError, match="too large"):
        DashboardAnnotationsPayload.model_validate(_payload(columns=cols))
