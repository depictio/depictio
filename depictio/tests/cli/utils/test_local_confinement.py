"""The read paths stay inside the allowed folders when a server reads its own disk.

With local folders on (server context, single-user mode, ``DEPICTIO_LOCAL_DATA_ROOTS``)
a run folder is the user's, but what it links to is not necessarily data: a
symlink out of the allowed roots, into a hidden folder or into a folder Depictio
keeps for itself is skipped by the scan, refused at read time, and invisible to
the data root the recipes read through. With local folders off nothing changes.
"""

import os
import tempfile
from types import SimpleNamespace

import pytest
from bson import ObjectId

from depictio.cli.cli.utils import deltatables, scan
from depictio.cli.cli.utils.data_root import LocalDataRoot
from depictio.models.local_access import LocalPathRefused
from depictio.models.models.users import Permission, UserBase


@pytest.fixture()
def run_folder(tmp_path, monkeypatch):
    """``home/run42`` with a table, a hidden table, a link out and a link in; the
    ``outside/`` folder it links to; the server's temp dir somewhere else again.

    The server's own temp dir is readable by design (uploads land there), and
    pytest's ``tmp_path`` is inside it, so the test gives the server its own.
    """
    home = tmp_path / "home"
    run = home / "run42"
    (run / "tables").mkdir(parents=True)
    (run / "tables" / "counts.csv").write_text("sample,n\nS1,1\n")
    (run / ".hidden").mkdir()
    (run / ".hidden" / "secret.csv").write_text("sample,n\nS1,9\n")
    (run / "sample_1").mkdir()
    (run / "sample_2").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "stolen.csv").write_text("sample,n\nS1,7\n")
    (outside / "sample_3").mkdir()
    (run / "tables" / "escape.csv").symlink_to(outside / "stolen.csv")
    (run / "sample_3").symlink_to(outside / "sample_3")
    (run / "tables" / "alias.csv").symlink_to(run / "tables" / "counts.csv")

    server_tmp = tmp_path / "server-tmp"
    server_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(server_tmp))
    monkeypatch.setenv("TMPDIR", str(server_tmp))
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS", raising=False)
    monkeypatch.delenv("DEPICTIO_AUTH_SINGLE_USER_MODE", raising=False)
    return SimpleNamespace(home=home, run=run, outside=outside, server_tmp=server_tmp)


@pytest.fixture()
def local_on(run_folder, monkeypatch):
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(run_folder.home))
    return run_folder


# ── LocalDataRoot ────────────────────────────────────────────────────────────


def test_the_data_root_hides_what_leaves_the_allowed_folders(local_on):
    root = LocalDataRoot(str(local_on.run))
    assert root.glob("tables/*.csv") == ["tables/alias.csv", "tables/counts.csv"]
    assert root.glob("**/*.csv") == ["tables/alias.csv", "tables/counts.csv"]
    assert root.match(r".*\.csv") == ["tables/alias.csv", "tables/counts.csv"]
    assert root.exists("tables/counts.csv")
    assert not root.exists("tables/escape.csv")
    assert not root.exists(".hidden/secret.csv")
    assert root.runs(r"sample_\d") == ["sample_1", "sample_2"]


def test_dot_dot_in_a_glob_does_not_reach_out(local_on):
    root = LocalDataRoot(str(local_on.run))
    assert root.glob("../../outside/*.csv") == []
    assert not root.exists("../../outside/stolen.csv")


def test_the_data_root_refuses_to_read_what_leaves(local_on):
    root = LocalDataRoot(str(local_on.run))
    assert root.read_bytes("tables/counts.csv").startswith(b"sample")
    with pytest.raises(LocalPathRefused) as exc:
        root.read_bytes("tables/escape.csv")
    assert exc.value.code == "local_path_outside"
    assert str(local_on.outside) not in str(exc.value)
    with pytest.raises(LocalPathRefused):
        root.read_bytes(".hidden/secret.csv")


def test_without_local_folders_the_data_root_is_unchanged(run_folder):
    root = LocalDataRoot(str(run_folder.run))
    assert "tables/escape.csv" in root.glob("tables/*.csv")
    assert root.exists(".hidden/secret.csv")
    assert root.read_bytes("tables/escape.csv").startswith(b"sample")
    assert root.runs(r"sample_\d") == ["sample_1", "sample_2", "sample_3"]


# ── the scan ─────────────────────────────────────────────────────────────────


def _scan_one(path: str):
    return scan.scan_single_file(
        file_location=path,
        run=SimpleNamespace(id=ObjectId(), run_tag="run42"),
        data_collection=SimpleNamespace(id=ObjectId()),
        permissions=Permission(owners=[UserBase(id=ObjectId(), email="me@example.com")]),
        existing_files={},
        update_files=False,
        skip_regex=True,
    )


def test_the_scan_skips_a_match_that_leaves(local_on):
    assert _scan_one(str(local_on.run / "tables" / "escape.csv")) is None
    assert _scan_one(str(local_on.run / ".hidden" / "secret.csv")) is None
    kept = _scan_one(str(local_on.run / "tables" / "counts.csv"))
    assert kept is not None
    assert kept.file.file_location == os.path.realpath(local_on.run / "tables" / "counts.csv")


def test_the_scan_still_reads_the_servers_own_uploads(local_on):
    upload = local_on.server_tmp / "depictio_upload_x" / "table.csv"
    upload.parent.mkdir()
    upload.write_text("a,b\n1,2\n")
    assert _scan_one(str(upload)) is not None


def test_the_recursive_walk_registers_only_what_stays(local_on):
    results = scan.process_files(
        path=str(local_on.run / "tables"),
        run=SimpleNamespace(id=ObjectId(), run_tag="run42"),
        data_collection=SimpleNamespace(id=ObjectId()),
        permissions=Permission(owners=[UserBase(id=ObjectId(), email="me@example.com")]),
        existing_files={},
        skip_regex=True,
    )
    # The in-root alias resolves to counts.csv, the escape is skipped.
    locations = sorted(result.file.file_location for result in results)
    real_counts = os.path.realpath(local_on.run / "tables" / "counts.csv")
    assert locations == [real_counts, real_counts]


def test_without_local_folders_the_scan_is_unchanged(run_folder):
    kept = _scan_one(str(run_folder.run / "tables" / "escape.csv"))
    assert kept is not None
    assert kept.file.file_location == os.path.realpath(run_folder.outside / "stolen.csv")


# ── the read ─────────────────────────────────────────────────────────────────


def test_a_read_outside_is_refused_whatever_registered_it(local_on):
    stolen = str(local_on.outside / "stolen.csv")
    with pytest.raises(LocalPathRefused) as exc:
        deltatables._lazy_scan_path(stolen, "csv", {})
    assert exc.value.code == "local_path_outside"
    frame = deltatables._lazy_scan_path(str(local_on.run / "tables" / "counts.csv"), "csv", {})
    assert frame.collect().height == 1


def test_a_file_the_process_wrote_itself_is_read_unconfined(local_on):
    stolen = str(local_on.outside / "stolen.csv")
    assert deltatables._lazy_scan_path(stolen, "csv", {}, confine=False).collect().height == 1


def test_read_single_file_lazy_fails_on_a_refused_file(local_on):
    file_info = SimpleNamespace(
        file_location=str(local_on.outside / "stolen.csv"), run_tag="run42", manifest_id=None
    )
    with pytest.raises(Exception, match="outside the folders this server may read"):
        deltatables.read_single_file_lazy(file_info, "csv", {})


def test_without_local_folders_the_read_is_unchanged(run_folder):
    stolen = str(run_folder.outside / "stolen.csv")
    assert deltatables._lazy_scan_path(stolen, "csv", {}).collect().height == 1
