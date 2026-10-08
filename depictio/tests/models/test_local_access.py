"""Tests for ``depictio.models.local_access``: what a server may read on its own disk.

Every refusal is judged on the real path, so the interesting cases are the ways
a path can look inside a root and not be: a symlink, ``..``, a denied folder, a
hidden one. Messages name the path as the caller wrote it and nothing else.
"""

import os
import tempfile

import pytest

from depictio.models.local_access import LocalDataPolicy, LocalPathRefused


@pytest.fixture()
def tree(tmp_path):
    """``home/`` holding a run, a hidden folder, a denied folder and two links,
    plus a folder ``outside/`` next to it."""
    home = tmp_path / "home"
    (home / "results" / "run42" / "pipeline_info").mkdir(parents=True)
    (home / "results" / "run42" / "table.csv").write_text("a,b\n1,2\n")
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id_ed25519").write_text("secret")
    (home / "results" / ".cache").mkdir()
    (home / "depictio-local" / "keys").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "passwd").write_text("root:x:0:0")
    (home / "escape").symlink_to(outside)
    (home / "latest").symlink_to(home / "results" / "run42")
    return home, outside


def _policy(home, **kwargs) -> LocalDataPolicy:
    kwargs.setdefault("denied", [str(home / "depictio-local")])
    return LocalDataPolicy.build([str(home)], home=str(home), **kwargs)


def _refusal(policy: LocalDataPolicy, path: str, want="dir") -> LocalPathRefused:
    with pytest.raises(LocalPathRefused) as exc:
        policy.confine(path, want=want)
    return exc.value


def test_a_folder_under_a_root_is_its_real_path(tree):
    home, _outside = tree
    policy = _policy(home)
    run = home / "results" / "run42"
    assert policy.confine(str(run)) == os.path.realpath(run)
    assert policy.allows(str(run))
    assert policy.root_of(os.path.realpath(run)) == os.path.realpath(home)


def test_a_root_is_allowed_itself(tree):
    home, _outside = tree
    assert _policy(home).confine(str(home)) == os.path.realpath(home)


def test_a_symlink_out_of_the_root_is_refused_and_never_named(tree):
    home, outside = tree
    policy = _policy(home)
    refused = _refusal(policy, str(home / "escape"))
    assert refused.code == "local_path_outside"
    assert str(outside) not in str(refused)
    assert not policy.allows(str(home / "escape" / "passwd"))


def test_a_symlink_that_stays_inside_reads_as_its_target(tree):
    home, _outside = tree
    real = _policy(home).confine(str(home / "latest"))
    assert real == os.path.realpath(home / "results" / "run42")


def test_dot_dot_cannot_walk_out(tree):
    home, _outside = tree
    sneaky = f"{home}/results/../../outside"
    refused = _refusal(_policy(home), sneaky)
    assert refused.code == "local_path_outside"
    assert sneaky in str(refused)


def test_dot_dot_that_stays_inside_is_fine(tree):
    home, _outside = tree
    real = _policy(home).confine(f"{home}/.ssh/../results/run42")
    assert real == os.path.realpath(home / "results" / "run42")


@pytest.mark.parametrize("rel", ["depictio-local", "depictio-local/keys"])
def test_a_denied_folder_is_refused_with_everything_below_it(tree, rel):
    home, _outside = tree
    refused = _refusal(_policy(home), str(home / rel))
    assert refused.code == "local_path_denied"


def test_the_depictio_home_is_denied_even_when_a_root_holds_it(tree):
    home, _outside = tree
    (home / ".depictio").mkdir()
    policy = _policy(home, denied=[str(home / ".depictio")])
    assert _refusal(policy, str(home / ".depictio")).code == "local_path_denied"


@pytest.mark.parametrize("rel", [".ssh", ".ssh/id_ed25519", "results/.cache"])
def test_a_hidden_segment_below_the_root_is_refused(tree, rel):
    home, _outside = tree
    refused = _refusal(_policy(home), str(home / rel), want="any")
    assert refused.code == "local_path_hidden"


def test_a_root_inside_a_hidden_folder_still_works(tree):
    """The rule counts from the innermost root an administrator allowed."""
    home, _outside = tree
    (home / ".ssh" / "runs").mkdir()
    policy = LocalDataPolicy.build([str(home), str(home / ".ssh" / "runs")], home=str(home))
    assert policy.allows(str(home / ".ssh" / "runs"))
    assert not policy.allows(str(home / ".ssh" / "id_ed25519"))


def test_tilde_is_the_servers_home(tree):
    home, _outside = tree
    policy = _policy(home)
    assert policy.confine("~/results/run42") == os.path.realpath(home / "results" / "run42")
    assert policy.confine("~") == os.path.realpath(home)


def test_allows_judges_a_tilde_path_as_written(tree):
    """``open("~/x")`` reads a cwd-relative ``~/x``, never the home: judging the
    expanded path would allow one file and let the read open another."""
    home, _outside = tree
    policy = _policy(home)
    assert not policy.allows("~/results/run42")
    assert not policy.allows_read("~/results/run42/table.csv")
    assert not policy.allows("~")
    # Spelled out, the same folder is allowed, and confine still expands it:
    # the real path it returns is what the caller then reads.
    assert policy.allows(str(home / "results" / "run42"))
    assert policy.allows_read(policy.confine("~/results/run42/table.csv", want="file"))


def test_a_tilde_refusal_names_the_path_as_written(tree):
    home, _outside = tree
    refused = _refusal(_policy(home), "~/.ssh", want="any")
    assert refused.code == "local_path_hidden"
    assert "'~/.ssh'" in str(refused)
    assert str(home) not in str(refused)


def test_tilde_user_is_not_expanded(tree):
    home, _outside = tree
    assert _refusal(_policy(home), "~root/results").code == "local_path_not_absolute"


def test_roots_may_be_configured_with_tilde(tree):
    home, _outside = tree
    policy = LocalDataPolicy.build(["~/results"], home=str(home))
    assert policy.roots == (os.path.realpath(home / "results"),)
    assert not policy.allows(str(home / "depictio-local"))


def test_a_tmp_root_matches_its_real_path():
    """macOS: /tmp is a symlink to /private/tmp, so both sides are made real."""
    base = tempfile.mkdtemp(dir="/tmp")
    try:
        os.mkdir(os.path.join(base, "run"))
        policy = LocalDataPolicy.build([base])
        assert policy.confine(os.path.join(base, "run")) == os.path.realpath(
            os.path.join(base, "run")
        )
        # Spelled through the real path too.
        assert policy.allows(os.path.realpath(os.path.join(base, "run")))
    finally:
        os.rmdir(os.path.join(base, "run"))
        os.rmdir(base)


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("results/run42", "local_path_not_absolute"),
        ("", "local_path_invalid"),
        ("   ", "local_path_invalid"),
        ("/tmp/x\x00y", "local_path_invalid"),
    ],
)
def test_malformed_paths(tree, path, code):
    home, _outside = tree
    assert _refusal(_policy(home), path).code == code


def test_wrong_kind_and_missing(tree):
    home, _outside = tree
    policy = _policy(home)
    table = str(home / "results" / "run42" / "table.csv")
    assert _refusal(policy, table, want="dir").code == "local_path_not_a_folder"
    assert _refusal(policy, str(home / "results"), want="file").code == "local_path_not_a_file"
    assert policy.confine(table, want="file") == os.path.realpath(table)
    assert policy.confine(table, want="any") == os.path.realpath(table)
    assert _refusal(policy, str(home / "nope")).code == "local_path_missing"


def test_allows_says_nothing_about_existence(tree):
    home, _outside = tree
    assert _policy(home).allows(str(home / "not-yet"))


def test_server_dirs_are_readable_but_never_data(tree):
    home, outside = tree
    policy = _policy(home, server_dirs=[str(outside)])
    assert policy.allows_read(str(outside / "passwd"))
    assert not policy.allows(str(outside / "passwd"))
    assert _refusal(policy, str(outside)).code == "local_path_outside"


def test_denied_wins_over_server_dirs(tree):
    home, outside = tree
    policy = _policy(home, server_dirs=[str(outside)], denied=[str(outside)])
    assert not policy.allows_read(str(outside / "passwd"))


def test_relative_and_blank_roots_are_dropped(tree):
    home, _outside = tree
    policy = LocalDataPolicy.build(["", "  ", "relative/dir", str(home)], home=str(home))
    assert policy.roots == (os.path.realpath(home),)


def test_the_refusal_is_a_value_error_with_a_code(tree):
    home, _outside = tree
    refused = _refusal(_policy(home), str(home / "escape"))
    assert isinstance(refused, ValueError)
    assert refused.detail == str(refused)
