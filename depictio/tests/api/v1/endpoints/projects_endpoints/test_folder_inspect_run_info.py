"""What GET /projects/folder_inspect says about the run's own records (``run_info``).

The run's provenance comes from the same read that detects its template: the
engine and its version, the run's parameters, the tools it ran and the reports
it wrote, each with its size. A size comes from the S3 listing the detection
already made, or from a stat of a file the local-data policy lets the server
read; no report is ever read for it.

No network: S3 is the shared stub (``depictio/tests/cli/s3_stubs.py``).
"""

import json
import os

import pytest
from bson import ObjectId
from starlette.requests import Request

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.projects_endpoints import run_folders
from depictio.models.models.run_info import WorkflowRunInfo
from depictio.models.models.users import UserBase
from depictio.tests.cli.s3_stubs import install_s3_listing, write_tree

PUBLIC = "open-data"
INSTANCE = "instance-data"

LONG_TEXT = "x" * 400
PARAMS = {
    "run_name": "lucky_turing",
    "input": "samplesheet.csv",
    "FW_primer": LONG_TEXT,
    "trunclenf": 230,
    "max_ee": 2.5,
    "skip_qiime": False,
    "metadata_category": None,
    "exclude_taxa": ["mitochondria", "chloroplast"],
    "cutoffs": {"min": 1},
    "hook_url": "https://hooks.example.org/T000/B000/abcdef",
}
REPORT = b"<html>" + b"r" * 1000 + b"</html>"
TRACE = b"task_id\thash\n1\tab/cdef\n"
DAG = b"<html>dag</html>"


def _versions() -> bytes:
    return (
        "CUTADAPT_BASIC:\n  cutadapt: 4.6\nFASTQC:\n  fastqc: 0.12.1\n"
        "Workflow:\n    nf-core/ampliseq: v2.16.0\n    Nextflow: 25.10.0\n"
    ).encode()


def _run_tree() -> dict[str, bytes]:
    return {
        "pipeline_info/nf_core_pipeline_software_mqc_versions.yml": _versions(),
        "pipeline_info/params_2026-01-01_10-00-00.json": json.dumps(PARAMS).encode(),
        "pipeline_info/execution_report_2026-01-01_10-00-00.html": REPORT,
        "pipeline_info/execution_trace_2026-01-01_10-00-00.txt": TRACE,
        "pipeline_info/pipeline_dag_2026-01-01_10-00-00.html": DAG,
        "multiqc/multiqc_data/multiqc.parquet": b"PAR1",
    }


def _user() -> UserBase:
    return UserBase(id=ObjectId(), email="me@example.com", is_admin=True)


def _request() -> Request:
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": [(b"host", b"localhost:8058")]}
    )


def _inspect(location: str, *, detect: bool = True):
    return run_folders.inspect_folder(
        location, detect=detect, request=_request(), current_user=_user()
    )


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    """Server context, no bucket listed, local folders off, unless a test says otherwise."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    for name in (
        "DEPICTIO_LOCAL_DATA_ROOTS",
        "DEPICTIO_AUTH_SINGLE_USER_MODE",
        "DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS",
        "DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings.s3, "bucket", INSTANCE)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Local folders on, ``home/`` the one root."""
    root = tmp_path / "home"
    root.mkdir()
    (root / "depictio-local").mkdir()
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(root))
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(root / "depictio-local"))
    return root


def _reports(run_info) -> dict[str, tuple[str, str, int | None]]:
    return {report.kind: (report.location, report.name, report.size) for report in run_info.reports}


# ── a local run folder ───────────────────────────────────────────────────────


def test_a_local_run_says_what_its_records_say(home):
    write_tree(home / "run", _run_tree())
    real = os.path.realpath(home / "run")

    inspection = _inspect(str(home / "run"))

    assert inspection.detected is not None
    run_info = inspection.run_info
    assert run_info is not None
    assert (run_info.engine, run_info.engine_version, run_info.run_name) == (
        "nextflow",
        "25.10.0",
        "lucky_turing",
    )
    assert run_info.tools_executed == ["cutadapt", "fastqc"]
    assert run_info.extra == {"pipeline_version_raw": "v2.16.0"}

    info = os.path.join(real, "pipeline_info")
    assert _reports(run_info) == {
        "software_versions": (
            os.path.join(info, "nf_core_pipeline_software_mqc_versions.yml"),
            "nf_core_pipeline_software_mqc_versions.yml",
            len(_versions()),
        ),
        "params": (
            os.path.join(info, "params_2026-01-01_10-00-00.json"),
            "params_2026-01-01_10-00-00.json",
            len(json.dumps(PARAMS).encode()),
        ),
        # The sizes of the files themselves, although detection staged only
        # an empty stand-in for each of these.
        "execution_report": (
            os.path.join(info, "execution_report_2026-01-01_10-00-00.html"),
            "execution_report_2026-01-01_10-00-00.html",
            len(REPORT),
        ),
        "execution_trace": (
            os.path.join(info, "execution_trace_2026-01-01_10-00-00.txt"),
            "execution_trace_2026-01-01_10-00-00.txt",
            len(TRACE),
        ),
        "pipeline_dag": (
            os.path.join(info, "pipeline_dag_2026-01-01_10-00-00.html"),
            "pipeline_dag_2026-01-01_10-00-00.html",
            len(DAG),
        ),
    }


def test_the_run_params_are_flattened_clipped_and_sorted(home):
    write_tree(home / "run", _run_tree())

    run_info = _inspect(str(home / "run")).run_info

    assert run_info is not None
    assert run_info.params_total == len(PARAMS)
    assert list(run_info.params) == sorted(PARAMS)
    assert run_info.params["run_name"] == "lucky_turing"
    assert run_info.params["FW_primer"] == "x" * run_folders.MAX_PARAM_CHARS + "..."
    assert (run_info.params["trunclenf"], run_info.params["max_ee"]) == (230, 2.5)
    assert run_info.params["skip_qiime"] is False
    assert run_info.params["metadata_category"] is None
    assert run_info.params["exclude_taxa"] == '["mitochondria", "chloroplast"]'
    assert run_info.params["cutoffs"] == '{"min": 1}'
    # A parameter named for a credential is never echoed.
    assert run_info.params["hook_url"] == run_folders.HIDDEN_PARAM
    dumped = run_info.model_dump_json()
    assert "hooks.example.org" not in dumped
    # A boolean stays one on the wire, rather than becoming 0 or "False".
    assert json.loads(dumped)["params"]["skip_qiime"] is False


def test_only_the_first_params_by_name_are_kept_and_all_are_counted(home, monkeypatch):
    monkeypatch.setattr(run_folders, "MAX_RUN_PARAMS", 3)
    write_tree(home / "run", _run_tree())

    run_info = _inspect(str(home / "run")).run_info

    assert run_info is not None
    assert list(run_info.params) == sorted(PARAMS)[:3]
    assert run_info.params_total == len(PARAMS)


def test_a_report_linked_from_outside_the_data_roots_gets_no_size(home, tmp_path):
    """A link leaving the data roots is either not listed by the confined root at
    all, or (its target in a folder the server reads for itself, such as the
    temporary directory this test writes to) listed but never stat-ed: its size
    is only taken where the policy lets data be read. Its target is never named."""
    tree = _run_tree()
    del tree["pipeline_info/execution_report_2026-01-01_10-00-00.html"]
    write_tree(home / "run", tree)
    outside = tmp_path / "outside" / "execution_report_2026-01-01_10-00-00.html"
    outside.parent.mkdir()
    outside.write_bytes(REPORT)
    (home / "run" / "pipeline_info" / outside.name).symlink_to(outside)

    run_info = _inspect(str(home / "run")).run_info

    assert run_info is not None
    report = _reports(run_info).get("execution_report")
    assert report is None or report[2] is None
    assert str(outside) not in run_info.model_dump_json()
    assert _reports(run_info)["execution_trace"][2] == len(TRACE)


def test_a_local_size_is_taken_below_the_root_where_the_policy_allows(home, tmp_path):
    from depictio.api.v1.configs.settings_models import local_data_policy
    from depictio.cli.cli.utils.data_root import LocalDataRoot

    write_tree(home / "run", {"pipeline_info/report.html": REPORT})
    elsewhere = write_tree(tmp_path / "elsewhere", {"report.html": REPORT}) / "report.html"
    (home / "run" / "pipeline_info" / "linked.html").symlink_to(elsewhere)
    root = LocalDataRoot(os.path.realpath(home / "run"))
    policy = local_data_policy()
    assert policy is not None
    inside = root.url("pipeline_info/report.html")

    assert run_folders._report_size(inside, root, policy, None) == len(REPORT)
    # Through a link that leaves the data roots, outside the root, or with no policy.
    assert (
        run_folders._report_size(root.url("pipeline_info/linked.html"), root, policy, None) is None
    )
    assert run_folders._report_size(str(elsewhere), root, policy, None) is None
    assert run_folders._report_size(inside, root, None, None) is None


def test_a_folder_that_is_not_a_run_has_no_run_info(home):
    write_tree(home / "notes", {"a.txt": b"x"})
    inspection = _inspect(str(home / "notes"))
    assert (inspection.detected, inspection.run_info) == (None, None)


def test_without_detection_there_is_no_run_info(home):
    write_tree(home / "run", _run_tree())
    assert _inspect(str(home / "run"), detect=False).run_info is None


def test_a_run_no_template_fits_still_says_what_it_is(home):
    tree = _run_tree()
    tree["pipeline_info/nf_core_pipeline_software_mqc_versions.yml"] = (
        b"Workflow:\n    nf-core/nothing-ships: 1.0.0\n    Nextflow: 24.04.1\n"
    )
    write_tree(home / "run", tree)

    inspection = _inspect(str(home / "run"))

    assert inspection.detected is not None and inspection.detected.match == "none"
    assert inspection.run_info is not None
    assert inspection.run_info.engine_version == "24.04.1"


# ── an s3:// run folder ──────────────────────────────────────────────────────


def test_an_s3_run_takes_its_report_sizes_from_the_listing(monkeypatch):
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", f"{PUBLIC}/runs")
    monkeypatch.setattr(run_folders, "ensure_region", lambda target: target)
    tree = _run_tree()
    client = install_s3_listing(monkeypatch, {f"runs/r/{rel}": body for rel, body in tree.items()})

    run_info = _inspect(f"s3://{PUBLIC}/runs/r/").run_info

    assert run_info is not None
    assert run_info.engine == "nextflow"
    url = f"s3://{PUBLIC}/runs/r/pipeline_info"
    assert _reports(run_info)["execution_report"] == (
        f"{url}/execution_report_2026-01-01_10-00-00.html",
        "execution_report_2026-01-01_10-00-00.html",
        len(REPORT),
    )
    assert _reports(run_info)["software_versions"][2] == len(_versions())
    # Only what detection opens is fetched: never a report, for its size or otherwise.
    assert not any("execution_" in key or "pipeline_dag" in key for key in client.get_object_calls)


# ── the summary itself ───────────────────────────────────────────────────────


def test_extra_keeps_single_texts_and_numbers():
    info = WorkflowRunInfo(
        engine="nextflow",
        extra={
            "pipeline_version_raw": "v2.16.0-g3d5c7e5",
            "identity_from_run": "run_1",
            "run_subdirs_scanned": 3,
            "identities_seen": ["nf-core/a 1.0", "nf-core/a 2.0"],
        },
    )
    summary = run_folders._run_info_summary(info, root=None)
    assert summary is not None
    assert summary.extra == {
        "identity_from_run": "run_1",
        "pipeline_version_raw": "v2.16.0-g3d5c7e5",
        "run_subdirs_scanned": "3",
    }
    assert (summary.reports, summary.params, summary.params_total) == ([], {}, 0)


def test_a_non_finite_number_is_shown_as_text():
    info = WorkflowRunInfo(params={"ratio": float("nan"), "limit": float("inf")})
    summary = run_folders._run_info_summary(info, root=None)
    assert summary is not None
    assert summary.params == {"limit": "inf", "ratio": "nan"}
