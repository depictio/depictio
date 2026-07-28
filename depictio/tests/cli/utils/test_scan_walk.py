"""Tests for the scan-phase filesystem walker.

These lock in the behaviours the walker replaced ``os.walk`` for: honouring
``max_depth``/``ignore``, preserving the walked-vs-resolved path distinction
that regex matching and file storage each depend on, and producing a change
token that is stable across walk order but sensitive to real changes.
"""

import os

import pytest

from depictio.cli.cli.utils.scan_walk import ScannedPath, iter_run_files, run_signature


def _rel_paths(root, **kwargs) -> set[str]:
    return {p.rel_path for p in iter_run_files(str(root), **kwargs)}


@pytest.fixture
def tree(tmp_path):
    """A small tree with three levels, used by most tests.

    root/
      top.txt
      a/
        mid.txt
        b/
          deep.txt
    """
    (tmp_path / "top.txt").write_text("top")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "mid.txt").write_text("mid")
    (tmp_path / "a" / "b").mkdir()
    (tmp_path / "a" / "b" / "deep.txt").write_text("deep")
    return tmp_path


class TestMaxDepth:
    def test_none_is_unlimited(self, tree):
        assert _rel_paths(tree) == {"top.txt", "a/mid.txt", "a/b/deep.txt"}

    def test_zero_stays_in_root(self, tree):
        assert _rel_paths(tree, max_depth=0) == {"top.txt"}

    def test_one_descends_a_single_level(self, tree):
        assert _rel_paths(tree, max_depth=1) == {"top.txt", "a/mid.txt"}

    def test_two_reaches_the_bottom(self, tree):
        assert _rel_paths(tree, max_depth=2) == {"top.txt", "a/mid.txt", "a/b/deep.txt"}


class TestIgnore:
    def test_matches_basename(self, tree):
        assert _rel_paths(tree, ignore=["*.txt"]) == set()

    def test_matches_run_relative_path(self, tree):
        assert _rel_paths(tree, ignore=["a/b/deep.txt"]) == {"top.txt", "a/mid.txt"}

    def test_directory_match_prunes_the_subtree(self, tree):
        # Pruning at directory level is the point: nothing under a/ is walked,
        # not merely filtered out afterwards.
        assert _rel_paths(tree, ignore=["a"]) == {"top.txt"}

    def test_multiple_patterns_are_ored(self, tree):
        assert _rel_paths(tree, ignore=["top.txt", "a/b"]) == {"a/mid.txt"}

    def test_empty_list_ignores_nothing(self, tree):
        assert _rel_paths(tree, ignore=[]) == {"top.txt", "a/mid.txt", "a/b/deep.txt"}


class TestSymlinks:
    def test_symlinked_directory_is_not_followed(self, tmp_path):
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "inside.txt").write_text("x")
        (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)

        # Matches os.walk's default: linked dirs are listed but never descended,
        # and never leak into the file stream.
        assert _rel_paths(tmp_path) == {"real/inside.txt"}

    def test_symlinked_directory_is_followed_when_asked(self, tmp_path):
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "inside.txt").write_text("x")
        (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)

        assert _rel_paths(tmp_path, follow_symlinks=True) == {
            "real/inside.txt",
            "link/inside.txt",
        }

    def test_symlinked_file_resolves_to_its_target(self, tmp_path):
        (tmp_path / "target.txt").write_text("payload")
        (tmp_path / "alias.txt").symlink_to(tmp_path / "target.txt")

        by_rel = {p.rel_path: p for p in iter_run_files(str(tmp_path))}
        alias = by_rel["alias.txt"]

        # The distinction the scan phase relies on: regex matches the link name,
        # storage records the resolved target.
        assert alias.match_name == "alias.txt"
        assert alias.name == "target.txt"
        assert alias.path == os.path.realpath(str(tmp_path / "target.txt"))
        assert alias.walk_path == str(tmp_path / "alias.txt")
        assert alias.size == len("payload")

    def test_broken_symlink_is_skipped_not_raised(self, tmp_path):
        (tmp_path / "ok.txt").write_text("ok")
        (tmp_path / "dangling.txt").symlink_to(tmp_path / "missing.txt")

        # os.walk + os.path.getctime used to raise FileNotFoundError here and
        # abort the whole scan.
        assert _rel_paths(tmp_path) == {"ok.txt"}


class TestMetadata:
    def test_stat_fields_match_the_file(self, tmp_path):
        payload = "0123456789"
        target = tmp_path / "sized.txt"
        target.write_text(payload)

        (scanned,) = list(iter_run_files(str(tmp_path)))
        stat_result = target.stat()

        assert scanned.size == len(payload)
        assert scanned.mtime == pytest.approx(stat_result.st_mtime)
        assert scanned.mtime_ns == stat_result.st_mtime_ns
        assert scanned.ctime == pytest.approx(stat_result.st_ctime)

    def test_scanned_path_is_frozen(self, tmp_path):
        (tmp_path / "f.txt").write_text("x")
        (scanned,) = list(iter_run_files(str(tmp_path)))

        with pytest.raises(Exception):
            scanned.size = 99  # type: ignore[misc]

    def test_missing_root_yields_nothing(self, tmp_path):
        # The caller validates the run location; the walker must not explode on
        # a directory that disappeared between validation and walking.
        assert list(iter_run_files(str(tmp_path / "nope"))) == []

    def test_empty_directory_yields_nothing(self, tmp_path):
        (tmp_path / "empty").mkdir()
        assert list(iter_run_files(str(tmp_path / "empty"))) == []


class TestRunSignature:
    def _sig(self, root) -> str:
        return run_signature(iter_run_files(str(root)))

    def test_stable_across_repeated_walks(self, tree):
        assert self._sig(tree) == self._sig(tree)

    def test_independent_of_input_order(self, tree):
        paths = list(iter_run_files(str(tree)))
        assert run_signature(paths) == run_signature(list(reversed(paths)))

    def test_changes_when_a_file_is_added(self, tree):
        before = self._sig(tree)
        (tree / "extra.txt").write_text("new")
        assert self._sig(tree) != before

    def test_changes_when_a_file_is_removed(self, tree):
        before = self._sig(tree)
        (tree / "top.txt").unlink()
        assert self._sig(tree) != before

    def test_changes_when_size_changes(self, tree):
        before = self._sig(tree)
        (tree / "top.txt").write_text("top-but-longer")
        assert self._sig(tree) != before

    def test_changes_when_mtime_changes_at_equal_size(self, tree):
        # The in-place rewrite case: same byte count, different mtime. This is
        # what a re-run of an upstream pipeline typically looks like.
        before = self._sig(tree)
        target = tree / "top.txt"
        stat_result = target.stat()
        os.utime(target, ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 1_000_000_000))
        assert self._sig(tree) != before

    def test_changes_when_a_file_is_renamed(self, tree):
        before = self._sig(tree)
        (tree / "top.txt").rename(tree / "renamed.txt")
        assert self._sig(tree) != before

    def test_empty_input_is_deterministic(self):
        assert run_signature([]) == run_signature([])

    def test_distinguishes_same_names_in_different_directories(self):
        # rel_path, not basename, is what goes into the digest.
        def entry(rel_path: str) -> ScannedPath:
            return ScannedPath(
                path=f"/root/{rel_path}",
                walk_path=f"/root/{rel_path}",
                rel_path=rel_path,
                name=os.path.basename(rel_path),
                match_name=os.path.basename(rel_path),
                size=1,
                ctime=0.0,
                mtime=0.0,
                mtime_ns=0,
            )

        assert run_signature([entry("a/f.txt")]) != run_signature([entry("b/f.txt")])
