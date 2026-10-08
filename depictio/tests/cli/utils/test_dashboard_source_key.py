"""The source key `ingest` sends with each dashboard, and `--dashboard-name`.

The server files an imported dashboard under its source key and a later import
finds the dashboard with the same key, so the key has to stay put across a rename
and across template versions. A dashboard the project has is kept as edited in
the viewer (`existing=keep`), or with `reset` replaced under the title it has now
(`existing=replace`, `keep_titles`); `--dashboard-name` is sent as `main_title`
with the main dashboard's file, and a child tab file names its parent's key.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from depictio.cli.cli.utils import templates as templates_module
from depictio.cli.cli.utils.templates import (
    dashboard_outcome,
    dashboard_source_key,
    import_dashboards_from_template,
    template_family,
)


@pytest.mark.parametrize(
    "template_id,family",
    [
        ("nf-core/rnaseq/3.26.0", "nf-core/rnaseq"),
        ("nf-core/rnaseq/latest", "nf-core/rnaseq"),
        (
            "nf-core/variantbenchmarking/1.4.0/categories/small",
            "nf-core/variantbenchmarking/categories/small",
        ),
        ("init/catalog_conformance", "init/catalog_conformance"),
    ],
)
def test_template_family_drops_the_version(template_id: str, family: str) -> None:
    assert template_family(template_id) == family


class TestDashboardSourceKey:
    def test_template_dashboard(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "nf-core" / "rnaseq" / "3.26.0"
        path = template_dir / "dashboards" / "base.yaml"

        key = dashboard_source_key(path, "nf-core/rnaseq/3.26.0", template_dir)

        assert key == "nf-core/rnaseq:dashboards/base.yaml"

    def test_same_dashboard_in_a_newer_version_keeps_its_key(self, tmp_path: Path) -> None:
        keys = {
            dashboard_source_key(
                tmp_path / version / "dashboards" / "base.yaml",
                f"nf-core/rnaseq/{version}",
                tmp_path / version,
            )
            for version in ("3.26.0", "3.27.0")
        }
        assert keys == {"nf-core/rnaseq:dashboards/base.yaml"}

    def test_file_under_the_project_config_directory(self, tmp_path: Path) -> None:
        key = dashboard_source_key(tmp_path / "dashboards" / "main.yaml", base_dir=tmp_path)

        assert key == "file:dashboards/main.yaml"

    def test_override_outside_the_template_is_keyed_by_its_absolute_path(
        self, tmp_path: Path
    ) -> None:
        template_dir = tmp_path / "template"
        path = tmp_path / "mine" / "custom.yaml"

        key = dashboard_source_key(path, "nf-core/rnaseq/3.26.0", template_dir)

        assert key == f"file:{path.resolve().as_posix()}"

    def test_file_outside_the_project_config_directory_is_keyed_by_its_absolute_path(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "elsewhere" / "main.yaml"

        key = dashboard_source_key(path, base_dir=tmp_path / "project")

        assert key == f"file:{path.resolve().as_posix()}"

    def test_files_with_the_same_name_next_to_a_template_get_two_keys(self, tmp_path: Path) -> None:
        """`ingest --template X --dashboard qc/dashboard.yaml --dashboard
        expr/dashboard.yaml`: one key filed them as one dashboard."""
        template_dir = tmp_path / "template"

        keys = {
            dashboard_source_key(
                tmp_path / folder / "dashboard.yaml", "nf-core/rnaseq/3.26.0", template_dir
            )
            for folder in ("qc", "expr")
        }

        assert len(keys) == 2


@pytest.fixture
def post(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    response = MagicMock(status_code=200)
    response.json.return_value = {"dashboard_id": "x", "title": "t", "updated": False}
    mock = MagicMock(return_value=response)
    monkeypatch.setattr(templates_module.httpx, "post", mock)
    return mock


def _sent(post: MagicMock) -> list[tuple[dict, dict]]:
    """(params, parsed YAML) of every import request, in order."""
    return [(c.kwargs["params"], yaml.safe_load(c.kwargs["content"])) for c in post.call_args_list]


def _write(path: Path, doc: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc))
    return path


class TestImportDashboards:
    def test_template_dashboard_is_sent_with_its_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, post: MagicMock
    ) -> None:
        template_dir = tmp_path / "nf-core" / "rnaseq" / "3.26.0"
        _write(template_dir / "template.yaml", {})
        path = _write(template_dir / "dashboards" / "base.yaml", {"title": "RNA-seq"})
        monkeypatch.setattr(
            templates_module, "locate_template", lambda _id: template_dir / "template.yaml"
        )

        import_dashboards_from_template(
            [path], "http://api", {}, project_id="p", template_id="nf-core/rnaseq/3.26.0"
        )

        ((params, _),) = _sent(post)
        assert params["source_key"] == "nf-core/rnaseq:dashboards/base.yaml"

    def test_project_config_dashboards_are_keyed_by_their_path(
        self, tmp_path: Path, post: MagicMock
    ) -> None:
        paths = [
            _write(tmp_path / "qc" / "dashboard.yaml", {"title": "QC"}),
            _write(tmp_path / "expr" / "dashboard.yaml", {"title": "Expression"}),
        ]

        import_dashboards_from_template(paths, "http://api", {}, base_dir=tmp_path)

        keys = [params["source_key"] for params, _ in _sent(post)]
        assert keys == ["file:qc/dashboard.yaml", "file:expr/dashboard.yaml"]

    def test_dashboard_name_renames_the_main_dashboard_and_keeps_its_tabs(
        self, tmp_path: Path, post: MagicMock
    ) -> None:
        paths = [
            _write(tmp_path / "main.yaml", {"title": "Main"}),
            _write(
                tmp_path / "tab.yaml",
                {"title": "Tab", "is_main_tab": False, "parent_dashboard_tag": "Main"},
            ),
        ]

        import_dashboards_from_template(
            paths, "http://api", {}, dashboard_name="Renamed", base_dir=tmp_path
        )

        (_, main), (_, tab) = _sent(post)
        assert main["title"] == "Renamed"
        assert tab["title"] == "Tab"
        assert tab["parent_dashboard_tag"] == "Renamed"

    def test_dashboard_name_renames_only_the_multi_tab_main(
        self, tmp_path: Path, post: MagicMock
    ) -> None:
        path = _write(
            tmp_path / "base.yaml",
            {"main_dashboard": {"title": "Main"}, "tabs": [{"title": "QC"}]},
        )

        import_dashboards_from_template([path], "http://api", {}, dashboard_name="Renamed")

        ((_, doc),) = _sent(post)
        assert doc["main_dashboard"]["title"] == "Renamed"
        assert doc["tabs"] == [{"title": "QC"}]

    def test_every_import_keeps_the_titles_it_finds(self, tmp_path: Path, post: MagicMock) -> None:
        paths = [
            _write(tmp_path / "main.yaml", {"title": "Main"}),
            _write(tmp_path / "multi.yaml", {"main_dashboard": {"title": "M"}, "tabs": []}),
        ]

        import_dashboards_from_template(paths, "http://api", {}, base_dir=tmp_path)

        for params, _ in _sent(post):
            assert params["keep_titles"] is True
            assert "main_title" not in params

    def test_dashboard_name_is_sent_as_the_main_title_of_the_main_file_only(
        self, tmp_path: Path, post: MagicMock
    ) -> None:
        paths = [
            _write(
                tmp_path / "tab.yaml",
                {"title": "Tab", "is_main_tab": False, "parent_dashboard_tag": "Main"},
            ),
            _write(tmp_path / "main.yaml", {"title": "Main"}),
            _write(tmp_path / "other.yaml", {"title": "Other"}),
        ]

        import_dashboards_from_template(
            paths, "http://api", {}, dashboard_name="Renamed", base_dir=tmp_path
        )

        (tab, _), (main, _), (other, _) = _sent(post)
        assert main["main_title"] == "Renamed"
        assert "main_title" not in tab
        assert "main_title" not in other

    def test_dashboard_name_is_sent_with_a_multi_tab_file(
        self, tmp_path: Path, post: MagicMock
    ) -> None:
        path = _write(
            tmp_path / "base.yaml",
            {"main_dashboard": {"title": "Main"}, "tabs": [{"title": "QC"}]},
        )

        import_dashboards_from_template([path], "http://api", {}, dashboard_name="Renamed")

        ((params, _),) = _sent(post)
        assert params["main_title"] == "Renamed"
        assert params["keep_titles"] is True

    @pytest.mark.parametrize("dashboard_name", [None, "Renamed"])
    def test_child_tab_file_is_sent_with_its_parent_key(
        self, tmp_path: Path, post: MagicMock, dashboard_name: str | None
    ) -> None:
        paths = [
            _write(
                tmp_path / "dashboards" / "main.yaml",
                {"main_dashboard": {"title": "Main"}, "tabs": []},
            ),
            _write(
                tmp_path / "dashboards" / "tab.yaml",
                {"title": "Tab", "is_main_tab": False, "parent_dashboard_tag": "Main"},
            ),
            _write(
                tmp_path / "dashboards" / "stray.yaml",
                {"title": "Stray", "is_main_tab": False, "parent_dashboard_tag": "Elsewhere"},
            ),
        ]

        import_dashboards_from_template(
            paths, "http://api", {}, dashboard_name=dashboard_name, base_dir=tmp_path
        )

        (main, _), (tab, _), (stray, _) = _sent(post)
        assert "parent_source_key" not in main
        assert tab["parent_source_key"] == "file:dashboards/main.yaml"
        # A parent this import does not bring is still found by its title.
        assert "parent_source_key" not in stray

    def test_existing_dashboards_are_kept_unless_reset(
        self, tmp_path: Path, post: MagicMock
    ) -> None:
        path = _write(tmp_path / "main.yaml", {"title": "Main"})

        import_dashboards_from_template([path], "http://api", {})
        import_dashboards_from_template([path], "http://api", {}, reset=True)

        (kept, _), (reset, _) = _sent(post)
        assert kept["existing"] == "keep"
        assert reset["existing"] == "replace"
        # A server from before `existing` reads overwrite instead: sent with keep,
        # it replaced the dashboards a refresh is meant to keep.
        assert "overwrite" not in kept
        assert reset["overwrite"] is True
        for params in (kept, reset):
            assert params["keep_titles"] is True

    @pytest.mark.parametrize(
        ("doc", "title"),
        [
            ({"title": "Main"}, "Main"),
            ({"main_dashboard": {"title": "Main"}, "tabs": [{"title": "QC"}]}, "Main"),
        ],
    )
    def test_a_conflict_from_a_server_before_existing_is_a_kept_dashboard(
        self, tmp_path: Path, post: MagicMock, doc: dict, title: str
    ) -> None:
        post.return_value = MagicMock(status_code=409, text="exists")
        post.return_value.json.return_value = {
            "detail": "Dashboard 'Main' already exists in this project. "
            "Use --overwrite to update it."
        }

        (result,) = import_dashboards_from_template(
            [_write(tmp_path / "main.yaml", doc)], "http://api", {}
        )

        assert (result["success"], result["status"], result["title"]) == (True, "kept", title)
        assert "error" not in result

    def test_a_conflict_on_reset_is_a_failure(self, tmp_path: Path, post: MagicMock) -> None:
        post.return_value = MagicMock(status_code=409, text="exists")
        post.return_value.json.return_value = {"detail": "Conflict"}

        (result,) = import_dashboards_from_template(
            [_write(tmp_path / "main.yaml", {"title": "Main"})], "http://api", {}, reset=True
        )

        assert result["success"] is False
        assert result["error"] == "HTTP 409: Conflict"

    def test_dashboard_files_with_the_same_name_are_sent_with_two_keys(
        self, tmp_path: Path, post: MagicMock
    ) -> None:
        """--template with two --dashboard files, no --project-config-path."""
        paths = [
            _write(tmp_path / "qc" / "dashboard.yaml", {"title": "QC"}),
            _write(tmp_path / "expr" / "dashboard.yaml", {"title": "Expression"}),
        ]

        import_dashboards_from_template(paths, "http://api", {})

        keys = [params["source_key"] for params, _ in _sent(post)]
        assert keys == [f"file:{path.resolve().as_posix()}" for path in paths]

    @pytest.mark.parametrize(
        ("response", "status"),
        [
            ({"status": "kept", "updated": False}, "kept"),
            ({"status": "created", "updated": False}, "created"),
            # A server from before `existing` says whether it updated, only.
            ({"updated": True}, "replaced"),
            ({"updated": False}, "created"),
        ],
    )
    def test_each_result_says_what_became_of_the_dashboard(
        self, tmp_path: Path, post: MagicMock, response: dict, status: str
    ) -> None:
        post.return_value.json.return_value = {"dashboard_id": "x", "title": "t", **response}

        (result,) = import_dashboards_from_template(
            [_write(tmp_path / "main.yaml", {"title": "Main"})], "http://api", {}
        )

        assert result["success"] is True
        assert result["status"] == status

    def test_a_kept_family_that_gained_tabs_says_how_many(
        self, tmp_path: Path, post: MagicMock
    ) -> None:
        post.return_value.json.return_value = {
            "dashboard_id": "x",
            "title": "t",
            "updated": False,
            "status": "kept",
            "tabs_added": 2,
        }

        (result,) = import_dashboards_from_template(
            [_write(tmp_path / "main.yaml", {"main_dashboard": {"title": "M"}, "tabs": []})],
            "http://api",
            {},
        )

        assert (result["status"], result["tabs_added"]) == ("kept", 2)
        assert dashboard_outcome(result) == "kept (2 tabs added)"


@pytest.mark.parametrize(
    ("result", "line"),
    [
        ({"status": "created"}, "created"),
        ({"status": "kept"}, "kept"),
        ({"status": "kept", "tabs_added": 0}, "kept"),
        ({"status": "kept", "tabs_added": 1}, "kept (1 tab added)"),
        ({"status": "kept", "tabs_added": 3}, "kept (3 tabs added)"),
    ],
)
def test_dashboard_outcome(result: dict, line: str) -> None:
    assert dashboard_outcome(result) == line

    def test_failure_is_returned_not_logged_as_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, post: MagicMock
    ) -> None:
        """The caller prints the ✗ line; an ERROR log line repeated it."""
        post.return_value = MagicMock(status_code=404, text="nope")
        post.return_value.json.return_value = {"detail": "Project x not found."}
        logger = MagicMock()
        monkeypatch.setattr(templates_module, "logger", logger)

        (result,) = import_dashboards_from_template(
            [_write(tmp_path / "main.yaml", {"title": "Main"})], "http://api", {}
        )

        assert result["success"] is False
        assert result["error"] == "HTTP 404: Project x not found."
        logger.error.assert_not_called()
