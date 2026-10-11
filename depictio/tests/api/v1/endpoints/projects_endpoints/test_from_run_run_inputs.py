"""What a POST /projects/from_run report says of the run and of the template's input files.

``run_info`` is the summary ``GET /projects/folder_inspect`` gives of the same
folder (task counts included), read once: from detection when it ran, else
for the report alone. ``input_files`` has one entry per ``*_FILE`` variable
the template declares, where it resolved, whether the folder holds it, and
which collections use it.

The shipped ``nf-core/ampliseq/2.16.0`` template against the megatest-shaped
fixture (``depictio/tests/cli/s3_stubs.py``), on S3 and on this computer. No
network, nothing created.
"""

import os
from types import SimpleNamespace

import mongomock
import pytest
from bson import ObjectId
from starlette.requests import Request

from depictio.api.v1.endpoints.projects_endpoints import from_run
from depictio.cli.cli.utils import run_detection
from depictio.cli.cli.utils.templates import variable_users
from depictio.models.models.templates import TemplateVariable
from depictio.models.models.users import UserBase
from depictio.tests.cli.s3_stubs import (
    MEGATEST_TREE,
    S3_BUCKET,
    S3_KEY_PREFIX,
    S3_ROOT,
    install_s3_listing,
    write_tree,
)

TEMPLATE_ID = "nf-core/ampliseq/2.16.0"
FILE_VARIABLES = ["SAMPLESHEET_FILE", "TREE_FILE", "METADATA_FILE"]
METADATA_USERS = [
    "metadata",
    "alpha_rarefaction",
    "alpha_rarefaction_summary",
    "ancombc_results",
    "upset_canonical",
    "ma_canonical",
]
TRACE = (
    b"task_id\thash\tnative_id\tname\tstatus\texit\n"
    b"1\tab/01\t11\tFASTQC (S1)\tCOMPLETED\t0\n"
    b"2\tab/02\t12\tCUTADAPT (S1)\tFAILED\t1\n"
    b"3\tab/03\t13\tCUTADAPT (S1)\tCOMPLETED\t0\n"
)
RUN_RECORDS = {
    "pipeline_info/nf_core_pipeline_software_mqc_versions.yml": (
        b"FASTQC:\n  fastqc: 0.12.1\nWorkflow:\n    nf-core/ampliseq: v2.16.0\n"
        b"    Nextflow: 25.10.0\n"
    ),
    "pipeline_info/execution_trace_2026-01-16_12-00-00.txt": TRACE,
}


def _user() -> UserBase:
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=True)


def _request() -> Request:
    return Request(
        {"type": "http", "method": "POST", "path": "/", "headers": [(b"host", b"localhost:8058")]}
    )


def _dry_run(data_root: str = S3_ROOT, template_id: str | None = TEMPLATE_ID, **kwargs):
    return from_run._create_project_from_run(
        data_root=data_root,
        template_id=template_id,
        current_user=_user(),
        dry_run=True,
        request=_request(),
        **kwargs,
    )


def _files(report) -> dict[str, from_run.RunInputFile]:
    return {entry.name: entry for entry in report.input_files}


@pytest.fixture(autouse=True)
def server_context(monkeypatch):
    """Server context, the megatest bucket public, local folders off, no project store."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS", raising=False)
    monkeypatch.delenv("DEPICTIO_AUTH_SINGLE_USER_MODE", raising=False)
    monkeypatch.delenv("DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS", raising=False)
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", S3_BUCKET)
    projects = mongomock.MongoClient()["depictio_test"]["projects"]
    monkeypatch.setattr(from_run, "projects_collection", projects)
    return projects


@pytest.fixture()
def local_run(tmp_path, monkeypatch):
    """Local folders on, ``home/`` the one root, the megatest tree and its run's
    records at ``home/run42``."""
    home = tmp_path / "home"
    write_tree(home / "run42", {**MEGATEST_TREE, **RUN_RECORDS})
    (home / "depictio-local").mkdir()
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(home))
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(home / "depictio-local"))
    return os.path.realpath(home / "run42")


# ── on this computer ─────────────────────────────────────────────────────────


def test_a_local_dry_run_says_what_the_run_records_say(local_run):
    run_info = _dry_run(local_run).run_info

    assert run_info is not None
    assert (run_info.engine, run_info.engine_version) == ("nextflow", "25.10.0")
    assert run_info.tools_executed == ["fastqc"]
    assert run_info.tasks is not None
    assert (run_info.tasks.total, run_info.tasks.completed, run_info.tasks.retried) == (2, 2, 1)
    assert run_info.tasks.trace == os.path.join(
        local_run, "pipeline_info/execution_trace_2026-01-16_12-00-00.txt"
    )


def test_a_local_dry_run_lists_the_template_files_in_its_order(local_run):
    report = _dry_run(local_run)

    assert [entry.name for entry in report.input_files] == FILE_VARIABLES
    files = _files(report)
    sheet = files["SAMPLESHEET_FILE"]
    assert (sheet.location, sheet.found) == (os.path.join(local_run, "input/samplesheet.csv"), True)
    assert sheet.used_by == ["samplesheet"]
    assert sheet.required is False
    assert sheet.description and "samplesheet" in sheet.description
    # The run used metadata (params.json): its copy under input/ was picked.
    metadata = files["METADATA_FILE"]
    assert (metadata.location, metadata.found) == (
        os.path.join(local_run, "input/Metadata_full.tsv"),
        True,
    )
    assert metadata.used_by == METADATA_USERS
    # Not set: nothing resolved, nothing to find. The collection it repoints still says so.
    tree = files["TREE_FILE"]
    assert (tree.location, tree.found, tree.used_by) == (
        None,
        None,
        ["phylogenetic_tree_canonical"],
    )


# ── on S3 ────────────────────────────────────────────────────────────────────


def test_an_s3_dry_run_resolves_each_file_below_the_prefix(monkeypatch):
    install_s3_listing(monkeypatch, MEGATEST_TREE, key_prefix=S3_KEY_PREFIX)

    files = _files(_dry_run(variables={"TREE_FILE": "qiime2/pruned.nwk"}))

    assert (files["SAMPLESHEET_FILE"].location, files["SAMPLESHEET_FILE"].found) == (
        f"{S3_ROOT}/input/samplesheet.csv",
        True,
    )
    assert files["METADATA_FILE"].found is True
    # Named relative to the root, reported where it resolved, and not there.
    assert (files["TREE_FILE"].location, files["TREE_FILE"].found) == (
        f"{S3_ROOT}/qiime2/pruned.nwk",
        False,
    )


def test_an_s3_run_with_records_but_no_trace_has_no_counts(monkeypatch):
    install_s3_listing(monkeypatch, MEGATEST_TREE, key_prefix=S3_KEY_PREFIX)
    run_info = _dry_run().run_info
    # The megatest prefix holds the run's params only: recognised, no trace.
    assert run_info is not None and run_info.engine == "nextflow"
    assert run_info.params_total == 3
    assert run_info.tasks is None


def test_a_folder_no_engine_recognises_has_no_run_info(monkeypatch):
    tree = {
        rel: body for rel, body in MEGATEST_TREE.items() if not rel.startswith("pipeline_info/")
    }
    install_s3_listing(monkeypatch, tree, key_prefix=S3_KEY_PREFIX)
    report = _dry_run()
    assert report.run_info is None
    assert [entry.name for entry in report.input_files] == FILE_VARIABLES


# ── the run is read once ─────────────────────────────────────────────────────


def test_with_detection_the_run_is_not_read_again(monkeypatch):
    from depictio.models.models.run_info import WorkflowRunInfo

    install_s3_listing(monkeypatch, MEGATEST_TREE, key_prefix=S3_KEY_PREFIX)
    info = WorkflowRunInfo(
        engine="nextflow", pipeline_name="nf-core/ampliseq", pipeline_version="2.16.0"
    )
    monkeypatch.setattr(
        run_detection, "detect_template_for_root", lambda _root: (TEMPLATE_ID, info)
    )
    monkeypatch.setattr(
        run_detection,
        "read_run_info_for_root",
        lambda _root: pytest.fail("the run was read a second time"),
    )
    report = _dry_run(template_id=None)
    assert report.detected_template is not None
    assert report.run_info is not None and report.run_info.engine == "nextflow"


def test_with_a_given_template_the_run_is_read_for_the_report(monkeypatch):
    install_s3_listing(monkeypatch, MEGATEST_TREE, key_prefix=S3_KEY_PREFIX)
    real = run_detection.read_run_info_for_root
    reads = []

    def _counted(root):
        reads.append(root.location)
        return real(root)

    monkeypatch.setattr(run_detection, "read_run_info_for_root", _counted)
    assert _dry_run().run_info is not None
    assert reads == [S3_ROOT]


def test_a_failed_read_of_the_run_is_no_run_info(monkeypatch):
    install_s3_listing(monkeypatch, MEGATEST_TREE, key_prefix=S3_KEY_PREFIX)

    def _broken(_root):
        raise OSError("disk went away")

    monkeypatch.setattr(run_detection, "read_run_info_for_root", _broken)
    report = _dry_run()
    assert report.success is True
    assert report.run_info is None


# ── one input file ───────────────────────────────────────────────────────────


def _root(*, under: bool, exists: bool, truncated: bool = False):
    return SimpleNamespace(
        relative_of=lambda value: "input/x.tsv" if under else None,
        exists=lambda rel: exists,
        url=lambda rel: f"s3://b/run/{rel}",
        truncated=truncated,
    )


VARIABLE = TemplateVariable(name="X_FILE", description="An input.", required=True)


@pytest.mark.parametrize(
    ("root", "location", "found"),
    [
        (_root(under=True, exists=True), "s3://b/run/input/x.tsv", True),
        (_root(under=True, exists=False), "s3://b/run/input/x.tsv", False),
        # A partial listing cannot deny a file it does not name.
        (_root(under=True, exists=False, truncated=True), "s3://b/run/input/x.tsv", None),
        # Outside the root: reported as given, never looked up.
        (_root(under=False, exists=True), "s3://elsewhere/x.tsv", None),
    ],
)
def test_where_a_file_resolved_and_whether_it_is_there(root, location, found):
    entry = from_run._input_file(VARIABLE, "s3://elsewhere/x.tsv", root, ["x"])
    assert (entry.location, entry.found) == (location, found)
    assert (entry.required, entry.description, entry.used_by) == (True, "An input.", ["x"])


def test_an_unset_file_is_neither_located_nor_looked_up():
    root = _root(under=True, exists=True)
    entry = from_run._input_file(VARIABLE, None, root, [])
    assert (entry.location, entry.found) == (None, None)


# ── which collections a variable reaches ─────────────────────────────────────


def test_a_variable_reaches_what_reads_it_and_what_a_condition_on_it_switches():
    users = variable_users(TEMPLATE_ID, FILE_VARIABLES)
    # Read by its own collection, and gates five more (if_var_absent).
    assert users["METADATA_FILE"] == METADATA_USERS
    # Read by nothing as written: only the conditional repointing the tree names it.
    assert users["TREE_FILE"] == ["phylogenetic_tree_canonical"]
    assert users["SAMPLESHEET_FILE"] == ["samplesheet"]


def test_a_variable_nothing_uses_reaches_nothing():
    assert variable_users(TEMPLATE_ID, ["NOT_A_VARIABLE_FILE"]) == {"NOT_A_VARIABLE_FILE": []}
