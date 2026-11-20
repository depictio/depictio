"""The project summary a static bundle ships (``BundleManifest.project``).

A bundle is a file that leaves the instance. The summary behind its project page
is built from an allow-list of the project document, so the tests below feed a
document carrying everything a real one can — ACL, owners' emails, storage
locations, template internals, credentials in run parameters — and assert none
of it comes out, while every display fact does.
"""

from __future__ import annotations

import json
from datetime import datetime

from bson import ObjectId

from depictio.models.models.serverless import BundleManifest, ProjectSummary
from depictio.serverless.project_summary import (
    WITHHELD,
    build_project_summary,
    is_secret_key,
    public_http_url,
    safe_parameter_value,
)

PROJECT_ID = ObjectId()
WF_ID = ObjectId()
DC_TABLE = ObjectId()
DC_MQC = ObjectId()
DC_DIRECT = ObjectId()
LINK_ID = ObjectId()


def _project_doc() -> dict:
    return {
        "_id": PROJECT_ID,
        "name": "Ampliseq run",
        "description": "Amplicon census of twelve samples.",
        "project_type": "advanced",
        "registration_time": "2026-08-01 10:00:00",
        "data_management_platform_project_url": "https://lims.example.org/p/42",
        "yaml_config_path": "/srv/depictio/projects/ampliseq/project.yaml",
        "hash": "deadbeef",
        "is_public": False,
        "permissions": {
            "owners": [{"_id": ObjectId(), "email": "owner@example.org", "is_admin": True}],
            "editors": [{"email": "editor@example.org"}],
            "viewers": ["*"],
        },
        "pending_owner_email": "next-owner@example.org",
        "published_lock": {"dashboard_ids": ["x"], "locked_by": "admin@example.org"},
        "provenance": {"source_instance": "https://internal.example.org", "pushed_by": "a@b.c"},
        "realtime": {"enabled": True, "watch_path": "/data/watch"},
        "template_origin": {
            "template_id": "nf-core/ampliseq/2.14.0",
            "template_version": "1.2.0",
            "applied_at": "2026-08-01T10:00:00",
            "data_root": "/data/runs/ampliseq-2026",
            "variables": {"DATA_ROOT": "/data/runs/ampliseq-2026"},
            "config_snapshot": {"s3": {"secret_key": "hunter2"}},
            "run_provenance": [
                {
                    "source": "params",
                    "group": "Primers",
                    "key": "FW_primer",
                    "value": "GTGYCAGCMGCCGCGGTAA",
                    "highlight": True,
                },
                {
                    "source": "params",
                    "group": "Input",
                    "key": "input",
                    "value": "/data/runs/ampliseq-2026/samplesheet.tsv",
                },
                {
                    "source": "params",
                    "group": "Input",
                    "key": "outdir",
                    "value": "s3://depictio-bucket/runs/ampliseq/results/",
                },
                {
                    "source": "params",
                    "group": "Other",
                    "key": "tower_access_token",
                    "value": "tok-123-xyz",
                },
                {"source": "params", "group": "Other", "key": "author", "value": "Jane"},
                {"source": "params", "group": "Other", "key": "trunclenf", "value": "230"},
                {"source": "params", "group": "Other", "key": "", "value": "dropped"},
            ],
            "run_provenance_files": ["/data/runs/ampliseq-2026/pipeline_info/params.json"],
            "unrecognised_files": [{"path": "x/y.tsv", "format": "tsv"}],
        },
        "workflows": [
            {
                "_id": WF_ID,
                "name": "ampliseq",
                "workflow_tag": "nf-core/ampliseq",
                "version": "2.14.0",
                "engine": {"name": "nextflow", "version": "24.10.0"},
                "catalog": {"name": "nf-core", "url": "https://nf-co.re"},
                "repository_url": "https://github.com/nf-core/ampliseq",
                "data_location": {
                    "structure": "flat",
                    "locations": ["/data/runs/ampliseq-2026"],
                },
                "data_collections": [
                    {
                        "_id": DC_TABLE,
                        "data_collection_tag": "alpha_diversity",
                        "config": {
                            "type": "table",
                            "metatype": "Aggregate",
                            "scan": {
                                "mode": "single",
                                "scan_parameters": {"filename": "/data/a.tsv"},
                            },
                            "dc_specific_properties": {
                                "format": "tsv",
                                "columns_description": {"shannon": "Shannon index"},
                            },
                        },
                        "flexible_metadata": {
                            "deltatable_size_bytes": 20480,
                            "s3_location": "s3://depictio-bucket/alpha/",
                        },
                    },
                    {
                        "_id": DC_MQC,
                        "data_collection_tag": "multiqc_data",
                        "config": {"type": "multiqc"},
                        "flexible_metadata": {"total_file_size_bytes": 4096},
                    },
                    {"data_collection_tag": "no_id"},  # unusable: dropped
                ],
            },
            {"name": "unnamed-id-less"},  # unusable: dropped
        ],
        "data_collections": [
            {
                "_id": DC_DIRECT,
                "data_collection_tag": "sample_sheet",
                "config": {"type": "table", "metatype": "Metadata"},
            }
        ],
        "links": [
            {
                "_id": LINK_ID,
                "source_dc_id": str(DC_DIRECT),
                "source_dc_tag": "sample_sheet",
                "source_column": "sample",
                "target_dc_id": str(DC_MQC),
                "target_dc_tag": "multiqc_data",
                "target_type": "multiqc",
                "link_config": {
                    "resolver": "sample_mapping",
                    "mappings": {"S1": ["S1_R1", "S1_R2"]},
                    "target_field": "sample_name",
                },
                "description": "Samples to MultiQC",
                "enabled": True,
            },
            {"source_dc_id": str(DC_DIRECT)},  # incomplete: dropped
        ],
        "joins": [
            {
                "name": "alpha_with_meta",
                "left_dc": "alpha_diversity",
                "right_dc": "sample_sheet",
                "on_columns": ["sample"],
                "how": "inner",
                "delta_location": "s3://depictio-bucket/joins/abc",
            }
        ],
    }


def _aggregations() -> dict:
    """What producer A reads from ``deltatables``: a whole aggregation entry,
    the user who ran it and the run folders included."""
    return {
        str(DC_TABLE): {
            "aggregation_time": datetime(2026, 8, 2, 9, 30, 5, 123456),
            "aggregation_by": {"id": str(ObjectId()), "email": "runner@example.org"},
            "aggregation_version": 3,
            "aggregation_hash": "cafebabe",
            "aggregation_columns_specs": [
                {"name": "sample", "type": "string", "specs": {"nunique": 12}},
                {"name": "shannon", "type": "float64", "specs": {"nunique": 11, "min": 1.2}},
                {"name": "depictio_run_id", "type": "string"},
                {"type": "int64"},  # nameless: dropped
            ],
            "delta_version": 4,
            "write_mode": "overwrite",
            "rows_total": 12,
            "content_digest": "digest-1",
            "run_tags": ["/data/runs/ampliseq-2026/run-A"],
            "ingestion_run_id": "ing-1",
        }
    }


def test_ingestion_facts_come_through():
    """The live collection viewer's facts: rows, schema, size, time, version."""
    summary = build_project_summary(_project_doc(), None, _aggregations())
    assert summary is not None
    by_tag = {dc.tag: dc for dc in summary.data_collections}
    alpha = by_tag["alpha_diversity"]
    assert alpha.rows == 12
    assert alpha.version == 4
    assert alpha.size_bytes == 20480
    assert alpha.format == "tsv"
    assert alpha.updated_at == "2026-08-02T09:30:05"
    assert [(c.name, c.type, c.distinct) for c in alpha.columns] == [
        ("sample", "string", 12),
        ("shannon", "float64", 11),
        ("depictio_run_id", "string", None),
    ]
    assert alpha.columns[1].description == "Shannon index"
    # A MultiQC report's size is its files'; no aggregation, no facts.
    mqc = by_tag["multiqc_data"]
    assert (mqc.size_bytes, mqc.rows, mqc.columns) == (4096, None, [])


def test_an_enriched_document_carries_its_own_aggregation():
    """The API's enriched project (`last_aggregation` stamped on each DC) needs
    no separate map."""
    doc = _project_doc()
    dc = doc["workflows"][0]["data_collections"][0]
    dc["last_aggregation"] = [{"rows_total": 1}, _aggregations()[str(DC_TABLE)]]
    dc["delta_location"] = "s3://depictio-bucket/alpha"
    summary = build_project_summary(doc, None)
    assert summary is not None
    alpha = next(d for d in summary.data_collections if d.tag == "alpha_diversity")
    assert alpha.rows == 12  # the newest entry, not the first
    text = json.dumps(summary.model_dump(mode="json"))
    assert "depictio-bucket" not in text


def test_ingestion_facts_keep_out_who_and_where():
    summary = build_project_summary(_project_doc(), None, _aggregations())
    assert summary is not None
    text = json.dumps(summary.model_dump(mode="json"))
    for leaked in (
        "runner@example.org",  # aggregation_by
        "aggregation_by",
        "cafebabe",  # aggregation_hash
        "digest-1",
        "run-A",  # run folders
        "ing-1",
        "depictio-bucket",  # s3_location in flexible_metadata
        '"min"',  # column statistics other than the distinct count
    ):
        assert leaked not in text, f"{leaked!r} leaked into the bundle's project summary"


def test_display_facts_come_through():
    summary = build_project_summary(_project_doc(), "https://demo.example.org/")
    assert summary is not None
    assert summary.id == str(PROJECT_ID)
    assert summary.name == "Ampliseq run"
    assert summary.description == "Amplicon census of twelve samples."
    assert summary.project_type == "advanced"
    assert summary.external_url == "https://lims.example.org/p/42"
    assert summary.project_url == f"https://demo.example.org/projects/{PROJECT_ID}"
    assert summary.template is not None
    assert summary.template.template_id == "nf-core/ampliseq/2.14.0"
    assert summary.template.template_version == "1.2.0"

    [workflow] = summary.workflows
    assert (workflow.id, workflow.name, workflow.engine, workflow.engine_version) == (
        str(WF_ID),
        "ampliseq",
        "nextflow",
        "24.10.0",
    )
    assert workflow.catalog == "nf-core"
    assert workflow.repository_url == "https://github.com/nf-core/ampliseq"

    by_tag = {dc.tag: dc for dc in summary.data_collections}
    assert set(by_tag) == {"alpha_diversity", "multiqc_data", "sample_sheet"}
    assert by_tag["alpha_diversity"].workflow_id == str(WF_ID)
    assert by_tag["alpha_diversity"].metatype == "Aggregate"
    assert by_tag["multiqc_data"].type == "multiqc"
    assert by_tag["sample_sheet"].workflow_id is None  # a direct (basic project) collection

    [link] = summary.links
    assert (link.source_dc_tag, link.source_column, link.target_dc_tag) == (
        "sample_sheet",
        "sample",
        "multiqc_data",
    )
    assert link.resolver == "sample_mapping"
    assert link.target_field == "sample_name"
    [join] = summary.joins
    assert (join.left_dc, join.right_dc, join.on_columns, join.how) == (
        "alpha_diversity",
        "sample_sheet",
        ["sample"],
        "inner",
    )

    params = {p.key: p for p in summary.run_parameters}
    assert params["FW_primer"].value == "GTGYCAGCMGCCGCGGTAA"
    assert params["FW_primer"].highlight is True
    assert params["FW_primer"].group == "Primers"
    assert params["trunclenf"].value == "230"
    assert "" not in params
    assert summary.run_parameter_files == ["params.json"]


def test_nothing_sensitive_leaves_the_instance():
    summary = build_project_summary(_project_doc(), None)
    assert summary is not None
    text = json.dumps(summary.model_dump(mode="json"))
    for leaked in (
        "owner@example.org",
        "editor@example.org",
        "next-owner@example.org",
        "admin@example.org",
        "a@b.c",
        "permissions",
        "hunter2",
        "secret_key",
        "/data/runs",
        "/srv/depictio",
        "/data/watch",
        "/data/a.tsv",
        "depictio-bucket",
        "s3://",
        "data_root",
        "config_snapshot",
        "deadbeef",
        "internal.example.org",
        "S1_R1",  # link value mappings stay out
        "tok-123-xyz",  # the token's value
    ):
        assert leaked not in text, f"{leaked!r} leaked into the bundle's project summary"
    # No instance URL declared -> no live project link.
    assert summary.project_url is None
    params = {p.key: p.value for p in summary.run_parameters}
    assert params["input"] == "…/samplesheet.tsv"
    assert params["outdir"] == "…/results"
    assert params["tower_access_token"] == WITHHELD
    assert params["author"] == "Jane"  # `auth` is a credential, `author` is not


def test_no_project_means_no_summary():
    assert build_project_summary(None) is None
    assert build_project_summary({}) is None
    assert build_project_summary({"_id": PROJECT_ID}) is None  # nameless


def test_parameter_values():
    assert safe_parameter_value("input", "/abs/dir/file.csv") == "…/file.csv"
    assert safe_parameter_value("genome_dir", "C:\\genomes\\GRCh38\\") == "…/GRCh38"
    assert safe_parameter_value("ref", "gs://bucket/ref.fa") == "…/ref.fa"
    assert safe_parameter_value("home", "~/data") == "…/data"
    assert safe_parameter_value("root", "/") == "…"
    assert safe_parameter_value("url", "https://user:pw@host.org/x") == "https://host.org/x"
    assert safe_parameter_value("relative", "results/qc") == "results/qc"
    assert safe_parameter_value("n", None) == ""
    assert safe_parameter_value("db_password", "") == ""  # nothing to withhold


def test_secret_keys():
    for key in (
        "password",
        "aws_secret_access_key",
        "api-key",
        "GITHUB_TOKEN",
        "auth",
        "github_pat",
    ):
        assert is_secret_key(key), key
    for key in ("author", "trunclenf", "skip_taxonomy", "path", "pattern"):
        assert not is_secret_key(key), key


def test_public_urls_only():
    assert public_http_url("https://x.org/a") == "https://x.org/a"
    assert public_http_url("https://tok@x.org/a") == "https://x.org/a"
    assert public_http_url("ftp://x.org") is None
    assert public_http_url("/relative") is None
    assert public_http_url(None) is None


def test_summary_validates_inside_a_manifest():
    """The summary is a manifest section: it must round-trip through the model."""
    summary = build_project_summary(_project_doc(), "https://demo.example.org")
    assert isinstance(summary, ProjectSummary)
    field = BundleManifest.model_fields["project"]
    assert field.default is None  # older manifests (no project) stay valid
