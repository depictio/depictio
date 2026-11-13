"""``parse_manifest_block``: the ``manifest {}`` of a ``nextflow.config``, as text.

Shared by run-info detection (a pipeline checkout on disk) and the Project
Builder's repository metadata (a ``nextflow.config`` fetched from GitHub).
"""

import pytest

from depictio.models.models.nextflow import MANIFEST_FIELDS, parse_manifest_block

NF_CORE_CONFIG = """\
/*
 * nf-core/rnaseq Nextflow config file
 */

params {
    input = null
}

process {
    cpus = 2
}

manifest {
    name            = 'nf-core/rnaseq'
    author          = 'Harshil Patel'
    contributors    = [
        [
            name: 'Harshil Patel',
            affiliation: 'Seqera',
            github: '@drpatelh',
            contribution: ['author'],
        ],
    ]
    homePage        = 'https://github.com/nf-core/rnaseq'
    description     = 'RNA sequencing analysis pipeline'
    mainScript      = 'main.nf'
    defaultBranch   = 'master'
    nextflowVersion = '!>=24.04.2'
    version         = '3.14.0'
    doi             = ''
}
"""


class TestParseManifestBlock:
    def test_every_field_is_returned_under_its_name(self):
        assert parse_manifest_block(NF_CORE_CONFIG) == {
            "name": "nf-core/rnaseq",
            "author": "Harshil Patel",
            "homepage": "https://github.com/nf-core/rnaseq",
            "description": "RNA sequencing analysis pipeline",
            "version": "3.14.0",
        }

    def test_the_fields_read_are_the_documented_ones(self):
        assert MANIFEST_FIELDS == {
            "name": "name",
            "version": "version",
            "description": "description",
            "author": "author",
            "homePage": "homepage",
        }

    def test_the_nextflow_version_constraint_is_not_a_version(self):
        parsed = parse_manifest_block(NF_CORE_CONFIG)
        assert "nextflowVersion" not in parsed
        assert "!>=24.04.2" not in parsed.values()

    def test_the_map_of_contributors_does_not_stand_in_for_the_name(self):
        """`name: 'Harshil Patel'` inside a list is a map entry, not `name = ...`."""
        assert parse_manifest_block(NF_CORE_CONFIG)["name"] == "nf-core/rnaseq"

    @pytest.mark.parametrize("quote", ["'", '"'])
    def test_either_quote_works(self, quote):
        text = f"manifest {{\n    name = {quote}a/b{quote}\n    version = {quote}1.0{quote}\n}}\n"
        assert parse_manifest_block(text) == {"name": "a/b", "version": "1.0"}

    def test_values_are_stripped(self):
        text = "manifest {\n    name = '  padded  '\n}\n"
        assert parse_manifest_block(text) == {"name": "padded"}

    def test_only_the_entries_that_are_there_come_back(self):
        assert parse_manifest_block("manifest {\n    name = 'only'\n}\n") == {"name": "only"}

    def test_an_empty_value_is_not_an_entry(self):
        assert parse_manifest_block("manifest {\n    name = 'x'\n    doi = ''\n}\n") == {
            "name": "x"
        }

    def test_a_commented_out_entry_is_not_read(self):
        text = "manifest {\n    // name = 'old/name'\n    name = 'new/name'\n}\n"
        assert parse_manifest_block(text) == {"name": "new/name"}

    def test_the_first_manifest_entry_wins(self):
        text = "manifest {\n    name = 'first'\n    name = 'second'\n}\n"
        assert parse_manifest_block(text)["name"] == "first"

    def test_the_manifest_may_be_the_whole_file_or_the_last_block(self):
        assert parse_manifest_block("manifest {\n    name = 'a'\n}") == {"name": "a"}
        assert parse_manifest_block("manifest{\n    name = 'a'\n}\n") == {"name": "a"}

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   \n",
            "process {\n    cpus = 2\n}\n",
            "params { name = 'not-a-manifest' }\n",
            "manifest\n",
        ],
    )
    def test_text_without_a_manifest_block_is_empty(self, text):
        assert parse_manifest_block(text) == {}

    def test_a_manifest_block_with_no_known_entry_is_empty(self):
        assert parse_manifest_block("manifest {\n    mainScript = 'main.nf'\n}\n") == {}

    def test_the_entries_outside_the_block_are_not_read(self):
        text = "name = 'outside'\nmanifest {\n    version = '1'\n}\nversion = '9'\n"
        assert parse_manifest_block(text) == {"version": "1"}
