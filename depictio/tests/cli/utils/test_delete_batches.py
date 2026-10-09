"""Batch deletes of runs and files, and the per-id fallback for an older server.

The count they return is what the scan reports as removed, so it has to say
what was really deleted: neither dropping the chunks already done when a later
one falls back, nor counting a refused chunk as gone.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from depictio.cli.cli.utils.api_calls import _delete_batch_or_fallback, _delete_concurrently

IDS = ["a", "b", "c", "d", "e"]


def _response(status: int, deleted: int = 0) -> MagicMock:
    return MagicMock(status_code=status, text="", json=lambda: {"deleted": deleted})


def _ok(_item, _config) -> MagicMock:
    return MagicMock(status_code=200)


@pytest.fixture
def batch():
    """Run a batch delete of IDS in chunks of two, the server answering ``replies``."""

    def run(*replies, delete_one=_ok):
        logger = MagicMock()
        with (
            patch(
                "depictio.cli.cli.utils.api_calls.request_with_retry",
                MagicMock(side_effect=list(replies)),
            ),
            patch("depictio.cli.cli.utils.api_calls.generate_api_headers", return_value={}),
            patch("depictio.cli.cli.utils.api_calls.logger", logger),
        ):
            deleted = _delete_batch_or_fallback(
                IDS,
                endpoint="runs/delete_batch",
                payload_key="run_ids",
                delete_one=delete_one,
                CLI_config=MagicMock(api_base_url="http://api"),
                concurrency=1,
                chunk_size=2,
            )
        return deleted, logger

    return run


class TestTheFallback:
    @pytest.mark.parametrize(
        "second_reply",
        [_response(404), httpx.ConnectError("connection reset")],
        ids=["no batch endpoint", "transport error"],
    )
    def test_the_chunks_already_deleted_still_count(self, batch, second_reply):
        retried: list[str] = []

        def delete_one(item, config):
            retried.append(item)
            return _ok(item, config)

        deleted, _ = batch(_response(200, deleted=2), second_reply, delete_one=delete_one)

        assert deleted == 5
        # Only what the batch had not already deleted.
        assert retried == ["c", "d", "e"]


class TestARefusedChunk:
    def test_is_counted_as_failed_not_deleted(self, batch):
        deleted, logger = batch(_response(500), _response(200, deleted=2), _response(200, 1))

        assert deleted == 3
        logger.warning.assert_any_call("2 of 5 id(s) could not be deleted via runs/delete_batch.")


class TestPerIdDeletes:
    def test_a_transport_error_on_one_id_does_not_stop_the_others(self):
        def delete_one(item, _config):
            if item == "b":
                raise httpx.ReadTimeout("timed out")
            return MagicMock(status_code=200)

        deleted = _delete_concurrently(["a", "b", "c"], delete_one, MagicMock(), concurrency=1)

        assert deleted == 2

    def test_a_refused_id_is_not_counted(self):
        def delete_one(item, _config):
            return MagicMock(status_code=403 if item == "a" else 200)

        assert _delete_concurrently(["a", "b", "c"], delete_one, MagicMock(), concurrency=3) == 2
