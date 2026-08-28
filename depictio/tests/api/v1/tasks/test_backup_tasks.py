"""Tests for the scheduled MongoDB backup task."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from depictio.api.v1.tasks.backup_tasks import run_scheduled_backup, start_backup_tasks

ROUTES = "depictio.api.v1.endpoints.backup_endpoints.routes"
TASKS = "depictio.api.v1.tasks.backup_tasks"


@pytest.fixture
def backup_settings(tmp_path):
    """Real values for every field the task compares or formats."""
    mock_settings = MagicMock()
    mock_settings.backup.backup_path = str(tmp_path / "backups")
    mock_settings.backup.backup_file_retention_days = 30
    mock_settings.backup.backup_retention_weekly_weeks = 0
    mock_settings.backup.backup_retention_monthly_months = 0
    mock_settings.backup.auto_backup_enabled = True
    mock_settings.backup.auto_backup_interval_hours = 24
    mock_settings.backup.auto_backup_time_of_day = None
    mock_state = MagicMock()
    mock_state.find_one.return_value = None
    with (
        patch(f"{ROUTES}.settings", mock_settings),
        patch(f"{ROUTES}.initialization_collection", mock_state),
    ):
        yield mock_settings


@pytest.mark.asyncio
async def test_skips_when_the_slot_is_not_due(backup_settings, tmp_path):
    with (
        patch(f"{TASKS}.claim_auto_backup_slot", return_value=None),
        patch(f"{TASKS}._create_mongodb_backup", new=AsyncMock()) as mock_create,
    ):
        assert await run_scheduled_backup() is None

    mock_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_skips_while_the_schedule_is_off(backup_settings, tmp_path):
    """The loop runs even when disabled so the UI toggle needs no restart, so
    the enabled check has to happen per tick rather than at startup."""
    backup_settings.backup.auto_backup_enabled = False
    with (
        patch(f"{TASKS}.claim_auto_backup_slot") as mock_claim,
        patch(f"{TASKS}._create_mongodb_backup", new=AsyncMock()) as mock_create,
    ):
        assert await run_scheduled_backup() is None

    # Not even the claim is attempted: a disabled tick must not move the due time.
    mock_claim.assert_not_called()
    mock_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_writes_a_backup_and_its_sidecar_when_due(backup_settings, tmp_path):
    """A scheduled backup has to be a first-class one: same filename, same
    sidecar. Without the sidecar a later restore refuses to run unverified."""
    # A real backup id is minted from "now"; using a fixed past one would be
    # pruned by the retention pass that runs right after the write.
    now_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "backup_metadata": {"backup_id": now_id, "total_documents": 3, "automatic": True},
        "data": {"projects": []},
    }
    with (
        patch(f"{TASKS}.claim_auto_backup_slot", return_value=object()),
        patch(
            f"{TASKS}._create_mongodb_backup", new=AsyncMock(return_value=payload)
        ) as mock_create,
    ):
        backup_id = await run_scheduled_backup()

    assert backup_id == now_id
    # The scheduler identifies itself, and stamps the snapshot as automatic so
    # the admin UI can tell it apart from a hand-made one.
    assert mock_create.await_args.args == ("scheduler",)
    assert mock_create.await_args.kwargs == {"automatic": True}

    backup_dir = tmp_path / "backups"
    written = backup_dir / f"depictio_backup_{now_id}.json"
    assert written.exists()
    assert (backup_dir / f"depictio_backup_{now_id}.json.sha256").exists()
    assert json.loads(written.read_text())["backup_metadata"]["automatic"] is True


@pytest.mark.asyncio
async def test_prunes_after_a_scheduled_backup(backup_settings, tmp_path):
    payload = {
        "backup_metadata": {
            "backup_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "total_documents": 0,
        },
        "data": {},
    }
    with (
        patch(f"{TASKS}.claim_auto_backup_slot", return_value=object()),
        patch(f"{TASKS}._create_mongodb_backup", new=AsyncMock(return_value=payload)),
        patch(f"{TASKS}.prune_expired_backups") as mock_prune,
    ):
        await run_scheduled_backup()

    mock_prune.assert_called_once()


def test_the_loop_starts_even_when_the_schedule_is_off(backup_settings):
    """Starting only when enabled would mean the admin's toggle did nothing
    until someone restarted the API."""
    backup_settings.backup.auto_backup_enabled = False
    with patch(f"{TASKS}.asyncio.create_task") as mock_create_task:
        start_backup_tasks()
    mock_create_task.assert_called_once()
