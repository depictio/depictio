"""How the tasks of a run ended (``run_info.tasks``), counted from its execution trace.

The trace is the one the Nextflow reader picked, the newest by name, and is
read from the run folder itself, never from the copy detection made: on S3
that copy holds an empty stand-in for it. Bounded (``MAX_TRACE_BYTES``), and a
nicety only: a trace that cannot be read gives no counts and fails nothing.

No network: S3 is the shared stub (``depictio/tests/cli/s3_stubs.py``).
"""

import os

import pytest
from bson import ObjectId
from starlette.requests import Request

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.settings_models import local_data_policy
from depictio.api.v1.endpoints.projects_endpoints import run_folders
from depictio.cli.cli.utils.data_root import LocalDataRoot
from depictio.models.models.run_info import WorkflowRunInfo
from depictio.models.models.users import UserBase
from depictio.tests.cli.s3_stubs import (
    StubS3Client,
    install_s3_client,
    install_s3_listing,
    s3_client_error,
    write_tree,
)

PUBLIC = "open-data"
HEADER = "task_id\thash\tnative_id\tname\tstatus\texit\n"
VERSIONS = b"Workflow:\n    nf-core/ampliseq: v2.16.0\n    Nextflow: 25.10.0\n"
OLDER = "pipeline_info/execution_trace_2026-01-01_10-00-00.txt"
NEWER = "pipeline_info/execution_trace_2026-01-02_09-30-00.txt"


def _trace(*rows: tuple[str, str]) -> bytes:
    """A trace with one line per ``(name, status)`` attempt, in order."""
    lines = [
        f"{index}\tab/{index:06x}\t{1000 + index}\t{name}\t{status}\t0\n"
        for index, (name, status) in enumerate(rows, start=1)
    ]
    return (HEADER + "".join(lines)).encode()


# Seven tasks: E failed twice before it completed, F failed before it was cached.
MIXED = (
    ("FASTQC (S1)", "COMPLETED"),
    ("FASTQC (S2)", "CACHED"),
    ("CUTADAPT (S1)", "FAILED"),
    ("CUTADAPT (S2)", "ABORTED"),
    ("DADA2_FILTNTRIM (S1)", "FAILED"),
    ("DADA2_FILTNTRIM (S1)", "FAILED"),
    ("DADA2_FILTNTRIM (S1)", "COMPLETED"),
    ("QIIME2_INSEQ", "FAILED"),
    ("QIIME2_INSEQ", "CACHED"),
    ("MULTIQC", "RUNNING"),
)


def _counts(tasks) -> tuple[int, int, int, int, int, int]:
    return (tasks.total, tasks.completed, tasks.cached, tasks.failed, tasks.retried, tasks.other)


def _user() -> UserBase:
    return UserBase(id=ObjectId(), email="me@example.com", is_admin=True)


def _request() -> Request:
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": [(b"host", b"localhost:8058")]}
    )


def _run_info(location: str):
    return run_folders.inspect_folder(location, request=_request(), current_user=_user()).run_info


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
    monkeypatch.setattr(settings.s3, "bucket", "instance-data")


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


def _run(home, traces: dict[str, bytes]):
    """``home/run``: a versions YAML and the given traces under ``pipeline_info/``."""
    tree = {"pipeline_info/nf_core_pipeline_software_mqc_versions.yml": VERSIONS, **traces}
    return write_tree(home / "run", tree)


# ── the counts ───────────────────────────────────────────────────────────────


def test_each_task_is_counted_once_by_its_last_attempt():
    tasks = run_folders._trace_tasks(_trace(*MIXED).decode(), trace="t.txt")
    assert tasks is not None
    # total, completed, cached, failed, retried, other
    assert _counts(tasks) == (7, 2, 2, 2, 2, 1)
    assert (tasks.trace, tasks.partial) == ("t.txt", False)


def test_a_trace_without_names_keys_its_tasks_by_hash():
    text = "task_id\thash\tstatus\n1\tab/01\tFAILED\n2\tab/01\tCOMPLETED\n3\tcd/02\tCOMPLETED\n"
    tasks = run_folders._trace_tasks(text, trace="t.txt")
    assert tasks is not None
    assert _counts(tasks) == (2, 2, 0, 0, 1, 0)


def test_a_trace_without_a_status_column_has_nothing_to_count():
    assert run_folders._trace_tasks("task_id\thash\n1\tab/cdef\n", trace="t.txt") is None
    assert run_folders._trace_tasks("", trace="t.txt") is None


def test_blank_and_short_lines_are_not_tasks():
    text = f"{HEADER}\n1\tab/01\t1\tFASTQC\tCOMPLETED\t0\n2\tab/02\n\n"
    tasks = run_folders._trace_tasks(text, trace="t.txt")
    assert tasks is not None
    assert _counts(tasks) == (1, 1, 0, 0, 0, 0)


# ── a local run folder ───────────────────────────────────────────────────────


def test_a_local_run_counts_the_tasks_of_its_trace(home):
    run = _run(home, {OLDER: _trace(*MIXED)})

    tasks = _run_info(str(run)).tasks

    assert tasks is not None
    assert _counts(tasks) == (7, 2, 2, 2, 2, 1)
    assert tasks.trace == os.path.join(os.path.realpath(run), OLDER)
    assert tasks.partial is False


def test_the_latest_of_several_traces_is_the_one_counted(home):
    """A resumed run writes one trace per launch; the last launch is the run's state."""
    run = _run(
        home,
        {
            OLDER: _trace(("FASTQC (S1)", "FAILED"), ("FASTQC (S2)", "FAILED")),
            NEWER: _trace(("FASTQC (S1)", "COMPLETED"), ("FASTQC (S2)", "CACHED")),
        },
    )

    tasks = _run_info(str(run)).tasks

    assert tasks is not None
    assert tasks.trace.endswith(NEWER)
    assert _counts(tasks) == (2, 1, 1, 0, 0, 0)


def test_a_trace_larger_than_the_cap_is_partial_and_its_cut_line_dropped(home, monkeypatch):
    body = _trace(("A", "COMPLETED"), ("B", "COMPLETED"), ("C", "FAILED"))
    # The cut lands inside C's line: C is not counted, rather than miscounted.
    monkeypatch.setattr(run_folders, "MAX_TRACE_BYTES", len(body) - 5)
    run = _run(home, {OLDER: body})

    tasks = _run_info(str(run)).tasks

    assert tasks is not None
    assert tasks.partial is True
    assert _counts(tasks) == (2, 2, 0, 0, 0, 0)


def test_a_trace_without_a_status_column_gives_no_counts(home):
    run = _run(home, {OLDER: b"task_id\thash\n1\tab/cdef\n"})
    run_info = _run_info(str(run))
    assert run_info is not None and run_info.engine == "nextflow"
    assert run_info.tasks is None


def test_a_run_without_a_trace_gives_no_counts(home):
    run = _run(home, {})
    run_info = _run_info(str(run))
    assert run_info is not None
    assert run_info.tasks is None


def test_without_a_local_data_policy_a_local_trace_is_not_read(home):
    """As a report's size: a local file is read only where the policy lets data be read."""
    run = _run(home, {OLDER: _trace(*MIXED)})
    info = WorkflowRunInfo(
        engine="nextflow", execution_trace_path=os.path.join(os.path.realpath(run), OLDER)
    )
    root = LocalDataRoot(os.path.realpath(run))
    assert run_folders._run_info_summary(info, root, policy=None).tasks is None


def test_a_trace_outside_the_root_is_not_read(home, tmp_path):
    elsewhere = write_tree(tmp_path / "elsewhere", {"execution_trace.txt": _trace(*MIXED)})
    run = _run(home, {})
    info = WorkflowRunInfo(
        engine="nextflow", execution_trace_path=str(elsewhere / "execution_trace.txt")
    )
    root = LocalDataRoot(os.path.realpath(run))
    assert run_folders._run_info_summary(info, root, local_data_policy()).tasks is None


# ── an s3:// run folder ──────────────────────────────────────────────────────


def _s3_run(monkeypatch, client_class=StubS3Client):
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", f"{PUBLIC}/runs")
    monkeypatch.setattr(run_folders, "ensure_region", lambda target: target)
    tree = {
        "pipeline_info/nf_core_pipeline_software_mqc_versions.yml": VERSIONS,
        OLDER: _trace(*MIXED),
    }
    client = client_class({f"runs/r/{rel}": body for rel, body in tree.items()})
    return install_s3_client(monkeypatch, client)


def test_an_s3_run_counts_the_real_trace_not_the_staged_stand_in(monkeypatch):
    client = _s3_run(monkeypatch)

    tasks = _run_info(f"s3://{PUBLIC}/runs/r/").tasks

    assert tasks is not None
    assert _counts(tasks) == (7, 2, 2, 2, 2, 1)
    assert tasks.trace == f"s3://{PUBLIC}/runs/r/{OLDER}"
    reads = dict(zip(client.get_object_calls, client.get_object_ranges, strict=True))
    assert reads[f"runs/r/{OLDER}"] == f"bytes=0-{run_folders.MAX_TRACE_BYTES - 1}"


def test_a_trace_s3_refuses_gives_no_counts_and_fails_nothing(monkeypatch):
    class _TraceDenied(StubS3Client):
        def get_object(self, Bucket, Key, Range=None):  # noqa: N803 - boto3's spelling
            if "execution_trace" in Key:
                self.get_object_calls.append(Key)
                raise s3_client_error("AccessDenied", 403, "GetObject")
            return super().get_object(Bucket, Key, Range)

    client = _s3_run(monkeypatch, _TraceDenied)

    run_info = _run_info(f"s3://{PUBLIC}/runs/r/")

    assert run_info is not None and run_info.engine_version == "25.10.0"
    assert run_info.tasks is None
    # Asked once, and nothing read in its place.
    assert client.get_object_calls.count(f"runs/r/{OLDER}") == 1


def test_an_s3_run_without_a_listed_trace_reads_none(monkeypatch):
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", f"{PUBLIC}/runs")
    monkeypatch.setattr(run_folders, "ensure_region", lambda target: target)
    client = install_s3_listing(
        monkeypatch, {"runs/r/pipeline_info/nf_core_pipeline_software_mqc_versions.yml": VERSIONS}
    )
    assert _run_info(f"s3://{PUBLIC}/runs/r/").tasks is None
    assert not any("execution_trace" in key for key in client.get_object_calls)
