"""Anonymous reads of a public GCS bucket through the GCS backend (#1358).

``DEPICTIO_TEST_GCS_PUBLIC=1`` turns it on; it needs network access to
storage.googleapis.com.
"""

from __future__ import annotations

import os

import polars as pl
import pytest

from depictio.api.v1.configs.settings_models import GCSConfig
from depictio.models.storage import GCSBackend

pytestmark = [
    pytest.mark.gcs_public,
    pytest.mark.skipif(
        os.environ.get("DEPICTIO_TEST_GCS_PUBLIC") != "1", reason="DEPICTIO_TEST_GCS_PUBLIC unset"
    ),
]

BUCKET = "gcp-public-data--broad-references"
KEY = "hg38/v0/CrossSpeciesContamination/ContaminantNormalizationFactors.txt"


@pytest.fixture(scope="module")
def public() -> GCSBackend:
    return GCSBackend(GCSConfig(bucket=BUCKET, anonymous=True))


def test_list_and_ranged_read(public):
    listed = [o.key for o in public.list_objects("hg38/v0/CrossSpeciesContamination/")]
    assert KEY in listed
    assert public.read_range(KEY, 0, 4) == b"name"
    info = public.head(KEY)
    assert info is not None and info.size > 0


def test_polars_scans_it_with_the_backends_options(public):
    df = pl.scan_csv(public.url(KEY), separator="\t", storage_options=public.storage_options())
    assert df.collect().columns[:2] == ["name", "tax_id"]
