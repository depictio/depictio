"""Tests for the run-folder picker reads: GET /projects/s3_dirs, /folder_inspect and
/find_runs (``run_folders``).

An ``s3://`` location is browsed only where an administrator listed it, the
instance's own bucket never, and every refusal is decided before a client is
built. A local one goes through the guards and the policy of ``local_dirs``.
Detection is the real one on a run folder written to disk, or stubbed where
only its plumbing is under test.

No network: S3 is the shared stub (``depictio/tests/cli/s3_stubs.py``), which
answers a ``Delimiter="/"`` listing the way S3 does.
"""

import json
import os

import pytest
from bson import ObjectId
from fastapi import HTTPException
from starlette.requests import Request

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.projects_endpoints import from_run, routes, run_folders
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import CodedHTTPException
from depictio.models.models.run_info import WorkflowRunInfo
from depictio.models.models.users import UserBase
from depictio.models.s3_access import S3AccessFailed, S3AccessRefused, S3Target
from depictio.tests.cli.s3_stubs import (
    FailingS3Client,
    install_s3_client,
    install_s3_listing,
    s3_client_error,
    write_tree,
)

PUBLIC = "open-data"
LAB = "lab-data"
INSTANCE = "instance-data"


def _user(is_admin: bool = True) -> UserBase:
    return UserBase(id=ObjectId(), email="me@example.com", is_admin=is_admin)


def _request(host: str | None = "localhost:8058") -> Request:
    headers = [(b"host", host.encode())] if host is not None else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def _versions(pipeline: str, version: str) -> str:
    # 4-space `Workflow:` indent, as real nf-core output uses.
    return (
        f"FASTQC:\n  fastqc: 0.12.1\nWorkflow:\n    {pipeline}: {version}\n    Nextflow: 25.10.0\n"
    )


def _run_tree(version: str = "v2.16.0", pipeline: str = "nf-core/ampliseq") -> dict[str, bytes]:
    return {
        "pipeline_info/software_versions.yml": _versions(pipeline, version).encode(),
        "pipeline_info/params_2026-01-01_10-00-00.json": json.dumps({"run_name": "r"}).encode(),
        "multiqc/multiqc_data/multiqc.parquet": b"PAR1",
        "qiime2/barplot/level-2.csv": b"index,Bacteria\nS1,42\n",
        "input/samplesheet.csv": b"sampleID\nS1\n",
        "template.yaml": b"name: x\n",
    }


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
def listed(monkeypatch):
    """One public prefix, one credentialed bucket, and the instance's own bucket listed
    by mistake: the server must still never browse it."""
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", f"{PUBLIC}/runs, {INSTANCE}")
    monkeypatch.setenv("DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS", f"{LAB}, {PUBLIC}/runs")


@pytest.fixture()
def no_client(monkeypatch):
    """Fail the test if any S3 client is built: a refusal needs none."""
    monkeypatch.setattr(S3Target, "client", lambda _target: pytest.fail("an S3 client was built"))


def _serve(monkeypatch, keys: dict[str, bytes], **client_kwargs):
    """Every S3 read answered from ``keys`` (whole keys), no region lookup."""
    monkeypatch.setattr(run_folders, "ensure_region", lambda target: target)
    return install_s3_listing(monkeypatch, keys, **client_kwargs)


def _under(prefix: str, tree: dict[str, bytes]) -> dict[str, bytes]:
    return {f"{prefix}{rel}": body for rel, body in tree.items()}


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


def _coded(fn, *args, **kwargs) -> CodedHTTPException:
    with pytest.raises(CodedHTTPException) as exc:
        fn(*args, **kwargs)
    return exc.value


def _inspect(location, *, detect=True, host="localhost:8058", user=None):
    return run_folders.inspect_folder(
        location, detect=detect, request=_request(host), current_user=user or _user()
    )


def _find(location, *, host="localhost:8058", user=None):
    return run_folders.find_runs(location, request=_request(host), current_user=user or _user())


# ── GET /projects/s3_dirs: the listed locations ──────────────────────────────


def test_without_a_url_the_listed_locations_public_first(listed, no_client):
    listing = run_folders.list_s3_dirs(None)
    assert (listing.path, listing.root, listing.parent) == (None, None, None)
    # The instance bucket is left out, and a location listed twice comes once.
    assert [(e.name, e.path) for e in listing.entries] == [
        (f"{PUBLIC}/runs", f"s3://{PUBLIC}/runs/"),
        (LAB, f"s3://{LAB}/"),
    ]
    assert all(e.has_children and not e.looks_like_run for e in listing.entries)


def test_nothing_listed_is_an_empty_listing(no_client):
    assert run_folders.list_s3_dirs(None).entries == []
    assert run_folders.list_s3_dirs("").entries == []


# ── GET /projects/s3_dirs: one location ──────────────────────────────────────


RUNS_KEYS = {
    "runs/results-b/pipeline_info/params.json": b"{}",
    "runs/results-a/multiqc/multiqc_data/multiqc.parquet": b"PAR1",
    "runs/results-a/qiime2/x.csv": b"x",
    "runs/multiqc/report.html": b"<html>",
    "runs/README.md": b"hi",
    "runs/": b"",
}


def test_a_listed_prefix_lists_its_sub_folders_from_one_page(monkeypatch, listed):
    client = _serve(monkeypatch, RUNS_KEYS)
    listing = run_folders.list_s3_dirs(f"s3://{PUBLIC}/runs")

    assert listing.path == f"s3://{PUBLIC}/runs/"
    assert listing.root == f"s3://{PUBLIC}/runs/"
    assert listing.parent is None
    assert [(e.name, e.path) for e in listing.entries] == [
        ("multiqc", f"s3://{PUBLIC}/runs/multiqc/"),
        ("results-a", f"s3://{PUBLIC}/runs/results-a/"),
        ("results-b", f"s3://{PUBLIC}/runs/results-b/"),
    ]
    # Unknown without a request per entry: every entry may be opened.
    assert all(e.has_children and not e.looks_like_run for e in listing.entries)
    # The listed location holds a multiqc/, but no MultiQC output in it: one
    # more page, of the keys below multiqc/, says so.
    assert listing.looks_like_run is False
    assert listing.truncated is False
    assert client.listings == [
        {"Bucket": PUBLIC, "Prefix": "runs/", "Delimiter": "/"},
        {"Bucket": PUBLIC, "Prefix": "runs/multiqc/", "Delimiter": None},
    ]
    assert client.pages_served == 2


def test_below_the_listed_prefix_parent_goes_up_one_level(monkeypatch, listed):
    _serve(monkeypatch, RUNS_KEYS)
    listing = run_folders.list_s3_dirs(f"s3://{PUBLIC}/runs/results-a/")
    assert listing.path == f"s3://{PUBLIC}/runs/results-a/"
    assert listing.parent == f"s3://{PUBLIC}/runs/"
    assert listing.root == f"s3://{PUBLIC}/runs/"
    assert [e.name for e in listing.entries] == ["multiqc", "qiime2"]
    assert listing.looks_like_run is True


def test_a_whole_listed_bucket_is_its_own_root(monkeypatch, listed):
    client = _serve(
        monkeypatch,
        {
            "exp1/run1/pipeline_info/p.json": b"{}",
            "exp1/run1/multiqc/multiqc_report.html": b"<html>",
            "notes.txt": b"x",
        },
    )
    top = run_folders.list_s3_dirs(f"s3://{LAB}")
    assert (top.path, top.root, top.parent) == (f"s3://{LAB}/", f"s3://{LAB}/", None)
    assert [e.name for e in top.entries] == ["exp1"]
    assert top.looks_like_run is False

    deeper = run_folders.list_s3_dirs(f"s3://{LAB}/exp1/run1/")
    assert deeper.parent == f"s3://{LAB}/exp1/"
    assert deeper.looks_like_run is True
    # pipeline_info/ settles it: no page is asked for below multiqc/.
    assert [listing["Prefix"] for listing in client.listings] == ["", "exp1/run1/"]


@pytest.mark.parametrize(
    ("keys", "is_run"),
    [
        ({"runs/rna/multiqc/star_salmon/multiqc_report.html": b"<html>"}, True),
        ({"runs/rna/multiqc/multiqc.parquet": b"PAR1"}, True),
        ({"runs/rna/multiqc/fastqc.yaml": b"x", "runs/rna/multiqc/bowtie2/r.yaml": b"x"}, False),
        ({"runs/rna/multiqc/a/b/multiqc_report.html": b"<html>"}, False),
    ],
)
def test_an_s3_multiqc_folder_is_a_marker_only_with_multiqc_output(
    monkeypatch, listed, keys, is_run
):
    _serve(monkeypatch, {**keys, "runs/rna/star_salmon/x.bam": b"x"})
    assert run_folders.list_s3_dirs(f"s3://{PUBLIC}/runs/rna/").looks_like_run is is_run
    inspection = _inspect(f"s3://{PUBLIC}/runs/rna/", detect=False)
    assert inspection.markers == (["multiqc"] if is_run else [])
    assert inspection.folders.names == ["multiqc", "star_salmon"]


def test_a_multiqc_folder_that_cannot_be_listed_is_no_marker(monkeypatch, listed):
    client = _serve(monkeypatch, {"runs/r/multiqc/multiqc_data/multiqc.parquet": b"PAR1"})
    paginator = client.get_paginator("list_objects_v2")

    class _DeniedBelowMultiqc:
        def paginate(self, **params):
            if params["Prefix"].endswith("multiqc/"):
                raise s3_client_error("AccessDenied", 403)
            return paginator.paginate(**params)

    monkeypatch.setattr(client, "get_paginator", lambda _name: _DeniedBelowMultiqc())
    listing = run_folders.list_s3_dirs(f"s3://{PUBLIC}/runs/r/")
    assert [e.name for e in listing.entries] == ["multiqc"]
    assert listing.looks_like_run is False


def test_the_root_is_the_outermost_listed_location(monkeypatch):
    """A bucket listed whole and one of its prefixes listed again: going up stops at
    the bucket, where everything is still readable."""
    monkeypatch.setenv("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", f"{PUBLIC}/runs")
    monkeypatch.setenv("DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS", PUBLIC)
    _serve(monkeypatch, RUNS_KEYS)
    listing = run_folders.list_s3_dirs(f"s3://{PUBLIC}/runs/")
    assert listing.root == f"s3://{PUBLIC}/"
    assert listing.parent == f"s3://{PUBLIC}/"


def test_more_folders_than_the_cap_is_truncated(monkeypatch, listed):
    monkeypatch.setattr(run_folders, "MAX_ENTRIES", 2)
    _serve(monkeypatch, RUNS_KEYS)
    listing = run_folders.list_s3_dirs(f"s3://{PUBLIC}/runs/")
    assert [e.name for e in listing.entries] == ["multiqc", "results-a"]
    assert listing.truncated is True


def test_a_truncated_page_is_truncated(monkeypatch, listed):
    _serve(monkeypatch, RUNS_KEYS, is_truncated=True)
    assert run_folders.list_s3_dirs(f"s3://{PUBLIC}/runs/").truncated is True


@pytest.mark.parametrize("code", ["NoSuchKey", "404"])
def test_a_404_listing_is_empty(monkeypatch, listed, code):
    monkeypatch.setattr(run_folders, "ensure_region", lambda target: target)
    install_s3_client(monkeypatch, FailingS3Client(code, 404))
    listing = run_folders.list_s3_dirs(f"s3://{PUBLIC}/runs/gone/")
    assert listing.entries == []
    assert listing.truncated is False


def test_a_denied_listing_keeps_its_code_and_no_endpoint(monkeypatch, listed):
    monkeypatch.setattr(run_folders, "ensure_region", lambda target: target)
    install_s3_client(monkeypatch, FailingS3Client("AccessDenied", 403))
    with pytest.raises(S3AccessFailed) as exc:
        run_folders.list_s3_dirs(f"s3://{LAB}/exp1/")
    assert (exc.value.status_code, exc.value.code) == (422, "s3_access_denied")
    assert "s3:9000" not in exc.value.detail and "RequestId" not in exc.value.detail


# ── S3 refusals, decided before a client is built ────────────────────────────


@pytest.mark.parametrize(
    ("url", "says"),
    [
        (f"s3://{INSTANCE}/projects/", "instance's own data"),
        ("s3://private-bucket/run1/", "cannot be read by the server"),
        # Above the listed prefix, and a sibling sharing its first letters.
        (f"s3://{PUBLIC}/", "cannot be read by the server"),
        (f"s3://{PUBLIC}/runs-old/", "cannot be read by the server"),
        ("s3://", "not a valid s3:// location"),
        ("https://example.org/runs/", "not an s3:// location"),
    ],
)
def test_s3_dirs_refuses_what_is_not_listed(listed, no_client, url, says):
    with pytest.raises(S3AccessRefused) as exc:
        run_folders.list_s3_dirs(url)
    assert (exc.value.status_code, exc.value.code) == (422, "s3_refused")
    assert says in exc.value.detail


def test_nothing_is_browsed_outside_the_lists_whatever_the_context(monkeypatch, no_client):
    """In CLI context the resolver would read an unlisted bucket with the CLI
    configuration's keys; browsing still refuses it, before any request."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "CLI")
    with pytest.raises(S3AccessRefused, match="lets you browse"):
        run_folders.list_s3_dirs("s3://private-bucket/run1/")


# ── GET /projects/folder_inspect: local ──────────────────────────────────────


def test_inspect_a_local_run_folder(home):
    write_tree(home / "results" / "2.16.0", _run_tree())
    (home / "results" / "2.16.0" / ".cache").mkdir()
    (home / "results" / "2.16.0" / ".env").write_text("SECRET=1")

    inspection = _inspect(str(home / "results" / "2.16.0"))
    real = os.path.realpath(home / "results" / "2.16.0")
    assert (inspection.location, inspection.source, inspection.name) == (real, "local", "2.16.0")
    assert inspection.looks_like_run is True
    assert inspection.markers == ["multiqc", "pipeline_info"]
    # Dot-entries are not visible, so not counted.
    assert inspection.folders.model_dump() == {
        "count": 4,
        "names": ["input", "multiqc", "pipeline_info", "qiime2"],
    }
    assert inspection.files.model_dump() == {"count": 1, "names": ["template.yaml"]}
    assert inspection.truncated is False
    assert inspection.detected is not None
    assert inspection.detected.model_dump() == {
        "template_id": "nf-core/ampliseq/2.16.0",
        "template_version": "2.16.0",
        "pipeline": "nf-core/ampliseq",
        "version": "2.16.0",
        "engine": "nextflow",
        "match": "exact",
    }


def test_inspect_a_run_of_an_unshipped_version_is_the_closest_match(home):
    write_tree(home / "run", _run_tree(version="v2.17.0"))
    detected = _inspect(str(home / "run")).detected
    assert detected is not None
    assert (detected.template_id, detected.template_version, detected.version) == (
        "nf-core/ampliseq/2.16.0",
        "2.16.0",
        "2.17.0",
    )
    assert detected.match == "closest"


def test_inspect_a_run_no_template_fits(home):
    write_tree(home / "run", _run_tree(version="1.0.0", pipeline="nf-core/nothing-ships"))
    detected = _inspect(str(home / "run")).detected
    assert detected is not None
    assert (detected.template_id, detected.template_version) == (None, None)
    assert (detected.pipeline, detected.match) == ("nf-core/nothing-ships", "none")


def test_inspect_a_folder_that_is_not_a_run(home):
    write_tree(home / "notes", {"a.txt": b"x", "sub/b.txt": b"y"})
    inspection = _inspect(str(home / "notes"))
    assert inspection.looks_like_run is False
    assert inspection.markers == []
    assert (inspection.folders.count, inspection.files.count) == (1, 1)
    assert inspection.detected is None


def test_inspect_without_detection_never_detects(home, monkeypatch):
    from depictio.cli.cli.utils import run_detection

    write_tree(home / "run", _run_tree())
    monkeypatch.setattr(
        run_detection, "detect_template_for_root", lambda _root: pytest.fail("detected")
    )
    inspection = _inspect(str(home / "run"), detect=False)
    assert inspection.looks_like_run is True
    assert inspection.detected is None


def test_inspect_hides_what_the_policy_hides(home, tmp_path):
    folder = home / "mixed"
    folder.mkdir()
    (folder / "pipeline_info").symlink_to(tmp_path)  # leaves the root: not a marker
    (folder / "depictio-local").symlink_to(home / "depictio-local")  # denied
    (folder / "alias").symlink_to(home / "depictio-local", target_is_directory=True)  # denied
    (folder / "ok").mkdir()
    inspection = _inspect(str(folder), detect=False)
    assert inspection.folders.names == ["ok"]
    assert inspection.looks_like_run is False


def test_inspect_names_are_capped_counts_are_not(home, monkeypatch):
    monkeypatch.setattr(run_folders, "MAX_NAMES", 2)
    write_tree(home / "many", {f"f{index}.txt": b"x" for index in range(5)})
    files = _inspect(str(home / "many"), detect=False).files
    assert files.model_dump() == {"count": 5, "names": ["f0.txt", "f1.txt"]}


def test_inspect_stops_at_the_entry_cap(home, monkeypatch):
    monkeypatch.setattr(run_folders, "MAX_INSPECT_ENTRIES", 3)
    write_tree(home / "many", {f"f{index}.txt": b"x" for index in range(5)})
    inspection = _inspect(str(home / "many"), detect=False)
    assert inspection.truncated is True
    assert inspection.files.count == 3


@pytest.mark.parametrize(
    ("rel", "code"),
    [
        ("../outside", "local_path_outside"),
        ("depictio-local", "local_path_denied"),
        (".ssh", "local_path_hidden"),
        ("nope", "local_path_missing"),
    ],
)
def test_inspect_and_find_runs_refuse_what_local_dirs_refuses(home, rel, code):
    (home / ".ssh").mkdir()
    (home.parent / "outside").mkdir()
    for fn in (_inspect, _find):
        refused = _coded(fn, f"{home}/{rel}")
        assert (refused.status_code, refused.code) == (404, code)


def test_local_locations_need_local_folders_on(tmp_path):
    for fn in (_inspect, _find):
        refused = _coded(fn, str(tmp_path))
        assert (refused.status_code, refused.code) == (404, "local_folders_off")


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"user": _user(is_admin=False)}, "local_admin_only"),
        ({"host": "evil.example:8058"}, "non_loopback_host"),
        ({"host": None}, "non_loopback_host"),
    ],
)
def test_local_locations_need_the_users_own_tab(home, kwargs, code):
    for fn in (_inspect, _find):
        refused = _coded(fn, str(home), **kwargs)
        assert (refused.status_code, refused.code) == (403, code)


@pytest.mark.parametrize("location", ["results/run1", "https://example.org/run1", "gs://b/run1"])
def test_another_kind_of_location_is_unsupported(location, home):
    for fn in (_inspect, _find):
        refused = _coded(fn, location)
        assert (refused.status_code, refused.code) == (422, "location_unsupported")
        assert refused.detail == run_folders.LOCATION_RULE_LOCAL


def test_without_local_folders_only_s3_is_offered():
    refused = _coded(_inspect, "results/run1")
    assert refused.detail == run_folders.LOCATION_RULE


# ── GET /projects/folder_inspect: S3 ─────────────────────────────────────────


def test_inspect_an_s3_run_folder(monkeypatch, listed):
    _serve(monkeypatch, {**_under("runs/2.16.0/", _run_tree()), "runs/2.16.0/": b""})
    inspection = _inspect(f"s3://{PUBLIC}/runs/2.16.0")
    assert (inspection.location, inspection.source, inspection.name) == (
        f"s3://{PUBLIC}/runs/2.16.0/",
        "s3",
        "2.16.0",
    )
    assert inspection.markers == ["multiqc", "pipeline_info"]
    assert inspection.folders.names == ["input", "multiqc", "pipeline_info", "qiime2"]
    # The folder's own zero-byte key is not a file in it.
    assert inspection.files.model_dump() == {"count": 1, "names": ["template.yaml"]}
    assert inspection.truncated is False
    assert inspection.detected is not None
    assert (inspection.detected.template_id, inspection.detected.match) == (
        "nf-core/ampliseq/2.16.0",
        "exact",
    )


def test_inspect_s3_without_detection_lists_one_page_and_one_below_multiqc(monkeypatch, listed):
    client = _serve(monkeypatch, _under("runs/r/", _run_tree()))
    inspection = _inspect(f"s3://{PUBLIC}/runs/r/", detect=False)
    assert inspection.detected is None
    assert client.listings == [
        {"Bucket": PUBLIC, "Prefix": "runs/r/", "Delimiter": "/"},
        {"Bucket": PUBLIC, "Prefix": "runs/r/multiqc/", "Delimiter": None},
    ]


def test_inspect_s3_truncated_page(monkeypatch, listed):
    _serve(monkeypatch, _under("runs/r/", _run_tree()), is_truncated=True)
    assert _inspect(f"s3://{PUBLIC}/runs/r/", detect=False).truncated is True


def test_inspect_s3_refusals(listed, no_client):
    for url in (f"s3://{INSTANCE}/x/", "s3://private-bucket/x/", f"s3://{PUBLIC}/"):
        with pytest.raises(S3AccessRefused):
            _inspect(url)


# ── GET /projects/find_runs: local ───────────────────────────────────────────


@pytest.fixture()
def tree(home, tmp_path):
    """Runs at several depths, with the entries a search must not go into."""
    base = home / "projects"
    write_tree(base / "a" / "run1", _run_tree())
    write_tree(base / "a" / "run1" / "sub" / "nested", {"multiqc/multiqc_report.html": b"x"})
    write_tree(base / "run0", {"multiqc/multiqc_report.html": b"x"})
    # Six levels down is searched, seven is not.
    write_tree(base / "b" / "c" / "d" / "e" / "f" / "run6", {"pipeline_info/p.json": b"{}"})
    write_tree(base / "b" / "c" / "d" / "e" / "f" / "g" / "run7", {"pipeline_info/p.json": b"{}"})
    write_tree(base / ".hidden" / "run_h", {"pipeline_info/p.json": b"{}"})
    write_tree(tmp_path / "outside" / "run_o", {"pipeline_info/p.json": b"{}"})
    (base / "escape").symlink_to(tmp_path / "outside")
    (base / "latest").symlink_to(base / "run0")
    write_tree(home / "depictio-local" / "run_x", {"pipeline_info/p.json": b"{}"})
    (base / "kept").symlink_to(home / "depictio-local")
    write_tree(base / "empty-folder", {"notes.txt": b"x"})
    return base


def test_find_runs_below_a_local_folder(tree):
    found = _find(str(tree))
    real = os.path.realpath(tree)
    assert found.location == real
    assert [(run.relative, run.name, run.markers) for run in found.runs] == [
        ("a/run1", "run1", ["multiqc", "pipeline_info"]),
        ("b/c/d/e/f/run6", "run6", ["pipeline_info"]),
        ("run0", "run0", ["multiqc"]),
    ]
    assert found.runs[0].location == os.path.join(real, "a", "run1")
    # g, six levels down, holds folders the search did not open (run7).
    assert found.truncated is True
    # projects, a, b, empty-folder, run0, run1, c, d, e, f, run6 and g (six
    # levels down, opened but not searched below): never a hidden, escaping or
    # denied folder, nothing below a run, run0 once although linked.
    assert found.scanned == 12


def test_find_runs_detects_the_first_runs(tree, monkeypatch):
    found = _find(str(tree))
    by_relative = {run.relative: run for run in found.runs}
    assert by_relative["a/run1"].detected is not None
    assert by_relative["a/run1"].detected.match == "exact"
    # Recognised by no engine: no versions, no params, no manifest.
    assert by_relative["run0"].detected is None

    from depictio.cli.cli.utils import run_detection

    seen = []
    monkeypatch.setattr(
        run_detection,
        "detect_template_for_root",
        lambda root: seen.append(root.location) or (None, None),
    )
    monkeypatch.setattr(run_folders, "FIND_DETECT_RUNS", 1)
    _find(str(tree))
    assert seen == [os.path.realpath(tree / "a" / "run1")]


def test_find_runs_within_the_depth_is_complete(tree):
    found = _find(str(tree / "b" / "c"))
    assert [run.relative for run in found.runs] == ["d/e/f/g/run7", "d/e/f/run6"]
    assert found.truncated is False


def test_find_runs_on_a_run_is_that_run(tree):
    found = _find(str(tree / "a" / "run1"))
    assert [(run.relative, run.name) for run in found.runs] == [(".", "run1")]
    assert found.scanned == 1


def test_find_runs_stops_at_the_folder_cap(tree, monkeypatch):
    monkeypatch.setattr(run_folders, "FIND_MAX_DIRS", 3)
    found = _find(str(tree))
    assert found.truncated is True
    assert found.scanned <= 3


def test_find_runs_stops_at_the_run_cap(tree, monkeypatch):
    monkeypatch.setattr(run_folders, "FIND_MAX_RUNS", 2)
    found = _find(str(tree))
    assert [run.relative for run in found.runs] == ["a/run1", "b/c/d/e/f/run6"]
    assert found.truncated is True


def test_find_runs_skips_lookalikes_noise_and_nextflow_work(home):
    base = home / "search"
    write_tree(base / "catalog", {"multiqc/fastqc.yaml": b"x", "multiqc/bowtie2/recipe.yaml": b"x"})
    write_tree(base / "rnaseq", {"multiqc/star_salmon/multiqc_report.html": b"<html>"})
    write_tree(
        base / "work",
        {
            "3f/a1b2c3/multiqc/multiqc_data/multiqc.parquet": b"PAR1",
            "ab/d4e5f6/pipeline_info/p.json": b"{}",
            "stage-0b1c/x/pipeline_info/p.json": b"{}",
        },
    )
    write_tree(base / "node_modules" / "pkg", {"pipeline_info/p.json": b"{}"})
    write_tree(base / "__pycache__" / "x", {"pipeline_info/p.json": b"{}"})
    # A folder named work that is not Nextflow's is searched like any other.
    write_tree(base / "mine" / "work", {"notes/pipeline_info/p.json": b"{}"})

    found = _find(str(base))
    assert [(run.relative, run.markers) for run in found.runs] == [
        ("mine/work/notes", ["pipeline_info"]),
        ("rnaseq", ["multiqc"]),
    ]
    assert found.truncated is False
    # search, catalog, mine, rnaseq, work (opened, not searched below),
    # catalog/multiqc, mine/work, catalog/multiqc/bowtie2 and mine/work/notes.
    assert found.scanned == 9


@pytest.mark.parametrize(
    ("name", "folder_names", "is_work"),
    [
        ("work", ["3f", "a0"], True),
        ("work", ["3f", "stage-1a2b", "conda", "singularity"], True),
        ("work", ["3f", "notes"], False),
        ("work", ["3F"], False),
        ("work", ["stage-1a2b"], False),
        ("work", [], False),
        ("results", ["3f", "a0"], False),
    ],
)
def test_is_nextflow_work(name, folder_names, is_work):
    assert run_folders._is_nextflow_work(name, folder_names) is is_work


def test_find_runs_lists_nothing_in_an_unreadable_folder(tree, monkeypatch):
    def _denied(_path):
        raise PermissionError("no")

    monkeypatch.setattr(run_folders.os, "scandir", _denied)
    found = _find(str(tree))
    assert (found.runs, found.scanned, found.truncated) == ([], 1, False)


# ── GET /projects/find_runs: S3 ──────────────────────────────────────────────


FIND_KEYS = {
    "runs/a/run1/pipeline_info/params.json": b"{}",
    "runs/a/run1/multiqc/multiqc_data/x.parquet": b"PAR1",
    "runs/a/run1/sub/pipeline_info/p.json": b"{}",
    "runs/b/multiqc/star_salmon/multiqc_report.html": b"<html>",
    "runs/c/data.csv": b"x",
    "runs/catalog/multiqc/fastqc.yaml": b"x",
    "runs/multiqc": b"a file, not a folder",
    "runs/d/e/f/pipeline_info/": b"",
    "runs/work/3f/a1b2c3/pipeline_info/p.json": b"{}",
}


def test_find_runs_below_an_s3_prefix(monkeypatch, listed):
    client = _serve(monkeypatch, FIND_KEYS)
    found = _find(f"s3://{PUBLIC}/runs")
    assert found.location == f"s3://{PUBLIC}/runs/"
    assert [(run.relative, run.name, run.markers, run.location) for run in found.runs] == [
        ("a/run1", "run1", ["multiqc", "pipeline_info"], f"s3://{PUBLIC}/runs/a/run1/"),
        ("b", "b", ["multiqc"], f"s3://{PUBLIC}/runs/b/"),
        ("d/e/f", "f", ["pipeline_info"], f"s3://{PUBLIC}/runs/d/e/f/"),
    ]
    assert all(run.detected is None for run in found.runs)
    assert (found.scanned, found.truncated) == (len(FIND_KEYS), False)
    # One listing, of keys: no delimiter.
    assert client.listings == [{"Bucket": PUBLIC, "Prefix": "runs/", "Delimiter": None}]


@pytest.mark.parametrize(
    ("key", "run"),
    [
        ("r/pipeline_info/params.json", ("r", "pipeline_info")),
        ("a/b/pipeline_info/", ("a/b", "pipeline_info")),
        ("r/multiqc/multiqc_data/multiqc.parquet", ("r", "multiqc")),
        ("r/multiqc/multiqc_data/", ("r", "multiqc")),
        ("r/multiqc/multiqc.parquet", ("r", "multiqc")),
        ("r/multiqc/multiqc_report.html", ("r", "multiqc")),
        ("r/multiqc/Project_42_multiqc_report.html", ("r", "multiqc")),
        ("r/multiqc/star_salmon/multiqc_report.html", ("r", "multiqc")),
        ("r/multiqc/star_salmon/multiqc_report_data/multiqc.parquet", ("r", "multiqc")),
        ("multiqc/fastqc/multiqc_data/x.txt", ("", "multiqc")),
        # Not MultiQC output: recipes, a deeper report, a lookalike, a file.
        ("catalog/multiqc/fastqc.yaml", None),
        ("catalog/multiqc/bowtie2/recipe.yaml", None),
        ("r/multiqc/a/b/multiqc_report.html", None),
        ("r/multiqc/report.html", None),
        ("r/multiqc/multiqc_data", None),
        ("r/multiqc/", None),
        ("r/pipeline_info", None),
        # Below a Nextflow task folder: no run's.
        ("work/3f/a1b2c3/multiqc/multiqc_data/multiqc.parquet", None),
        ("launch/work/ab/c3d4/pipeline_info/p.json", None),
        ("work/3f/", None),
        # A work folder whose next segment is no task folder is read as any other.
        ("work/notes/pipeline_info/p.json", ("work/notes", "pipeline_info")),
    ],
)
def test_run_of(key, run):
    assert run_folders._run_of(key) == run


def test_find_runs_on_an_s3_run_is_that_run(monkeypatch, listed):
    _serve(monkeypatch, FIND_KEYS)
    found = _find(f"s3://{PUBLIC}/runs/a/run1/")
    assert [(run.relative, run.name) for run in found.runs] == [(".", "run1")]


def test_find_runs_stops_at_the_key_cap(monkeypatch, listed):
    monkeypatch.setattr(run_folders, "FIND_MAX_KEYS", 2)
    _serve(monkeypatch, FIND_KEYS, page_size=1)
    found = _find(f"s3://{PUBLIC}/runs/")
    assert (found.scanned, found.truncated) == (2, True)


def test_find_runs_a_listing_that_ends_on_the_cap_is_complete(monkeypatch, listed):
    monkeypatch.setattr(run_folders, "FIND_MAX_KEYS", len(FIND_KEYS))
    _serve(monkeypatch, FIND_KEYS, is_truncated=False)
    assert _find(f"s3://{PUBLIC}/runs/").truncated is False


def test_find_runs_s3_run_cap(monkeypatch, listed):
    monkeypatch.setattr(run_folders, "FIND_MAX_RUNS", 1)
    _serve(monkeypatch, FIND_KEYS)
    found = _find(f"s3://{PUBLIC}/runs/")
    assert [run.relative for run in found.runs] == ["a/run1"]
    assert found.truncated is True


def test_find_runs_s3_refusals(listed, no_client):
    for url in (f"s3://{INSTANCE}/x/", "s3://private-bucket/x/", f"s3://{PUBLIC}/"):
        with pytest.raises(S3AccessRefused):
            _find(url)


# ── the detection summary ────────────────────────────────────────────────────


def _info(version: str | None, raw: str | None = None, pipeline: str | None = "nf-core/ampliseq"):
    extra = {"pipeline_version_raw": raw} if raw else {}
    return WorkflowRunInfo(
        engine="nextflow", pipeline_name=pipeline, pipeline_version=version, extra=extra
    )


@pytest.mark.parametrize(
    ("template_id", "info", "match"),
    [
        ("nf-core/ampliseq/2.16.0", _info("2.16.0"), "exact"),
        # A template directory named after the version as the engine wrote it.
        ("nf-core/ampliseq/v2.16.0-g3d5", _info("2.16.0", raw="v2.16.0-g3d5"), "exact"),
        ("nf-core/ampliseq/2.16.0", _info("2.17.0"), "closest"),
        (None, _info("2.17.0", pipeline="nf-core/unknown"), "none"),
        (None, _info(None, pipeline=None), "none"),
    ],
)
def test_describe_detection(template_id, info, match):
    detected = from_run.describe_detection(template_id, info)
    assert detected is not None
    assert detected.match == match
    assert detected.template_version == (template_id.rsplit("/", 1)[-1] if template_id else None)


def test_no_engine_recognised_is_no_detection():
    assert from_run.describe_detection(None, None) is None


# ── the routes ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_routes_need_a_user():
    for call in (
        routes.get_s3_dirs(url=None, current_user=None),
        routes.get_folder_inspect(_request(), location="/x", detect=True, current_user=None),
        routes.get_find_runs(_request(), location="/x", current_user=None),
    ):
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_the_routes_answer_a_coded_refusal_with_detail_and_code(home):
    for call in (
        routes.get_folder_inspect(
            _request("evil.example"), location=str(home), detect=True, current_user=_user()
        ),
        routes.get_find_runs(_request("evil.example"), location=str(home), current_user=_user()),
    ):
        response = await call
        assert response.status_code == 403
        body = json.loads(response.body)
        assert body == {"detail": body["detail"], "code": "non_loopback_host"}


@pytest.mark.asyncio
async def test_the_routes_answer(home, monkeypatch, listed):
    write_tree(home / "run", _run_tree())
    inspection = await routes.get_folder_inspect(
        _request(), location=str(home / "run"), detect=False, current_user=_user()
    )
    assert inspection.looks_like_run is True
    found = await routes.get_find_runs(_request(), location=str(home), current_user=_user())
    assert [run.relative for run in found.runs] == ["run"]
    listing = await routes.get_s3_dirs(url=None, current_user=_user(is_admin=False))
    assert [e.name for e in listing.entries] == [f"{PUBLIC}/runs", LAB]


@pytest.mark.asyncio
async def test_an_s3_refusal_reaches_the_api_handler_coded(listed, no_client):
    from depictio.api.main import s3_access_exception_handler

    with pytest.raises(S3AccessRefused) as exc:
        await routes.get_s3_dirs(url=f"s3://{INSTANCE}/", current_user=_user())
    response = await s3_access_exception_handler(None, exc.value)
    assert response.status_code == 422
    assert json.loads(response.body)["code"] == "s3_refused"
