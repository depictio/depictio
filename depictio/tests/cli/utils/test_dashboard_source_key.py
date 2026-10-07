"""The source key `ingest` sends with each dashboard, and `--dashboard-name`.

The server files an imported dashboard under its source key and a refresh with
overwrite updates the dashboard with the same key, so the key has to stay put
across a rename and across template versions.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from depictio.cli.cli.utils import templates as templates_module
from depictio.cli.cli.utils.templates import (
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

    def test_override_outside_the_template_is_a_file_key(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"

        key = dashboard_source_key(
            tmp_path / "mine" / "custom.yaml", "nf-core/rnaseq/3.26.0", template_dir
        )

        assert key == "file:custom.yaml"


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
        assert params["overwrite"] is True

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
