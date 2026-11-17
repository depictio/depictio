"""Storage backends against real stores (#1358). Not in the default test paths.

Each target runs only when its environment says it is there:

- ``gcs``: a GCS emulator, ``DEPICTIO_TEST_GCS_EMULATOR=http://localhost:4443``.
  It must speak the XML API ``object_store`` uses: the ``tustvold/fake-gcs-server``
  image (upstream ``fsouza/fake-gcs-server`` answers PUT with "invalid uploadType").
- ``gcs_public``: anonymous reads of ``gs://gcp-public-data--broad-references``,
  ``DEPICTIO_TEST_GCS_PUBLIC=1`` (needs network).
- ``gcs_live``: a real, private, writable bucket, ``DEPICTIO_TEST_GCS_BUCKET=<name>``
  with Application Default Credentials (or ``GOOGLE_APPLICATION_CREDENTIALS``).

Run: ``uv run --extra dev pytest depictio/tests/storage``.
"""

from __future__ import annotations

import os
import uuid

import pytest

from depictio.api.v1.configs.settings_models import GCSConfig
from depictio.models.storage import GCSBackend

EMULATOR = os.environ.get("DEPICTIO_TEST_GCS_EMULATOR", "").rstrip("/")
LIVE_BUCKET = os.environ.get("DEPICTIO_TEST_GCS_BUCKET", "")
EMULATOR_BUCKET = "depictio-test"


def _emulator_bucket() -> None:
    """Create the emulator's bucket (fake-gcs-server keeps buckets in memory)."""
    import httpx

    httpx.post(f"{EMULATOR}/storage/v1/b", json={"name": EMULATOR_BUCKET}, timeout=10)


def _targets() -> list:
    targets = [
        pytest.param(
            "emulator",
            marks=[
                pytest.mark.gcs,
                pytest.mark.skipif(not EMULATOR, reason="DEPICTIO_TEST_GCS_EMULATOR unset"),
            ],
            id="gcs-emulator",
        ),
        pytest.param(
            "live",
            marks=[
                pytest.mark.gcs_live,
                pytest.mark.skipif(not LIVE_BUCKET, reason="DEPICTIO_TEST_GCS_BUCKET unset"),
            ],
            id="gcs-live",
        ),
    ]
    return targets


@pytest.fixture(params=_targets())
def backend(request) -> GCSBackend:
    """A writable GCS backend, on the emulator or a real bucket."""
    if request.param == "emulator":
        _emulator_bucket()
        return GCSBackend(GCSConfig(bucket=EMULATOR_BUCKET, endpoint_url=EMULATOR))
    return GCSBackend(GCSConfig(bucket=LIVE_BUCKET))


@pytest.fixture
def prefix(backend: GCSBackend):
    """A key prefix of the test's own, emptied afterwards."""
    root = f"depictio-tests/{uuid.uuid4().hex}/"
    yield root
    try:
        backend.delete_prefix(root)
    except Exception:  # noqa: BLE001 - cleanup is best effort
        pass
