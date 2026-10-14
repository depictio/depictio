"""Writing the template where ``depictio ingest --template`` reads it."""

from __future__ import annotations

import hashlib
import os
import shlex
from pathlib import Path

import pytest
import yaml

from depictio.project_builder import bundle
from depictio.project_builder.assemble import build_template, template_yaml
from depictio.project_builder.bundle import default_bundle_dir, ingest_command, write_bundle
from depictio.project_builder.errors import BuilderRefused

from ._fixtures import project, scan_dc, table_dc


@pytest.fixture
def template() -> dict:
    return build_template(project(table_dc(), scan_dc(), name="Lab Run"))


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """A home folder of the test's own, for the fallback bundle location."""
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    return folder


# ── write_bundle ─────────────────────────────────────────────────────────────


class TestWriteBundle:
    def test_it_writes_the_template_and_says_how_to_ingest_it(self, tmp_path, template):
        out = tmp_path / "bundle"
        written = write_bundle(template, out, data_root="/data/run1")
        path = out / "template.yaml"
        assert set(written) == {"path", "yaml", "ingest_command", "watch_command"}
        assert written["path"] == str(path)
        assert path.read_text() == written["yaml"] == template_yaml(template)
        assert yaml.safe_load(path.read_text()) == template
        assert written["ingest_command"] == f"depictio ingest /data/run1 --template {path}"
        assert written["watch_command"] == f"depictio watch /data/run1 --template {path}"
        assert not (out / "template.yaml.bak").exists()

    def test_a_remote_root_is_named_as_given(self, tmp_path, template):
        written = write_bundle(template, tmp_path, data_root="s3://bucket/run1")
        assert written["ingest_command"].startswith("depictio ingest s3://bucket/run1 --template ")

    def test_missing_folders_are_made(self, tmp_path, template):
        out = tmp_path / "a" / "b" / "c"
        write_bundle(template, out, data_root="/d")
        assert (out / "template.yaml").is_file()

    def test_the_file_is_not_replaced_unless_asked(self, tmp_path, template):
        out = tmp_path / "bundle"
        write_bundle(template, out, data_root="/d")
        path = out / "template.yaml"
        path.write_text("# edited by hand\n")
        with pytest.raises(BuilderRefused) as exc:
            write_bundle(template, out, data_root="/d")
        assert (exc.value.status, exc.value.code) == (409, "bundle_exists")
        assert str(path) in exc.value.detail
        assert path.read_text() == "# edited by hand\n"
        assert not (out / "template.yaml.bak").exists()

    def test_overwriting_keeps_the_previous_file_next_to_it(self, tmp_path, template):
        out = tmp_path / "bundle"
        write_bundle(template, out, data_root="/d")
        path = out / "template.yaml"
        path.write_text("# edited by hand\n")

        written = write_bundle(template, out, data_root="/d", overwrite=True)

        assert (out / "template.yaml.bak").read_text() == "# edited by hand\n"
        assert path.read_text() == written["yaml"] == template_yaml(template)

    def test_only_the_latest_previous_file_is_kept(self, tmp_path, template):
        out = tmp_path / "bundle"
        path = out / "template.yaml"
        write_bundle(template, out, data_root="/d")
        for generation in ("one", "two"):
            path.write_text(f"# {generation}\n")
            write_bundle(template, out, data_root="/d", overwrite=True)
        assert (out / "template.yaml.bak").read_text() == "# two\n"

    def test_overwrite_on_a_fresh_folder_just_writes(self, tmp_path, template):
        out = tmp_path / "bundle"
        write_bundle(template, out, data_root="/d", overwrite=True)
        assert (out / "template.yaml").is_file()
        assert not (out / "template.yaml.bak").exists()

    def test_a_folder_that_cannot_be_made_is_a_500_with_the_reason(self, tmp_path, template):
        blocker = tmp_path / "blocker"
        blocker.write_text("a file where the folder should go")
        with pytest.raises(BuilderRefused) as exc:
            write_bundle(template, blocker / "bundle", data_root="/d")
        assert (exc.value.status, exc.value.code) == (500, "bundle_unwritable")
        assert exc.value.detail.startswith("Could not write ")

    def test_a_file_that_cannot_be_written_is_a_500(self, tmp_path, template, monkeypatch):
        def refuse(self, *args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "write_text", refuse)
        with pytest.raises(BuilderRefused) as exc:
            write_bundle(template, tmp_path, data_root="/d")
        assert (exc.value.status, exc.value.code) == (500, "bundle_unwritable")
        assert "Permission denied" in exc.value.detail

    def test_the_ingest_command_is_one_line(self):
        assert ingest_command("/data/run1", Path("/b/template.yaml")) == (
            "depictio ingest /data/run1 --template /b/template.yaml"
        )

    def test_the_ingest_command_of_plain_paths_pastes_into_a_shell_as_it_reads(self):
        command = ingest_command("/data/run1", Path("/b/template.yaml"))
        assert shlex.split(command) == [
            "depictio",
            "ingest",
            "/data/run1",
            "--template",
            "/b/template.yaml",
        ]

    @pytest.mark.parametrize("data_root", ["/data/my run", "/data/run1; echo pwned", "/d/$(id)"])
    def test_the_ingest_command_quotes_what_a_shell_would_split(self, data_root):
        command = ingest_command(data_root, Path("/b dir/template.yaml"))
        assert shlex.split(command) == [
            "depictio",
            "ingest",
            data_root,
            "--template",
            "/b dir/template.yaml",
        ]

    def test_the_file_name_is_template_yaml(self):
        assert bundle.BUNDLE_FILE == "template.yaml"


# ── where the bundle goes ────────────────────────────────────────────────────


class TestDefaultBundleDir:
    def test_a_writable_root_keeps_its_bundle_inside(self, tmp_path, home):
        assert default_bundle_dir(tmp_path, "Lab Run") == tmp_path / ".depictio" / "template"

    def test_an_existing_bundle_folder_is_the_one_asked_about(self, tmp_path, home):
        (tmp_path / ".depictio" / "template").mkdir(parents=True)
        assert default_bundle_dir(tmp_path, "Lab Run") == tmp_path / ".depictio" / "template"

    def test_a_root_that_does_not_exist_yet_is_judged_by_its_nearest_parent(self, tmp_path, home):
        target = tmp_path / "not" / "made" / "yet"
        assert default_bundle_dir(target, "Lab Run") == target / ".depictio" / "template"

    def _unwritable(self, monkeypatch, *folders: Path):
        """``os.access`` says no to ``folders``: a read-only results folder, also as root."""
        real = os.access
        blocked = {str(folder) for folder in folders}

        def access(path, mode, *args, **kwargs):
            if str(path) in blocked and mode & os.W_OK:
                return False
            return real(path, mode, *args, **kwargs)

        monkeypatch.setattr(bundle.os, "access", access)

    def test_a_read_only_root_falls_back_to_a_folder_under_the_home(
        self, tmp_path, home, monkeypatch
    ):
        shared = tmp_path / "shared-results"
        shared.mkdir()
        self._unwritable(monkeypatch, shared)

        chosen = default_bundle_dir(shared, "Lab Run")

        digest = hashlib.sha256(str(shared.resolve()).encode()).hexdigest()[:8]
        assert chosen == home / ".depictio" / "builder" / f"lab_run-{digest}"
        assert not str(chosen).startswith(str(shared))

    def test_the_fallback_is_stable_per_root_and_apart_between_roots(
        self, tmp_path, home, monkeypatch
    ):
        first, second = tmp_path / "one", tmp_path / "two"
        first.mkdir()
        second.mkdir()
        self._unwritable(monkeypatch, first, second)
        a1 = default_bundle_dir(first, "Run")
        assert default_bundle_dir(first, "Run") == a1
        assert default_bundle_dir(second, "Run") != a1

    def test_the_name_is_slugged_and_cut_for_the_folder_name(self, tmp_path, home, monkeypatch):
        shared = tmp_path / "shared"
        shared.mkdir()
        self._unwritable(monkeypatch, shared)
        chosen = default_bundle_dir(shared, "Lab Run / 2026! " + "x" * 100)
        assert chosen.parent == home / ".depictio" / "builder"
        slug, _, digest = chosen.name.rpartition("-")
        assert slug.startswith("lab_run_2026_") and len(slug) <= 40
        assert len(digest) == 8

    def test_an_existing_bundle_in_a_read_only_root_is_judged_by_that_folder(
        self, tmp_path, home, monkeypatch
    ):
        shared = tmp_path / "shared"
        inside = shared / ".depictio" / "template"
        inside.mkdir(parents=True)
        self._unwritable(monkeypatch, inside)
        assert default_bundle_dir(shared, "Run").parent == home / ".depictio" / "builder"

    def test_a_real_read_only_folder(self, tmp_path, home):
        shared = tmp_path / "shared-results"
        shared.mkdir()
        shared.chmod(0o555)
        try:
            if os.access(shared, os.W_OK):
                pytest.skip("this user can write to a read-only folder (running as root)")
            chosen = default_bundle_dir(shared, "Lab Run")
            assert chosen.parent == home / ".depictio" / "builder"
        finally:
            shared.chmod(0o755)

    def test_a_bundle_can_then_be_written_at_the_fallback(
        self, tmp_path, home, monkeypatch, template
    ):
        shared = tmp_path / "shared"
        shared.mkdir()
        self._unwritable(monkeypatch, shared)
        out = default_bundle_dir(shared, "Lab Run")
        written = write_bundle(template, out, data_root=str(shared))
        assert Path(written["path"]).is_file()
        assert str(home) in written["path"]
