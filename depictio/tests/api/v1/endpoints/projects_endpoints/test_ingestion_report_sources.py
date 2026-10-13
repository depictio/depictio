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


def test_a_relative_source_is_joined_onto_the_data_root_unprobed(tmp_path, monkeypatch):
    """A shared server does not look at its disk for it: the data root is the
    project's word too, so ``../etc/hosts`` would be an oracle."""
    monkeypatch.delenv("DEPICTIO_LOCAL_DATA_ROOTS", raising=False)
    (tmp_path / "real").mkdir()
    (tmp_path / "run").symlink_to(tmp_path / "real")
    assert _inputs({}, str(tmp_path / "run")) == [str(tmp_path / "run" / "input/samplesheet.csv")]
    assert _inputs({"samplesheet": "../etc/hosts"}, "/usr") == ["/etc/hosts"]


def test_under_depictio_local_a_source_below_a_root_is_resolved(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    monkeypatch.setenv("DEPICTIO_AUTH_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("DEPICTIO_LOCAL_DATA_ROOTS", str(tmp_path))
    (tmp_path / "run" / "input").mkdir(parents=True)
    (tmp_path / "run" / "input" / "samplesheet.csv").write_text("sample\n")
    assert _inputs({}, str(tmp_path / "run")) == [
        str((tmp_path / "run" / "input" / "samplesheet.csv").resolve())
    ]
    assert _inputs({}, "s3://bucket/run") == ["s3://bucket/run/input/samplesheet.csv"]


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
