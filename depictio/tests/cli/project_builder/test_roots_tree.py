"""Path confinement, the one standalone root, the remote-root cache and the folder listing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from depictio.cli.cli.utils.data_root import LocalDataRoot
from depictio.project_builder import roots, tree
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.roots import PATH_REFUSED, RootCache, confine_rel, standalone_root

from ..s3_stubs import S3_ROOT, write_tree

# ── errors ───────────────────────────────────────────────────────────────────


class TestBuilderRefused:
    def test_the_body_is_detail_and_code(self):
        refused = BuilderRefused(422, "nope", "some_code")
        assert (refused.status, refused.detail, refused.code) == (422, "nope", "some_code")
        assert refused.body() == {"detail": "nope", "code": "some_code"}
        assert str(refused) == "nope"

    def test_a_refusal_without_a_code_has_no_code_in_its_body(self):
        assert BuilderRefused(404, "gone").body() == {"detail": "gone"}


# ── confinement ──────────────────────────────────────────────────────────────


class TestConfineRel:
    @pytest.mark.parametrize(
        "rel",
        [
            "/etc/passwd",  # absolute
            "/",
            "../outside",
            "a/../../outside",
            "a/b/..",
            "..",
            "a\\..\\outside",  # a Windows separator reads as one
            "~",
            "~/results",
            "~root/x",
            "a\x00b",
            "\x00",
        ],
    )
    def test_a_path_that_could_leave_the_root_is_refused(self, rel):
        with pytest.raises(BuilderRefused) as exc:
            confine_rel(rel)
        assert (exc.value.status, exc.value.code) == (400, PATH_REFUSED)
        assert PATH_REFUSED == "builder_path_refused"

    @pytest.mark.parametrize(
        ("rel", "clean"),
        [
            (None, ""),
            ("", ""),
            (".", ""),
            ("star", "star"),
            ("star/S1/quant.tsv", "star/S1/quant.tsv"),
            ("star//S1/./quant.tsv/", "star/S1/quant.tsv"),
            ("a\\b", "a/b"),
            # Only a whole ".." segment is a way out.
            ("..hidden/x", "..hidden/x"),
            ("a/..b", "a/..b"),
            (".hidden/x", ".hidden/x"),
            ("a/~b", "a/~b"),
        ],
    )
    def test_a_path_inside_the_root_comes_back_clean(self, rel, clean):
        assert confine_rel(rel) == clean


# ── the standalone root ──────────────────────────────────────────────────────


class TestStandaloneRoot:
    def test_a_folder_is_a_local_root_on_its_real_path(self, tmp_path):
        (tmp_path / "real").mkdir()
        (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
        root = standalone_root(tmp_path / "link")
        assert isinstance(root, LocalDataRoot)
        assert root.location == str((tmp_path / "real").resolve())
        assert root.is_remote is False

    def test_a_relative_folder_is_resolved(self, tmp_path, monkeypatch):
        (tmp_path / "here").mkdir()
        monkeypatch.chdir(tmp_path)
        assert standalone_root("here").location == str((tmp_path / "here").resolve())

    def test_a_tilde_is_the_home_folder(self, tmp_path, monkeypatch):
        (tmp_path / "results").mkdir()
        monkeypatch.setenv("HOME", str(tmp_path))
        assert standalone_root("~/results").location == str((tmp_path / "results").resolve())

    @pytest.mark.parametrize("kind", ["missing", "file"])
    def test_what_is_not_a_folder_is_refused(self, tmp_path, kind):
        target = tmp_path / "x"
        if kind == "file":
            target.write_text("not a folder")
        with pytest.raises(BuilderRefused) as exc:
            standalone_root(target)
        assert (exc.value.status, exc.value.code) == (400, "builder_root_missing")
        assert str(target.resolve()) in exc.value.detail


# ── the remote-root cache ────────────────────────────────────────────────────


def _remote() -> SimpleNamespace:
    return SimpleNamespace(is_remote=True)


class _Builds:
    """A ``build`` callable that counts its calls and hands out a fresh root each time."""

    def __init__(self, *, remote: bool = True):
        self.remote = remote
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return SimpleNamespace(is_remote=self.remote, n=self.calls)


class TestRootCache:
    def test_a_remote_root_is_built_once_and_reused(self):
        cache, build = RootCache(), _Builds()
        first = cache.get("k", build)
        assert cache.get("k", build) is first
        assert build.calls == 1

    def test_a_local_root_is_never_cached(self):
        cache, build = RootCache(), _Builds(remote=False)
        assert cache.get("k", build) is not cache.get("k", build)
        assert build.calls == 2

    def test_keys_are_cached_apart(self):
        cache, build = RootCache(), _Builds()
        a, b = cache.get("a", build), cache.get("b", build)
        assert a is not b
        assert cache.get("a", build) is a
        assert build.calls == 2

    def test_refresh_lists_again_and_replaces_the_entry(self):
        cache, build = RootCache(), _Builds()
        old = cache.get("k", build)
        fresh = cache.get("k", build, refresh=True)
        assert fresh is not old
        assert cache.get("k", build) is fresh
        assert build.calls == 2

    def test_a_listing_older_than_the_ttl_is_taken_again(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(roots, "time", SimpleNamespace(monotonic=lambda: now[0]))
        cache, build = RootCache(ttl_s=60), _Builds()
        cache.get("k", build)
        now[0] += 59
        cache.get("k", build)
        assert build.calls == 1
        now[0] += 2
        cache.get("k", build)
        assert build.calls == 2

    def test_the_default_ttl_is_a_minute(self):
        assert roots.S3_ROOT_TTL_S == 60.0
        assert RootCache()._ttl_s == 60.0

    def test_the_oldest_entry_goes_when_the_cache_is_full(self, monkeypatch):
        now = [0.0]
        monkeypatch.setattr(roots, "time", SimpleNamespace(monotonic=lambda: now[0]))
        cache, build = RootCache(max_entries=2), _Builds()
        for key in ("a", "b", "c"):
            now[0] += 1
            cache.get(key, build)
        assert build.calls == 3
        assert set(cache._entries) == {"b", "c"}

    def test_clear_forgets_everything(self):
        cache, build = RootCache(), _Builds()
        cache.get("k", build)
        cache.clear()
        cache.get("k", build)
        assert build.calls == 2

    def test_a_build_that_fails_caches_nothing(self):
        cache = RootCache()

        def broken():
            raise RuntimeError("listing failed")

        with pytest.raises(RuntimeError):
            cache.get("k", broken)
        assert cache._entries == {}


# ── the folder listing ───────────────────────────────────────────────────────

LISTED = {
    "zeta.csv": b"a,b\n1,2\n",
    "alpha.tsv": b"a\tb\n1\t2\n",
    "Beta/inner.csv": b"x",
    "star/S1/quant.tsv": b"x",
    "star/S2/quant.tsv": b"x",
    "star/summary.txt": b"x",
    ".hidden/secret.csv": b"x",
    ".dotfile": b"x",
    "__pycache__/mod.pyc": b"x",
    "node_modules/pkg/index.js": b"x",
    "__MACOSX/._junk": b"x",
}


@pytest.fixture
def listed_root(tmp_path):
    return LocalDataRoot(str(write_tree(tmp_path / "results", LISTED)))


class TestListFolder:
    def test_folders_come_first_then_files_by_name(self, listed_root):
        listing = tree.list_folder(listed_root)
        assert [(e["name"], e["is_dir"]) for e in listing["entries"]] == [
            ("Beta", True),
            ("star", True),
            ("alpha.tsv", False),
            ("zeta.csv", False),
        ]

    def test_hidden_entries_are_left_out(self, listed_root):
        names = {e["name"] for e in tree.list_folder(listed_root)["entries"]}
        assert names.isdisjoint({".hidden", ".dotfile", "__pycache__", "node_modules", "__MACOSX"})

    def test_an_entry_carries_the_path_to_ask_for_next(self, listed_root):
        top = {e["name"]: e for e in tree.list_folder(listed_root)["entries"]}
        assert top["star"] == {"name": "star", "path": "star", "is_dir": True, "size": None}
        assert top["alpha.tsv"]["path"] == "alpha.tsv"
        assert top["alpha.tsv"]["size"] == len(LISTED["alpha.tsv"])

        inner = tree.list_folder(listed_root, "star")
        assert inner["path"] == "star"
        assert [e["path"] for e in inner["entries"]] == ["star/S1", "star/S2", "star/summary.txt"]

    def test_the_listing_describes_its_root(self, listed_root):
        listing = tree.list_folder(listed_root)
        assert listing["path"] == ""
        assert listing["is_remote"] is False
        assert listing["root_label"] == listed_root.location
        assert listing["truncated"] is False

    def test_the_path_is_cleaned_before_it_is_used(self, listed_root):
        assert tree.list_folder(listed_root, "star//S1/")["path"] == "star/S1"

    @pytest.mark.parametrize("rel", ["../elsewhere", "/etc", "~", "star/../../x", "a\x00b"])
    def test_a_path_outside_the_root_is_refused_before_anything_is_read(self, listed_root, rel):
        with pytest.raises(BuilderRefused) as exc:
            tree.list_folder(listed_root, rel)
        assert (exc.value.status, exc.value.code) == (400, PATH_REFUSED)

    def test_a_folder_that_does_not_exist_is_a_404(self, listed_root):
        with pytest.raises(BuilderRefused) as exc:
            tree.list_folder(listed_root, "nope")
        assert (exc.value.status, exc.value.code) == (404, "folder_missing")

    def test_a_file_lists_nothing(self, listed_root):
        assert tree.list_folder(listed_root, "alpha.tsv")["entries"] == []

    def test_a_long_folder_is_cut_and_says_so(self, listed_root, monkeypatch):
        monkeypatch.setattr(tree, "MAX_ENTRIES", 3)
        listing = tree.list_folder(listed_root)
        assert len(listing["entries"]) == 3
        assert listing["truncated"] is True
        # Exactly at the cap is not truncated.
        monkeypatch.setattr(tree, "MAX_ENTRIES", 4)
        assert tree.list_folder(listed_root)["truncated"] is False

    def test_a_root_with_a_partial_view_says_so(self):
        partial = SimpleNamespace(
            location="s3://b/p",
            is_remote=True,
            truncated=True,
            exists=lambda rel: True,
            children=lambda rel: [],
        )
        listing = tree.list_folder(partial)
        assert (listing["truncated"], listing["is_remote"]) == (True, True)

    def test_an_s3_prefix_lists_like_a_folder(self, s3_root, root):
        remote, local = tree.list_folder(s3_root), tree.list_folder(root)
        assert remote["is_remote"] is True
        assert remote["root_label"] == S3_ROOT
        assert remote["entries"] == local["entries"]
        assert tree.list_folder(s3_root, "star")["path"] == "star"
        with pytest.raises(BuilderRefused) as exc:
            tree.list_folder(s3_root, "nope")
        assert exc.value.code == "folder_missing"
