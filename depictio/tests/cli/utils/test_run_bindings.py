"""Per-run single files, recipe params and template variables (epic #1399)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from depictio.cli.cli.utils.run_bindings import (
    carry_run_bindings,
    run_params_for,
    single_files,
)


def _single(tag: str, filename: str, scope=None):
    params = SimpleNamespace(filename=filename, run_files=None, scope=scope)
    scan = SimpleNamespace(mode="single", scan_parameters=params)
    return SimpleNamespace(
        data_collection_tag=tag, config=SimpleNamespace(scan=scan, transform=None)
    )


def _recipe(tag: str, params):
    transform = SimpleNamespace(params=params, run_params=None)
    return SimpleNamespace(
        data_collection_tag=tag,
        config=SimpleNamespace(scan=None, transform=transform),
    )


def _project(locations, dcs, variables=None, data_root=None):
    wf = SimpleNamespace(
        workflow_tag="wf",
        data_location=SimpleNamespace(locations=locations),
        data_collections=dcs,
    )
    origin = SimpleNamespace(variables=variables or {}, data_root=data_root, run_variables=None)
    return SimpleNamespace(workflows=[wf], template_origin=origin)


def _remote(locations, dcs, variables=None, data_root=None, run_variables=None):
    return {
        "workflows": [
            {
                "workflow_tag": "wf",
                "data_location": {"locations": locations},
                "data_collections": dcs,
            }
        ],
        "template_origin": {
            "variables": variables or {},
            "data_root": data_root,
            "run_variables": run_variables,
        },
    }


def _remote_single(tag, filename, run_files=None):
    return {
        "data_collection_tag": tag,
        "config": {
            "scan": {
                "mode": "single",
                "scan_parameters": {"filename": filename, "run_files": run_files},
            }
        },
    }


def _remote_recipe(tag, params, run_params=None):
    return {
        "data_collection_tag": tag,
        "config": {"transform": {"params": params, "run_params": run_params}},
    }


@pytest.fixture
def runs(tmp_path):
    out = {}
    for name, body in (
        ("run_athens", "a\n1\n"),
        ("run_barcelona", "a\n2\n"),
        ("run_naples", "a\n1\n"),
    ):
        (tmp_path / name / "input").mkdir(parents=True)
        (tmp_path / name / "input" / "metadata.tsv").write_text(body)
        out[name] = str(tmp_path / name)
    return out


def test_attach_binds_each_run_its_own_file(runs):
    athens, barcelona = runs["run_athens"], runs["run_barcelona"]
    dc = _single("metadata", f"{barcelona}/input/metadata.tsv")
    project = _project([athens, barcelona], [dc])
    remote = _remote([athens], [_remote_single("metadata", f"{athens}/input/metadata.tsv")])

    report = carry_run_bindings(project, remote, {"wf": [barcelona]})

    params = dc.config.scan.scan_parameters
    assert params.filename == f"{athens}/input/metadata.tsv"
    assert params.run_files == {
        athens: f"{athens}/input/metadata.tsv",
        barcelona: f"{barcelona}/input/metadata.tsv",
    }
    assert report.per_run_single == ["metadata"]


def test_identical_bytes_are_kept_once(runs):
    athens, naples = runs["run_athens"], runs["run_naples"]
    dc = _single("metadata", f"{naples}/input/metadata.tsv")
    project = _project([athens, naples], [dc])
    remote = _remote([athens], [_remote_single("metadata", f"{athens}/input/metadata.tsv")])

    report = carry_run_bindings(project, remote, {"wf": [naples]})

    params = dc.config.scan.scan_parameters
    assert set(params.run_files.values()) == {f"{athens}/input/metadata.tsv"}
    assert report.shared_single == ["metadata"]
    files = single_files(params, [athens, naples])
    assert files == [(f"{athens}/input/metadata.tsv", [athens, naples])]


def test_run_without_the_file_keeps_the_previous_one(runs, tmp_path):
    athens = runs["run_athens"]
    empty = str(tmp_path / "run_empty")
    dc = _single("metadata", f"{empty}/input/metadata.tsv")
    project = _project([athens, empty], [dc])
    remote = _remote([athens], [_remote_single("metadata", f"{athens}/input/metadata.tsv")])

    report = carry_run_bindings(project, remote, {"wf": [empty]})

    assert dc.config.scan.scan_parameters.run_files == {
        athens: f"{athens}/input/metadata.tsv",
        empty: f"{athens}/input/metadata.tsv",
    }
    assert report.missing_single == ["metadata"]


def test_refresh_of_a_single_run_project_changes_nothing(runs):
    athens = runs["run_athens"]
    dc = _single("metadata", f"{athens}/input/metadata.tsv")
    recipe = _recipe("alpha", {"GROUP": "habitat"})
    project = _project([athens], [dc, recipe], variables={"V": "1"}, data_root=athens)
    remote = _remote(
        [athens],
        [
            _remote_single("metadata", f"{athens}/input/metadata.tsv"),
            _remote_recipe("alpha", {"GROUP": "habitat"}),
        ],
        variables={"V": "1"},
        data_root=athens,
    )

    carry_run_bindings(project, remote, {"wf": [athens]})

    assert dc.config.scan.scan_parameters.run_files is None
    assert dc.config.scan.scan_parameters.filename == f"{athens}/input/metadata.tsv"
    assert recipe.config.transform.run_params is None
    assert recipe.config.transform.params == {"GROUP": "habitat"}
    assert project.template_origin.run_variables is None


def test_params_and_variables_are_kept_per_run(runs):
    athens, barcelona = runs["run_athens"], runs["run_barcelona"]
    recipe = _recipe("alpha", {"GROUP": "city"})
    project = _project([athens, barcelona], [recipe], variables={"G": "city"}, data_root=barcelona)
    remote = _remote(
        [athens],
        [_remote_recipe("alpha", {"GROUP": "habitat"})],
        variables={"G": "habitat"},
        data_root=athens,
    )

    report = carry_run_bindings(project, remote, {"wf": [barcelona]})

    transform = recipe.config.transform
    assert transform.params == {"GROUP": "habitat"}
    assert transform.run_params == {athens: {"GROUP": "habitat"}, barcelona: {"GROUP": "city"}}
    assert run_params_for(transform, barcelona) == {"GROUP": "city"}
    assert run_params_for(transform, athens + "/") == {"GROUP": "habitat"}
    assert report.per_run_params == ["alpha"]
    origin = project.template_origin
    assert origin.variables == {"G": "habitat"}
    assert origin.data_root == athens
    assert origin.run_variables == {athens: {"G": "habitat"}, barcelona: {"G": "city"}}


def test_same_params_store_no_map(runs):
    athens, barcelona = runs["run_athens"], runs["run_barcelona"]
    recipe = _recipe("alpha", {"GROUP": "habitat"})
    project = _project([athens, barcelona], [recipe])
    remote = _remote([athens], [_remote_recipe("alpha", {"GROUP": "habitat"})])
    carry_run_bindings(project, remote, {"wf": [barcelona]})
    assert recipe.config.transform.run_params is None


def test_project_scope_keeps_the_first_file(runs):
    athens, barcelona = runs["run_athens"], runs["run_barcelona"]
    dc = _single("metadata", f"{barcelona}/input/metadata.tsv", scope="project")
    project = _project([athens, barcelona], [dc])
    remote = _remote([athens], [_remote_single("metadata", f"{athens}/input/metadata.tsv")])
    carry_run_bindings(project, remote, {"wf": [barcelona]})
    params = dc.config.scan.scan_parameters
    assert params.filename == f"{athens}/input/metadata.tsv"
    assert params.run_files is None
    assert single_files(params, [athens, barcelona]) == [(params.filename, [])]


def test_dropped_location_loses_its_binding(runs):
    athens, barcelona = runs["run_athens"], runs["run_barcelona"]
    dc = _single("metadata", f"{athens}/input/metadata.tsv")
    project = _project([athens], [dc])
    remote = _remote(
        [athens, barcelona],
        [
            _remote_single(
                "metadata",
                f"{athens}/input/metadata.tsv",
                run_files={
                    athens: f"{athens}/input/metadata.tsv",
                    barcelona: f"{barcelona}/input/metadata.tsv",
                },
            )
        ],
    )
    carry_run_bindings(project, remote, {"wf": [athens]})
    assert dc.config.scan.scan_parameters.run_files is None


def test_single_files_without_map_belong_to_the_first_location():
    params = SimpleNamespace(filename="/a/m.tsv", run_files=None, scope=None)
    assert single_files(params, ["/a", "/b"]) == [("/a/m.tsv", ["/a"])]
