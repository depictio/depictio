"""The recipe inputs an ingestion report lists for a transformed collection."""

from unittest.mock import patch

from depictio.api.v1.endpoints.projects_endpoints.ingestion_report import _dc_source_inputs


class _Source:
    def __init__(self, ref: str, path: str):
        self.ref, self.path, self.dc_ref = ref, path, None


class _Recipe:
    SOURCES = [_Source("samplesheet", "input/samplesheet.csv")]


def _inputs(override, data_root):
    config = {
        "source": "transformed",
        "transform": {"recipe": "nf-core/test/samples.py", "source_overrides": override},
    }
    with patch("depictio.recipes.load_recipe", return_value=_Recipe):
        return _dc_source_inputs(config, data_root)


def test_a_relative_source_is_resolved_under_the_data_root(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "samplesheet.csv").write_text("sample\n")
    assert _inputs({}, str(tmp_path)) == [str((tmp_path / "input" / "samplesheet.csv").resolve())]


def test_an_override_outside_the_root_is_shown_as_stored(tmp_path):
    """Not joined onto the root, and not probed on this server's disk: a
    symlink's target or a file's existence is not the reader's to learn."""
    target = tmp_path / "real.csv"
    target.write_text("sample\n")
    link = tmp_path / "link.csv"
    link.symlink_to(target)
    root = str(tmp_path / "run")
    assert _inputs({"samplesheet": str(link)}, root) == [str(link)]
    assert _inputs({"samplesheet": "https://example.org/sheet.csv"}, root) == [
        "https://example.org/sheet.csv"
    ]
