"""scripts/update_template_lock.py: a template changed without a version bump fails.

The script is exercised on tmp trees only. The last class holds the real
``depictio/projects`` tree to its lock, and skips while there is none.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "update_template_lock.py"
_PROJECTS = Path(__file__).resolve().parents[2] / "projects"


@pytest.fixture(scope="module")
def lock() -> ModuleType:
    spec = importlib.util.spec_from_file_location("update_template_lock_under_test", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # A dataclass resolves its string annotations through sys.modules.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def _template(root: Path, template_id: str, version: str = "1.0.0", dashboard: str = "a") -> Path:
    template_dir = root / template_id
    (template_dir / "dashboards").mkdir(parents=True)
    (template_dir / "template.yaml").write_text(
        f'template:\n  template_id: "{template_id}"\n  version: "{version}"\n'
    )
    (template_dir / "dashboards" / "base.yaml").write_text(f"title: {dashboard}\n")
    return template_dir


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """Two versions of one pipeline sharing recipes, and a lone template."""
    root = tmp_path / "projects"
    _template(root, "nf-core/demo/1.0.0")
    _template(root, "nf-core/demo/2.0.0")
    _template(root, "init/solo")
    recipes = root / "nf-core" / "demo" / "recipes"
    recipes.mkdir()
    (recipes / "table.py").write_text("SOURCES = []\n")
    return root


def _write(lock: ModuleType, root: Path) -> Path:
    path = root / lock.LOCK_NAME
    assert lock.main(["--write", "--projects-dir", str(root)]) == 0
    return path


def _check(lock: ModuleType, root: Path, *extra: str) -> int:
    return lock.main(["--check", "--projects-dir", str(root), *extra])


class TestDiscovery:
    def test_templates_are_found_by_their_directory(self, lock: ModuleType, tree: Path) -> None:
        assert sorted(lock.discover_templates(tree)) == [
            "init/solo",
            "nf-core/demo/1.0.0",
            "nf-core/demo/2.0.0",
        ]

    def test_caches_and_seeds_are_not_templates(self, lock: ModuleType, tree: Path) -> None:
        for noise in ("__pycache__", ".db_seeds"):
            (tree / "init" / "solo" / noise).mkdir()
            (tree / "init" / "solo" / noise / "template.yaml").write_text("template: {}\n")

        assert "init/solo/__pycache__" not in lock.discover_templates(tree)
        assert "init/solo/.db_seeds" not in lock.discover_templates(tree)

    def test_a_nested_template_is_its_own_entry(self, lock: ModuleType, tree: Path) -> None:
        _template(tree, "nf-core/demo/2.0.0/categories/sub")

        assert "nf-core/demo/2.0.0/categories/sub" in lock.discover_templates(tree)


class TestContentHash:
    def _hash(self, lock: ModuleType, root: Path, template_id: str) -> str:
        return lock.content_hash(root, root / template_id)

    def test_it_is_stable(self, lock: ModuleType, tree: Path) -> None:
        assert self._hash(lock, tree, "init/solo") == self._hash(lock, tree, "init/solo")

    @pytest.mark.parametrize(
        "relative",
        ["template.yaml", "dashboards/base.yaml"],
    )
    def test_a_covered_file_moves_it(self, lock: ModuleType, tree: Path, relative: str) -> None:
        before = self._hash(lock, tree, "init/solo")

        path = tree / "init" / "solo" / relative
        path.write_text(path.read_text() + "# edit\n")

        assert self._hash(lock, tree, "init/solo") != before

    def test_a_new_dashboard_moves_it(self, lock: ModuleType, tree: Path) -> None:
        before = self._hash(lock, tree, "init/solo")

        (tree / "init" / "solo" / "dashboards" / "extra.yaml").write_text("title: b\n")

        assert self._hash(lock, tree, "init/solo") != before

    def test_the_shared_recipes_move_every_version_of_the_pipeline(
        self, lock: ModuleType, tree: Path
    ) -> None:
        before = [self._hash(lock, tree, f"nf-core/demo/{v}") for v in ("1.0.0", "2.0.0")]
        solo = self._hash(lock, tree, "init/solo")

        (tree / "nf-core" / "demo" / "recipes" / "table.py").write_text("SOURCES = [1]\n")

        after = [self._hash(lock, tree, f"nf-core/demo/{v}") for v in ("1.0.0", "2.0.0")]
        assert all(a != b for a, b in zip(before, after, strict=True))
        assert self._hash(lock, tree, "init/solo") == solo

    def test_a_version_override_recipe_moves_only_its_version(
        self, lock: ModuleType, tree: Path
    ) -> None:
        other = self._hash(lock, tree, "nf-core/demo/1.0.0")
        before = self._hash(lock, tree, "nf-core/demo/2.0.0")

        override = tree / "nf-core" / "demo" / "2.0.0" / "recipes"
        override.mkdir()
        (override / "table.py").write_text("SOURCES = []\n")

        assert self._hash(lock, tree, "nf-core/demo/2.0.0") != before
        assert self._hash(lock, tree, "nf-core/demo/1.0.0") == other

    def test_docs_data_seeds_and_caches_do_not_count(self, lock: ModuleType, tree: Path) -> None:
        before = self._hash(lock, tree, "init/solo")
        solo = tree / "init" / "solo"

        (solo / "docs").mkdir()
        (solo / "docs" / "dashboards.md").write_text("prose\n")
        (solo / "megatest.yaml").write_text("pipeline: demo\n")
        (solo / "input").mkdir()
        (solo / "input" / "counts.tsv").write_text("a\tb\n")
        (solo / "dashboards" / ".db_seeds").mkdir()
        (solo / "dashboards" / ".db_seeds" / "base.json").write_text("{}")
        (solo / "dashboards" / "__pycache__").mkdir()
        (solo / "dashboards" / "__pycache__" / "x.yaml").write_text("x: 1\n")
        (tree / "nf-core" / "demo" / "recipes" / "__pycache__").mkdir()
        (tree / "nf-core" / "demo" / "recipes" / "__pycache__" / "table.pyc").write_bytes(b"\0")

        assert self._hash(lock, tree, "init/solo") == before

    def test_line_endings_do_not_count(self, lock: ModuleType, tree: Path) -> None:
        path = tree / "init" / "solo" / "dashboards" / "base.yaml"
        path.write_bytes(b"title: a\ndescription: b\n")
        unix = self._hash(lock, tree, "init/solo")

        path.write_bytes(b"title: a\r\ndescription: b\r\n")

        assert self._hash(lock, tree, "init/solo") == unix

    def test_it_does_not_depend_on_where_the_tree_is(
        self, lock: ModuleType, tree: Path, tmp_path: Path
    ) -> None:
        moved = tmp_path / "elsewhere" / "deep" / "projects"
        moved.parent.mkdir(parents=True)
        tree.rename(moved)

        assert lock.compute(moved)["init/solo"]["version"] == "1.0.0"
        fresh = tmp_path / "again"
        _template(fresh, "init/solo")
        assert (
            lock.compute(moved)["init/solo"]["content_hash"]
            == lock.compute(fresh)["init/solo"]["content_hash"]
        )


class TestCheck:
    def test_an_unchanged_tree_passes(
        self, lock: ModuleType, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(lock, tree)

        assert _check(lock, tree) == 0
        assert "match the lock" in capsys.readouterr().out

    def test_no_lock_yet_passes_with_a_note_unless_required(
        self, lock: ModuleType, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _check(lock, tree) == 0
        assert "--write" in capsys.readouterr().out
        assert _check(lock, tree, "--require-lock") == 1

    def test_a_change_without_a_bump_fails_and_says_what_to_do(
        self, lock: ModuleType, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(lock, tree)
        (tree / "init" / "solo" / "dashboards" / "base.yaml").write_text("title: changed\n")

        assert _check(lock, tree) == 1

        out = capsys.readouterr().out
        assert "init/solo: content changed but template.version is still 1.0.0" in out
        assert "Bump `template.version`" in out
        assert "update_template_lock.py --write" in out
        assert "nf-core/demo" not in out

    def test_a_shared_recipe_change_names_every_version_it_reaches(
        self, lock: ModuleType, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(lock, tree)
        (tree / "nf-core" / "demo" / "recipes" / "table.py").write_text("SOURCES = [1]\n")

        assert _check(lock, tree) == 1

        out = capsys.readouterr().out
        assert "nf-core/demo/1.0.0" in out and "nf-core/demo/2.0.0" in out

    def test_a_bump_with_the_lock_not_refreshed_fails_until_written(
        self, lock: ModuleType, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(lock, tree)
        solo = tree / "init" / "solo"
        (solo / "dashboards" / "base.yaml").write_text("title: changed\n")
        (solo / "template.yaml").write_text(
            'template:\n  template_id: "init/solo"\n  version: "1.1.0"\n'
        )

        assert _check(lock, tree) == 1
        assert "the lock still has 1.0.0" in capsys.readouterr().out

        assert lock.main(["--write", "--projects-dir", str(tree)]) == 0
        assert _check(lock, tree) == 0

    def test_a_version_going_down_fails(self, lock: ModuleType, tree: Path) -> None:
        solo = tree / "init" / "solo"
        (solo / "template.yaml").write_text(
            'template:\n  template_id: "init/solo"\n  version: "1.2.0"\n'
        )
        _write(lock, tree)
        (solo / "template.yaml").write_text(
            'template:\n  template_id: "init/solo"\n  version: "1.1.0"\n'
        )

        findings = lock.compare(lock.compute(tree), lock.load_lock(tree / lock.LOCK_NAME) or {})

        assert [f.kind for f in findings] == [lock.DOWNGRADED]

    @pytest.mark.parametrize("version", ["1.0", "v1.0.0", "next", ""])
    def test_a_version_that_is_not_semver_fails(
        self, lock: ModuleType, tree: Path, version: str
    ) -> None:
        _write(lock, tree)
        (tree / "init" / "solo" / "template.yaml").write_text(
            f'template:\n  template_id: "init/solo"\n  version: "{version}"\n'
        )

        findings = lock.compare(lock.compute(tree), lock.load_lock(tree / lock.LOCK_NAME) or {})

        assert [f.kind for f in findings] == [lock.INVALID]
        assert _check(lock, tree) == 1

    def test_a_new_and_a_removed_template_fail(self, lock: ModuleType, tree: Path) -> None:
        _write(lock, tree)
        _template(tree, "init/added")
        for path in sorted((tree / "init" / "solo").rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        (tree / "init" / "solo").rmdir()

        findings = lock.compare(lock.compute(tree), lock.load_lock(tree / lock.LOCK_NAME) or {})

        assert {(f.kind, f.template) for f in findings} == {
            (lock.NEW, "init/added"),
            (lock.REMOVED, "init/solo"),
        }


class TestWrite:
    def test_it_records_the_version_and_the_hash_of_every_template(
        self, lock: ModuleType, tree: Path
    ) -> None:
        path = _write(lock, tree)

        document = json.loads(path.read_text())
        assert document["schema"] == 1
        assert sorted(document["templates"]) == [
            "init/solo",
            "nf-core/demo/1.0.0",
            "nf-core/demo/2.0.0",
        ]
        entry = document["templates"]["init/solo"]
        assert entry["version"] == "1.0.0"
        assert len(entry["content_hash"]) == 64

    def test_it_refuses_a_change_without_a_bump(
        self, lock: ModuleType, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _write(lock, tree)
        before = path.read_text()
        (tree / "init" / "solo" / "dashboards" / "base.yaml").write_text("title: changed\n")

        assert lock.main(["--write", "--projects-dir", str(tree)]) == 1

        assert path.read_text() == before
        assert "Nothing written" in capsys.readouterr().out

    def test_force_records_it_anyway(self, lock: ModuleType, tree: Path) -> None:
        _write(lock, tree)
        (tree / "init" / "solo" / "dashboards" / "base.yaml").write_text("title: changed\n")

        assert lock.main(["--write", "--projects-dir", str(tree), "--force"]) == 0
        assert _check(lock, tree) == 0

    def test_the_lock_path_is_a_parameter(
        self, lock: ModuleType, tree: Path, tmp_path: Path
    ) -> None:
        elsewhere = tmp_path / "locks" / "mine.json"
        elsewhere.parent.mkdir()

        assert lock.main(["--write", "--projects-dir", str(tree), "--lock", str(elsewhere)]) == 0

        assert elsewhere.is_file()
        assert not (tree / lock.LOCK_NAME).exists()
        assert lock.main(["--check", "--projects-dir", str(tree), "--lock", str(elsewhere)]) == 0

    def test_writing_twice_is_byte_identical(self, lock: ModuleType, tree: Path) -> None:
        path = _write(lock, tree)
        first = path.read_bytes()

        _write(lock, tree)

        assert path.read_bytes() == first


class TestShippedTemplates:
    """The real tree against the real lock."""

    def test_every_template_declares_a_semver_version_matching_its_directory(
        self, lock: ModuleType
    ) -> None:
        wrong = []
        for template_id, template_dir in lock.discover_templates(_PROJECTS).items():
            version = lock.read_version(template_dir)
            if not version or not lock._SEMVER.match(version):
                wrong.append(f"{template_id}: version {version!r}")
        assert not wrong, "template.version must be X.Y.Z:\n" + "\n".join(wrong)

    def test_no_template_changed_without_a_version_bump(self, lock: ModuleType) -> None:
        lock_path = _PROJECTS / lock.LOCK_NAME
        if not lock_path.is_file():
            pytest.skip(
                f"{lock_path.name} does not exist yet: "
                "create it with `python scripts/update_template_lock.py --write`"
            )

        findings = lock.compare(lock.compute(_PROJECTS), lock.load_lock(lock_path) or {})

        assert not findings, (
            "Template content changed without a template.version bump, or the lock is stale:\n"
            + "\n".join(f"  {f.template}: {f.message}" for f in findings)
            + "\n\nBump `template.version` in the template's template.yaml (major: a data "
            "collection, column or variable changed; minor: dashboards, figures or recipes "
            "changed; patch: text only), then run "
            "`python scripts/update_template_lock.py --write`."
        )
