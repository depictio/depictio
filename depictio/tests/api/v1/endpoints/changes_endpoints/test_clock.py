"""Ingestion records keep the host's local clock; the changes views show UTC."""

from __future__ import annotations

import os
import time
from datetime import datetime

import pytest

from depictio.api.v1.services.changes.clock import local_to_utc, utc_to_local


@pytest.fixture
def paris_host():
    if not hasattr(time, "tzset"):
        pytest.skip("needs time.tzset (POSIX)")
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Paris"
    time.tzset()
    yield
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous
    time.tzset()


def test_a_local_stamp_reads_as_utc(paris_host):
    # 22:11 on a Paris host in November (UTC+1) is 21:11 UTC.
    assert local_to_utc(datetime(2026, 11, 12, 22, 11)) == datetime(2026, 11, 12, 21, 11)
    assert local_to_utc("2026-11-12T22:11:00") == datetime(2026, 11, 12, 21, 11)


def test_a_utc_cursor_queries_local_stamps(paris_host):
    cursor = datetime(2026, 11, 12, 21, 11)
    assert utc_to_local(cursor) == datetime(2026, 11, 12, 22, 11)
    assert local_to_utc(utc_to_local(cursor)) == cursor


def test_other_values_pass_through():
    assert local_to_utc(None) is None
    assert local_to_utc("not a date") == "not a date"
