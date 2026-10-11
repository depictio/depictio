"""The rule, the files and the recipe of each row of a POST /projects/from_run report.

A dry run of the shipped ``nf-core/ampliseq/2.16.0`` template against the
megatest-shaped fixture (``depictio/tests/cli/s3_stubs.py``), read back as the
JSON the viewer receives. No network, nothing created.
"""

import json

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.projects_endpoints import from_run
from depictio.models.models.users import UserBase
from depictio.tests.cli.s3_stubs import (
    MEGATEST_TREE,
    S3_BUCKET,
    S3_KEY_PREFIX,
    S3_ROOT,
    install_s3_listing,
)

TEMPLATE_ID = "nf-core/ampliseq/2.16.0"


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    """Server context, the megatest bucket public, local folders off."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS", raising=False)
    monkeypatch.delenv("DEPICTIO_AUTH_SINGLE_USER_MODE", raising=False)
    monkeypatch.delenv("DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS", raising=False)
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", S3_BUCKET)


@pytest.fixture()
def report_json(monkeypatch) -> dict[str, dict]:
    """The rows of a dry run's report, by tag, as JSON."""
    install_s3_listing(monkeypatch, MEGATEST_TREE, key_prefix=S3_KEY_PREFIX)
    projects = mongomock.MongoClient()["depictio_test"]["projects"]
    monkeypatch.setattr(from_run, "projects_collection", projects)
    report = from_run._create_project_from_run(
        data_root=S3_ROOT,
        template_id=TEMPLATE_ID,
        current_user=UserBase(id=ObjectId(), email="owner@example.com", is_admin=False),
        dry_run=True,
    )
    assert projects.count_documents({}) == 0
    body = json.loads(report.model_dump_json())
    return {row["data_collection_tag"]: row for row in body["data_collections"]}


def test_a_scan_row_carries_its_rule_and_the_files_it_matched(report_json):
    row = report_json["multiqc_data"]
    assert (row["kind"], row["status"], row["matched"]) == ("scan", "ok", 1)
    assert row["rule"]
    assert row["samples"] == [f"{S3_ROOT}/multiqc/multiqc_data/multiqc.parquet"]
    assert row["found_in"] == "multiqc/multiqc_data"
    assert row["recipe"] is None


def test_a_recipe_row_carries_its_recipe_and_each_source(report_json):
    row = report_json["taxonomy_composition"]
    assert (row["kind"], row["status"], row["rule"]) == ("recipe", "ok", None)
    recipe = row["recipe"]
    assert recipe["name"] == "qiime2/taxonomy_composition.py"
    assert recipe["summary"]
    found = [source for source in recipe["sources"] if source["kind"] == "file" and source["found"]]
    assert found
    assert found[0]["samples"] == [f"{S3_ROOT}/qiime2/barplot/level-2.csv"]
    assert set(found[0]) == {
        "ref",
        "kind",
        "pattern",
        "dc_ref",
        "optional",
        "matched",
        "samples",
        "found",
        "found_in",
    }
    assert found[0]["found_in"] == "qiime2/barplot"


def test_a_missing_file_source_is_named_with_its_pattern(report_json):
    row = report_json["alpha_rarefaction"]
    assert row["status"] == "missing"
    missing = [
        source
        for source in row["recipe"]["sources"]
        if source["kind"] == "file" and not source["found"] and not source["optional"]
    ]
    assert [source["pattern"] for source in missing] == row["missing_sources"]
    assert all(source["samples"] == [] for source in missing)


def test_a_source_read_from_another_collection_says_which(report_json):
    sources = report_json["upset_canonical"]["recipe"]["sources"]
    assert [(s["kind"], s["dc_ref"], s["optional"]) for s in sources] == [
        ("collection", "taxonomy_rel_abundance", False),
        ("collection", "metadata", True),
    ]
    # taxonomy_rel_abundance finds nothing in this fixture; metadata does.
    assert [(s["found"], s["pattern"]) for s in sources] == [(False, None), (True, None)]
