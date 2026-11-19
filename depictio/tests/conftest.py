"""Shared pytest fixtures for the Depictio test suite.

Sets safe defaults for the security-hardening env vars introduced in PR1
so existing tests that import ``depictio.api.v1.configs.config`` keep
working without each test having to wire ``DEPICTIO_S3_ROOT_PASSWORD``
and ``DEPICTIO_BOOTSTRAP_*`` itself.

Production deployments set these via their .env / Helm Secret; tests
inherit whatever is already in the env, which is empty in CI runners.
"""

from __future__ import annotations

import os

import pytest

# Defaults applied BEFORE any depictio module imports happen, so the
# Settings() singleton in depictio.api.v1.configs.config doesn't fail-fast
# on a clean CI runner.
_PYTEST_DEFAULTS = {
    "DEPICTIO_CONTEXT": "server",
    # 32-char dev-only password — passes the >=16 length check and isn't on
    # the well-known weak list. Never reuse outside the test suite.
    "DEPICTIO_S3_ROOT_PASSWORD": "pytest_s3_password_aaaaaaaaaaaaa",
    "DEPICTIO_BOOTSTRAP_ADMIN_EMAIL": "admin@example.com",
    "DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD": "pytest_admin_password_aaaaaaaaaa",
    "DEPICTIO_BOOTSTRAP_SEED_TEST_USER": "true",
    "DEPICTIO_BOOTSTRAP_TEST_USER_PASSWORD": "test_pwd",
    # Forced off so a test that boots the app lifespan never starts the release
    # check, which would call api.github.com. Tests of the check itself patch
    # `settings.version_check.enabled`.
    "DEPICTIO_VERSION_CHECK_ENABLED": "false",
}

for _k, _v in _PYTEST_DEFAULTS.items():
    os.environ.setdefault(_k, _v)


# beanie >= 2.1 passes list_collection_names(nameOnly=True, authorizedCollections=True)
# during init_beanie; mongomock 4.3.0 / mongomock-motor 0.0.36 accept neither kwarg.
# Both are no-ops against a mock (privilege filtering and a projection hint), so drop
# them before delegating. Remove once mongomock supports the kwargs upstream.
import mongomock.database  # noqa: E402

_orig_list_collection_names = mongomock.database.Database.list_collection_names


def _list_collection_names_shim(self, filter=None, session=None, **kwargs):
    kwargs.pop("nameOnly", None)
    kwargs.pop("authorizedCollections", None)
    return _orig_list_collection_names(self, filter=filter, session=session, **kwargs)


mongomock.database.Database.list_collection_names = _list_collection_names_shim


@pytest.fixture(scope="session")
def viralrecon_like_run(tmp_path_factory):
    """A small run shaped like nf-core/viralrecon's output, built on the fly.

    The real run (24 MB MultiQC report, mosdepth tables) is no longer vendored: git keeps
    every version of a big file for good. The MultiQC report is the synthetic one of the
    catalog conformance project; the genome coverage table is three samples of windows.
    """
    import shutil
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    report = (
        repo
        / "depictio/projects/init/catalog_conformance/run_1/multiqc/multiqc_data/multiqc.parquet"
    )
    run = tmp_path_factory.mktemp("viralrecon_like") / "run_1"
    mqc = run / "multiqc" / "multiqc_data"
    mqc.mkdir(parents=True)
    shutil.copy(report, mqc / "multiqc.parquet")
    genome = run / "variants" / "bowtie2" / "mosdepth" / "genome"
    genome.mkdir(parents=True)
    rows = ["chrom\tstart\tend\tcoverage\tsample"]
    for sample in ("SAMPLE_01", "SAMPLE_02", "SAMPLE_03"):
        for i in range(10):
            rows.append(f"MN908947.3\t{i * 200}\t{(i + 1) * 200}\t{1000 + 37 * i}.5\t{sample}")
    (genome / "all_samples.mosdepth.coverage.tsv").write_text("\n".join(rows) + "\n")
    return run
