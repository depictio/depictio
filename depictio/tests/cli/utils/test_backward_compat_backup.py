"""Backward-compatibility guard for backup/restore.

A backup produced by an older Depictio release must still validate against the
*current* Pydantic models, otherwise restoring it on a freshly upgraded
deployment would silently drop documents (restore is destructive:
``delete_many`` then ``insert_many``).

These tests load real, frozen backup fixtures committed under
``depictio/tests/fixtures/backups/`` and validate every document against the
current models via :func:`validate_backup_file` — the exact same code path the
``backup validate`` CLI command and the API ``/backup/validate`` endpoint use.

Supported-version policy: **v1.0.0 onwards only.** 1.0.0 is the clean baseline
(Dash -> React migration complete); pre-1.0.0 backups are explicitly out of
scope. See ``depictio/tests/fixtures/backups/README.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient
from pymongo.asynchronous.database import AsyncDatabase

from depictio.cli.cli.utils.backup_validation import (
    check_backup_collections_coverage,
    validate_backup_file,
)
from depictio.models.models.users import GroupBeanie, UserBeanie

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "backups"


def _fixture_files() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("depictio_backup_v*.json"))


async def _init_beanie() -> None:
    """Initialise Beanie so Document models (e.g. ``GroupBeanie``) can be built.

    ``validate_backup_file`` instantiates ``GroupBeanie`` for the ``groups``
    collection, which requires an initialised collection. We use an in-memory
    mongomock client exactly like the user-endpoint test suite does.
    """
    client = AsyncMongoMockClient()
    await init_beanie(
        database=cast(AsyncDatabase, client.test_db),
        document_models=[UserBeanie, GroupBeanie],
    )


def test_backup_fixtures_present() -> None:
    """Guard against an empty fixtures directory silently passing every test."""
    fixtures = _fixture_files()
    assert fixtures, (
        f"No backup fixtures found in {FIXTURES_DIR}. "
        "At least the current-version baseline fixture must be committed."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fixture_path",
    _fixture_files(),
    ids=lambda p: p.stem,
)
async def test_old_backup_validates_against_current_models(fixture_path: Path) -> None:
    """Every committed (>= v1.0.0) backup must validate against current models."""
    await _init_beanie()

    result = validate_backup_file(str(fixture_path))

    assert result["valid"], (
        f"Backup fixture {fixture_path.name} no longer validates against the "
        f"current Pydantic models — a backward-incompatible schema change was "
        f"introduced. Offending documents:\n  " + "\n  ".join(result["errors"][:20])
    )
    assert result["invalid_documents"] == 0
    # The fixture must actually exercise the validators, not be an empty shell.
    assert result["valid_documents"] > 0


@pytest.mark.asyncio
async def test_backup_collections_coverage() -> None:
    """A new MongoDB collection must not be added without backup coverage.

    Mirrors the coverage gate run server-side; fails loudly if a collection is
    added to settings but not to the backup validators / expected list.
    """
    await _init_beanie()

    coverage = check_backup_collections_coverage()

    # ``check_backup_collections_coverage`` reads the API settings singleton to
    # enumerate live collections. When the API layer isn't importable (e.g. a
    # CLI-only environment), it returns an ``error`` key — that is an infra
    # limitation, not a real coverage gap, so skip rather than fail.
    if coverage.get("error"):
        pytest.skip(f"API settings unavailable, cannot check coverage: {coverage['error']}")

    assert coverage["valid"], (
        "Backup collection coverage gap detected. "
        f"Missing from expected list: {coverage.get('missing_from_expected')}; "
        f"missing validators: {coverage.get('missing_validators')}; "
        f"errors: {coverage.get('errors')}"
    )
