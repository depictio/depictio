"""The ingestion instance filter matches what the admin pane shows for a run.

A run shows the CLI's ``instance_label``, else its hostname. Most CLI configs set
no label, so filtering on the label alone matched no run and left the pane's
instance select empty.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import mongomock
import pytest

from depictio.api.v1.monitoring import store


@pytest.fixture
def runs():
    collection = mongomock.MongoClient().db.ingestion_runs
    started = datetime(2026, 9, 14, 12, 0, 0)
    collection.insert_many(
        [
            {"run_id": "labelled", "cli_instance_label": "lab", "cli_hostname": "login1"},
            {"run_id": "host-only", "cli_hostname": "login1"},
            {"run_id": "null-label", "cli_instance_label": None, "cli_hostname": "laptop"},
            {"run_id": "empty-label", "cli_instance_label": "", "cli_hostname": "laptop"},
        ]
    )
    collection.update_many({}, {"$set": {"started_at": started, "status": "success"}})
    with patch.object(store, "ingestion_runs_collection", collection):
        yield collection


def _ids(**filters) -> list[str]:
    return sorted(r["run_id"] for r in store.query_ingestion_runs(**filters))


def test_a_label_matches_the_runs_that_carry_it(runs):
    assert _ids(instance="lab") == ["labelled"]


def test_a_hostname_matches_runs_without_a_label(runs):
    assert _ids(instance="laptop") == ["empty-label", "null-label"]


def test_a_labelled_run_is_not_matched_by_its_hostname(runs):
    # It shows its label, so picking the hostname must not pull it in.
    assert _ids(instance="login1") == ["host-only"]


def test_the_instance_filter_combines_with_status(runs):
    assert _ids(instance="laptop", status="failed") == []
