"""Tests for `--bind TAG=LOCATION` mode inference (depictio.cli.cli.utils.bindings).

The contract these lock down: a location's *shape* decides the scan mode, the
scan configs produced are valid against the real `Scan` model, and anything
ambiguous fails loudly rather than silently binding to the wrong thing.
"""

import copy
import re

import pytest

from depictio.cli.cli.utils.bindings import (
    BindingError,
    apply_bindings,
    assert_no_unbound_vars,
    id_regex_from_glob,
    infer_scan,
    parse_binding,
)
from depictio.models.models.data_collections import Scan


def _config():
    return {
        "workflows": [
            {
                "name": "wf",
                "data_location": {"structure": "flat", "locations": ["/old/root"]},
                "data_collections": [
                    {
                        "data_collection_tag": "samples",
                        "config": {
                            "scan": {
                                "mode": "manifest",
                                "scan_parameters": {
                                    "manifest_url": "https://x/m.json",
                                    "manifest_type": "samples",
                                },
                            }
                        },
                    },
                    {"data_collection_tag": "measurements", "config": {}},
                ],
            }
        ]
    }


class TestParseBinding:
    def test_splits_tag_and_location(self):
        assert parse_binding("samples=s3://b/x") == ("samples", "s3://b/x")

    def test_location_may_contain_equals(self):
        """Query strings carry '=' — only the first one separates tag from location."""
        assert parse_binding("s=https://h/a?x=1&y=2") == ("s", "https://h/a?x=1&y=2")

    @pytest.mark.parametrize("spec", ["samples", "=s3://b/x", "samples="])
    def test_malformed_specs_rejected(self, spec):
        with pytest.raises(BindingError):
            parse_binding(spec)


class TestInferScan:
    def test_s3_glob_becomes_prefix_scan(self):
        scan, root = infer_scan("s3://b/run42/*.csv")
        assert scan["mode"] == "s3_prefix"
        assert scan["scan_parameters"]["prefix"] == "s3://b/run42/"
        assert scan["scan_parameters"]["pattern"] == "*.csv"
        assert root is None

    def test_s3_trailing_slash_matches_everything(self):
        scan, _ = infer_scan("s3://b/run42/")
        assert scan["mode"] == "s3_prefix"
        assert scan["scan_parameters"]["pattern"] == "*"

    def test_bare_s3_key_is_a_single_url(self):
        scan, _ = infer_scan("s3://b/run42/a.csv")
        assert scan["mode"] == "url"

    def test_https_file_is_a_url(self):
        scan, _ = infer_scan("https://h/d.csv")
        assert scan == {"mode": "url", "scan_parameters": {"url": "https://h/d.csv"}}

    def test_https_glob_rejected_with_actionable_message(self):
        """HTTPS has no listing operation, so a glob can never be honoured."""
        with pytest.raises(BindingError, match="no listing operation"):
            infer_scan("https://h/*.csv")

    def test_unknown_scheme_rejected(self):
        with pytest.raises(BindingError, match="Unsupported scheme"):
            infer_scan("ftp://h/a.csv")

    def test_missing_local_path_rejected(self):
        with pytest.raises(BindingError, match="does not exist"):
            infer_scan("/nope/definitely/missing.csv")

    def test_local_file_is_single(self, tmp_path):
        target = tmp_path / "a.csv"
        target.write_text("x")
        scan, root = infer_scan(str(target))
        assert scan["mode"] == "single"
        assert scan["scan_parameters"]["filename"] == str(target.resolve())
        assert root is None

    def test_local_glob_is_recursive_and_yields_walk_root(self, tmp_path):
        scan, root = infer_scan(f"{tmp_path}/*.csv")
        assert scan["mode"] == "recursive"
        assert root == str(tmp_path.resolve())

    def test_local_dir_preserves_the_templates_pattern(self, tmp_path):
        """Repointing the root must not silently widen what counts as a match."""
        existing = {
            "mode": "recursive",
            "scan_parameters": {"regex_config": {"pattern": "KEEP.*"}},
        }
        scan, root = infer_scan(str(tmp_path), existing_scan=existing)
        assert scan["scan_parameters"]["regex_config"]["pattern"] == "KEEP.*"
        assert root == str(tmp_path.resolve())

    @pytest.mark.parametrize(
        "location",
        ["s3://b/run42/*.csv", "s3://b/run42/", "s3://b/a.csv", "https://h/d.csv"],
    )
    def test_produced_scans_validate_against_the_model(self, location):
        scan, _ = infer_scan(location)
        Scan(**scan)


class TestIdRegexFromGlob:
    def test_single_star_captures_the_entity_id(self):
        regex = id_regex_from_glob("*.samples.csv")
        assert re.search(regex, "sample_A.samples.csv").group(1) == "sample_A"

    def test_capture_stops_at_a_path_separator(self):
        """A nested key must not yield 'run1/sample_A' — that would not join
        against a plain 'sample_A' registered from another prefix."""
        regex = id_regex_from_glob("*.samples.csv")
        assert re.search(regex, "run1/sample_A.samples.csv") is None

    def test_does_not_match_a_different_role(self):
        regex = id_regex_from_glob("*.samples.csv")
        assert re.search(regex, "sample_A.measurements.csv") is None

    def test_prefix_and_suffix_around_the_star(self):
        regex = id_regex_from_glob("run_*_final.tsv")
        assert re.search(regex, "run_42_final.tsv").group(1) == "42"

    @pytest.mark.parametrize("pattern", ["*.*.csv", "data.csv", "*", "?.csv", "[ab].csv"])
    def test_ambiguous_globs_yield_no_id(self, pattern):
        """No id beats a wrong id: a bad join key silently mis-joins."""
        assert id_regex_from_glob(pattern) is None


class TestApplyBindings:
    def test_rewrites_the_named_data_collections(self):
        config = _config()
        notes = apply_bindings(
            config,
            ["samples=s3://b/run42/*.samples.csv", "measurements=https://h/m.csv"],
        )
        dcs = config["workflows"][0]["data_collections"]
        assert dcs[0]["config"]["scan"]["mode"] == "s3_prefix"
        assert dcs[1]["config"]["scan"]["mode"] == "url"
        assert len(notes) == 2

    def test_s3_glob_binding_carries_a_join_key(self):
        config = _config()
        apply_bindings(config, ["samples=s3://b/run42/*.samples.csv"])
        params = config["workflows"][0]["data_collections"][0]["config"]["scan"]["scan_parameters"]
        assert params["id_regex"]

    def test_unknown_tag_is_rejected_and_lists_the_real_ones(self):
        """A silently ignored --bind would leave the DC on the template's
        original location — the exact surprise this flag exists to remove."""
        with pytest.raises(BindingError) as excinfo:
            apply_bindings(_config(), ["nope=s3://b/x/"])
        assert "measurements" in str(excinfo.value)

    def test_local_binding_sets_the_workflow_walk_root(self, tmp_path):
        config = _config()
        apply_bindings(config, [f"samples={tmp_path}/*.csv"])
        assert config["workflows"][0]["data_location"]["locations"] == [str(tmp_path.resolve())]

    def test_conflicting_local_roots_rejected(self, tmp_path):
        """data_location is per-workflow, so two local binds cannot disagree."""
        first = tmp_path / "a"
        second = tmp_path / "b"
        first.mkdir()
        second.mkdir()
        with pytest.raises(BindingError, match="Conflicting local roots"):
            apply_bindings(
                _config(),
                [f"samples={first}/*.csv", f"measurements={second}/*.csv"],
            )

    def test_remote_binding_replaces_a_placeholder_data_location(self):
        config = _config()
        config["workflows"][0]["data_location"]["locations"] = ["__DEPICTIO_UNBOUND_MANIFEST_URL__"]
        apply_bindings(config, ["samples=s3://b/run42/*.samples.csv"])
        assert config["workflows"][0]["data_location"]["locations"] == [
            "s3://b/run42/*.samples.csv"
        ]

    def test_no_specs_is_a_no_op(self):
        config = _config()
        before = copy.deepcopy(config)
        assert apply_bindings(config, []) == []
        assert config == before


class TestAssertNoUnboundVars:
    def test_surviving_sentinel_in_workflows_raises_with_the_variable_name(self):
        config = {
            "workflows": [
                {
                    "data_collections": [
                        {
                            "config": {
                                "scan": {
                                    "scan_parameters": {
                                        "manifest_url": "__DEPICTIO_UNBOUND_MANIFEST_URL__"
                                    }
                                }
                            }
                        }
                    ]
                }
            ]
        }
        with pytest.raises(BindingError, match="MANIFEST_URL"):
            assert_no_unbound_vars(config)

    def test_provenance_is_not_treated_as_a_failure(self):
        """template_origin records what the template declared, not what drives
        ingestion — an unsupplied variable legitimately appears there."""
        config = {
            "workflows": [],
            "template_origin": {
                "variables": {"MANIFEST_URL": "__DEPICTIO_UNBOUND_MANIFEST_URL__"},
                "config_snapshot": {"x": "__DEPICTIO_UNBOUND_MANIFEST_URL__"},
            },
        }
        assert_no_unbound_vars(config)
        origin = config["template_origin"]
        # Never record a synthetic value as though the user had supplied it.
        assert "MANIFEST_URL" not in origin["variables"]
        assert origin["config_snapshot"]["x"] == "{MANIFEST_URL}"
