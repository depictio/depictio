"""Workflow metadata from a repository URL, fetched through injected getters."""

from __future__ import annotations

import base64
import json

import pytest

from depictio.api.v1 import remote_fetch
from depictio.api.v1.remote_fetch import RemoteFetchFailed, RemoteURLRejected
from depictio.project_builder import metadata
from depictio.project_builder.metadata import (
    default_getters,
    fetch_workflow_metadata,
    parse_nextflow_config,
    parse_ro_crate,
)

RAW = "https://raw.githubusercontent.com/nf-core/rnaseq/HEAD"
CRATE_URL = f"{RAW}/ro-crate-metadata.json"
CONFIG_URL = f"{RAW}/nextflow.config"
API_URL = "https://api.github.com/repos/nf-core/rnaseq"
LIGHT_URL = f"{RAW}/docs/images/nf-core-rnaseq_logo_light.png"
DARK_URL = f"{RAW}/docs/images/nf-core-rnaseq_logo_dark.png"
REPO = "https://github.com/nf-core/rnaseq"

RO_CRATE = {
    "@graph": [
        {"@id": "ro-crate-metadata.json", "about": {"@id": "./"}},
        {
            "@id": "./",
            "name": "nf-core/rnaseq",
            "version": "3.14.0",
            "description": "RNA sequencing analysis pipeline",
            "license": {"@id": "#mit"},
            "author": [{"@id": "#alice"}, {"@id": "#bob"}],
        },
        {"@id": "#mit", "name": "MIT"},
        {"@id": "#alice", "name": "Alice"},
        {"@id": "#bob", "name": "Bob"},
        {
            "@id": "main.nf",
            "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
            "programmingLanguage": {"@id": "#nextflow"},
        },
        {"@id": "#nextflow", "name": "Nextflow"},
    ]
}

NEXTFLOW_CONFIG = """\
params {
    input = null
}

manifest {
    name            = 'nf-core/rnaseq'
    author          = 'Harshil Patel'
    homePage        = 'https://github.com/nf-core/rnaseq'
    description     = 'RNA sequencing analysis pipeline'
    mainScript      = 'main.nf'
    nextflowVersion = '!>=23.04.0'
    version         = '3.14.0'
}
"""

GITHUB_API = {
    "name": "rnaseq",
    "description": "From the GitHub API",
    "homepage": "https://nf-co.re/rnaseq",
    "license": {"spdx_id": "MIT"},
}

LIGHT, DARK = b"\x89PNG light", b"\x89PNG dark"


class Fetches:
    """Getters over a fixed set of documents, recording every URL asked for."""

    def __init__(self, texts=None, blobs=None, errors=None):
        self.texts = dict(texts or {})
        self.blobs = dict(blobs or {})
        self.errors = dict(errors or {})
        self.asked: list[str] = []

    def _answer(self, url, documents):
        self.asked.append(url)
        if url in self.errors:
            raise self.errors[url]
        if url not in documents:
            raise FileNotFoundError(url)
        return documents[url]

    def text(self, url):
        return self._answer(url, self.texts)

    def data(self, url):
        return self._answer(url, self.blobs)

    def fetch(self, url):
        return fetch_workflow_metadata(url, get_text=self.text, get_bytes=self.data)


def _data_uri(blob: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(blob).decode()


# ── parsing ──────────────────────────────────────────────────────────────────


class TestParseRoCrate:
    def test_the_root_entity_and_the_engine(self):
        out = parse_ro_crate(RO_CRATE)
        assert out == {
            "name": "nf-core/rnaseq",
            "version": "3.14.0",
            "description": "RNA sequencing analysis pipeline",
            "license": "MIT",
            "author": "Alice, Bob",
            "engine": "nextflow",
        }

    def test_the_root_is_found_by_its_default_id_without_a_descriptor(self):
        out = parse_ro_crate({"@graph": [{"@id": "./", "name": "Plain"}]})
        assert out == {"name": "Plain"}

    @pytest.mark.parametrize("data", [{}, {"@graph": None}, {"@graph": "x"}, {"other": []}])
    def test_a_crate_without_a_graph_has_nothing(self, data):
        assert parse_ro_crate(data) == {}

    def test_strings_and_unresolved_references_are_names_too(self):
        out = parse_ro_crate(
            {
                "@graph": [
                    {"@id": "./", "license": "Apache-2.0", "author": [{"@id": "#nobody"}, "Eve"]},
                ]
            }
        )
        assert out == {"license": "Apache-2.0", "author": "#nobody, Eve"}

    @pytest.mark.parametrize(
        ("language", "engine"),
        [
            ("Nextflow", "nextflow"),
            ("Nextflow DSL2", "nextflow"),
            ("Snakemake", "snakemake"),
            ("Galaxy", "galaxy"),
            ("Python 3", "python"),
            ("R", "r"),
            # "r" counts as a whole word only: not the "r" in "Rust".
            ("Rust", "rust"),
            ("Common Workflow Language", "common workflow language"),
        ],
    )
    def test_the_engine_is_the_programming_language_normalised(self, language, engine):
        crate = {
            "@graph": [
                {
                    "@id": "wf",
                    "@type": "ComputationalWorkflow",
                    "programmingLanguage": language,
                }
            ]
        }
        assert parse_ro_crate(crate) == {"engine": engine}

    def test_a_language_entity_is_looked_up_for_its_name(self):
        crate = {
            "@graph": [
                {"@id": "wf", "@type": "SoftwareSourceCode", "programmingLanguage": {"@id": "#l"}},
                {"@id": "#l", "name": "Snakemake"},
            ]
        }
        assert parse_ro_crate(crate)["engine"] == "snakemake"

    def test_only_workflow_entities_say_what_the_engine_is(self):
        crate = {"@graph": [{"@id": "x", "@type": "File", "programmingLanguage": "Snakemake"}]}
        assert "engine" not in parse_ro_crate(crate)


class TestParseNextflowConfig:
    def test_the_manifest_fields_and_the_engine(self):
        assert parse_nextflow_config(NEXTFLOW_CONFIG) == {
            "engine": "nextflow",
            "name": "nf-core/rnaseq",
            "version": "3.14.0",
            "description": "RNA sequencing analysis pipeline",
            "author": "Harshil Patel",
            "homepage": "https://github.com/nf-core/rnaseq",
        }

    def test_a_config_without_a_manifest_is_still_nextflow(self):
        assert parse_nextflow_config("params { x = 1 }\n") == {"engine": "nextflow"}

    def test_it_is_the_models_parser_that_reads_the_block(self):
        from depictio.models.models.nextflow import parse_manifest_block

        parsed = parse_nextflow_config(NEXTFLOW_CONFIG)
        assert {k: v for k, v in parsed.items() if k != "engine"} == parse_manifest_block(
            NEXTFLOW_CONFIG
        )


# ── fetching ─────────────────────────────────────────────────────────────────


class TestFetchWorkflowMetadata:
    def test_an_nf_core_repository_is_nextflow_in_the_nf_core_catalog_with_no_network(self):
        fetches = Fetches()
        out = fetches.fetch(REPO)
        assert out["repository_url"] == REPO
        assert out["engine"] == "nextflow"
        assert out["catalog"] == {"name": "nf-core", "url": REPO}
        assert out["sources"] == ["nf-core"]
        assert out["blocked"] is False
        assert "logo_light" not in out and "logo_dark" not in out

    def test_it_reads_the_documents_at_fixed_urls_built_from_the_repository(self):
        fetches = Fetches()
        fetches.fetch(REPO)
        assert fetches.asked == [
            CRATE_URL,
            CONFIG_URL,
            API_URL,
            LIGHT_URL,
            DARK_URL,
        ]

    def test_ro_crate_nextflow_config_github_and_logos_are_merged_in_priority_order(self):
        fetches = Fetches(
            texts={
                CRATE_URL: json.dumps(RO_CRATE),
                CONFIG_URL: NEXTFLOW_CONFIG.replace("3.14.0", "9.9.9"),
                API_URL: json.dumps(GITHUB_API),
            },
            blobs={LIGHT_URL: LIGHT, DARK_URL: DARK},
        )
        out = fetches.fetch(REPO)
        # RO-Crate first, then the config fills what is left, then the GitHub API.
        assert out["name"] == "nf-core/rnaseq"
        assert out["version"] == "3.14.0"
        assert out["description"] == "RNA sequencing analysis pipeline"
        assert out["author"] == "Alice, Bob"
        assert out["license"] == "MIT"
        assert out["homepage"] == "https://github.com/nf-core/rnaseq"
        assert out["engine"] == "nextflow"
        assert out["logo_light"] == _data_uri(LIGHT)
        assert out["logo_dark"] == _data_uri(DARK)
        assert out["sources"] == ["nf-core", "ro-crate", "nextflow.config", "logo"]
        assert out["blocked"] is False

    def test_later_documents_are_not_read_once_the_fields_are_filled(self):
        fetches = Fetches(
            texts={CRATE_URL: json.dumps(RO_CRATE), CONFIG_URL: NEXTFLOW_CONFIG},
        )
        fetches.fetch(REPO)
        assert API_URL not in fetches.asked

    def test_the_github_api_fills_what_the_repository_files_do_not_say(self):
        api = "https://api.github.com/repos/someone/pipeline"
        fetches = Fetches(texts={api: json.dumps(GITHUB_API)})
        out = fetches.fetch("https://github.com/someone/pipeline")
        assert out["sources"] == ["github"]
        assert out["name"] == "rnaseq"
        assert out["description"] == "From the GitHub API"
        assert out["homepage"] == "https://nf-co.re/rnaseq"
        assert out["license"] == "MIT"
        assert "engine" not in out and "catalog" not in out

    def test_a_generic_repository_reads_the_crate_the_config_and_the_api_at_its_own_path(self):
        fetches = Fetches()
        out = fetches.fetch("https://github.com/someone/pipeline")
        raw = "https://raw.githubusercontent.com/someone/pipeline/HEAD"
        assert fetches.asked == [
            f"{raw}/ro-crate-metadata.json",
            f"{raw}/nextflow.config",
            "https://api.github.com/repos/someone/pipeline",
        ]
        assert out["sources"] == []
        assert out == {
            "repository_url": "https://github.com/someone/pipeline",
            "sources": [],
            "blocked": False,
        }

    def test_a_repository_url_is_trimmed_and_may_end_in_git_or_carry_a_path(self):
        fetches = Fetches()
        out = fetches.fetch("  https://github.com/someone/pipeline.git/tree/main/docs  ")
        assert out["repository_url"] == "https://github.com/someone/pipeline.git/tree/main/docs"
        assert fetches.asked[0] == (
            "https://raw.githubusercontent.com/someone/pipeline/HEAD/ro-crate-metadata.json"
        )

    def test_http_and_www_github_hosts_are_read_all_the_same_from_https_urls(self):
        for url in ("http://github.com/a/b", "https://www.github.com/a/b"):
            fetches = Fetches()
            fetches.fetch(url)
            assert fetches.asked[0] == (
                "https://raw.githubusercontent.com/a/b/HEAD/ro-crate-metadata.json"
            )

    @pytest.mark.parametrize(
        "url",
        [
            "https://gitlab.com/someone/pipeline",
            "https://example.org/someone/pipeline",
            "https://github.com.evil.example/nf-core/rnaseq",
            "https://github.com@evil.example/nf-core/rnaseq",
            "https://evil.example/github.com/nf-core/rnaseq",
            "https://github.com/nf-core",
            "https://github.com/",
            "https://workflowhub.eu/workflows/1",
        ],
    )
    def test_nothing_is_fetched_for_a_url_that_is_not_a_github_repository(self, url):
        fetches = Fetches()
        out = fetches.fetch(url)
        assert fetches.asked == []
        assert out == {"repository_url": url, "sources": [], "blocked": False}

    def test_the_server_never_fetches_the_url_it_was_given(self):
        fetches = Fetches()
        fetches.fetch("https://github.com/someone/pipeline?redirect=http://169.254.169.254/")
        assert all(
            url.startswith(("https://raw.githubusercontent.com/", "https://api.github.com/"))
            for url in fetches.asked
        )

    @pytest.mark.parametrize("url", ["", "   ", None])
    def test_a_url_is_required(self, url):
        with pytest.raises(ValueError, match="repository url is required"):
            fetch_workflow_metadata(url, get_text=Fetches().text, get_bytes=Fetches().data)

    @pytest.mark.parametrize(
        "url",
        [
            "github.com/nf-core/rnaseq",
            "ftp://github.com/nf-core/rnaseq",
            "file:///etc/passwd",
            "git@github.com:nf-core/rnaseq.git",
            "javascript:alert(1)",
        ],
    )
    def test_a_url_that_is_not_http_is_refused_before_anything_is_fetched(self, url):
        fetches = Fetches()
        with pytest.raises(ValueError, match="must start with http:// or https://"):
            fetches.fetch(url)
        assert fetches.asked == []

    def test_a_document_that_is_not_json_is_skipped(self):
        fetches = Fetches(texts={CRATE_URL: "<html>not json</html>", API_URL: "also not json"})
        out = fetches.fetch(REPO)
        assert out["sources"] == ["nf-core"]

    def test_a_crate_with_nothing_in_it_is_not_a_source(self):
        fetches = Fetches(texts={CRATE_URL: json.dumps({"@graph": []})})
        assert fetches.fetch(REPO)["sources"] == ["nf-core"]

    def test_a_config_with_a_manifest_is_a_source(self):
        fetches = Fetches(texts={CONFIG_URL: NEXTFLOW_CONFIG})
        out = fetches.fetch(REPO)
        assert out["sources"] == ["nf-core", "nextflow.config"]
        assert out["version"] == "3.14.0"

    def test_without_a_dark_logo_the_light_one_serves_both_and_the_other_way_round(self):
        light_only = Fetches(blobs={LIGHT_URL: LIGHT}).fetch(REPO)
        assert light_only["logo_light"] == light_only["logo_dark"] == _data_uri(LIGHT)
        dark_only = Fetches(blobs={DARK_URL: DARK}).fetch(REPO)
        assert dark_only["logo_light"] == dark_only["logo_dark"] == _data_uri(DARK)
        assert "logo" in dark_only["sources"]

    def test_only_nf_core_pipelines_have_a_logo_fetched(self):
        fetches = Fetches(blobs={LIGHT_URL: LIGHT})
        fetches.fetch("https://github.com/someone/rnaseq")
        assert not any("logo" in url for url in fetches.asked)

    def test_an_empty_or_oversized_logo_is_not_shown(self):
        empty = Fetches(blobs={LIGHT_URL: b"", DARK_URL: b""}).fetch(REPO)
        assert "logo_light" not in empty and "logo" not in empty["sources"]
        too_big = b"x" * (metadata._MAX_LOGO_BYTES + 1)
        big = Fetches(blobs={LIGHT_URL: too_big, DARK_URL: too_big}).fetch(REPO)
        assert "logo_light" not in big and "logo_dark" not in big

    def test_a_logo_exactly_at_the_cap_is_kept(self):
        blob = b"x" * metadata._MAX_LOGO_BYTES
        out = Fetches(blobs={LIGHT_URL: blob}).fetch(REPO)
        assert out["logo_light"] == _data_uri(blob)

    def test_a_long_markdown_description_is_reduced_to_a_short_plain_summary(self):
        readme = (
            '<h1><img src="logo.png"></h1>\n'
            "[![badge](b.svg)](https://ci)\n"
            "## Introduction\n"
            "**nf-core/rnaseq** is a [pipeline](https://nf-co.re) for RNA-seq. " + "More. " * 100
        )
        crate = {"@graph": [{"@id": "./", "description": readme}]}
        out = Fetches(texts={CRATE_URL: json.dumps(crate)}).fetch(REPO)
        description = out["description"]
        assert "<" not in description and "![" not in description and "](" not in description
        assert description.startswith("Introduction nf-core/rnaseq is a pipeline for RNA-seq.")
        assert len(description) <= 281 and description.endswith("…")

    def test_a_short_description_is_left_alone(self):
        crate = {"@graph": [{"@id": "./", "description": "Does science"}]}
        assert (
            Fetches(texts={CRATE_URL: json.dumps(crate)}).fetch(REPO)["description"]
            == "Does science"
        )


class TestBlocked:
    """``blocked``: the server's remote policy refused a request, which is the
    operator's decision and not an outage."""

    def test_a_policy_refusal_is_reported(self):
        fetches = Fetches(errors={CRATE_URL: RemoteURLRejected("not in the allowlist")})
        out = fetches.fetch(REPO)
        assert out["blocked"] is True
        # The rest is still read, and what is inferred offline still shows.
        assert out["engine"] == "nextflow" and out["sources"] == ["nf-core"]

    def test_a_refused_logo_is_reported_too(self):
        out = Fetches(errors={LIGHT_URL: RemoteURLRejected("no")}).fetch(REPO)
        assert out["blocked"] is True

    def test_an_unreachable_host_is_not_a_refusal(self):
        out = Fetches(
            errors={CRATE_URL: RemoteFetchFailed("Could not fetch the provided URL.")}
        ).fetch(REPO)
        assert out["blocked"] is False

    @pytest.mark.parametrize("error", [OSError("offline"), TimeoutError(), ValueError("boom")])
    def test_any_other_failure_only_means_fewer_fields(self, error):
        fetches = Fetches(errors={CRATE_URL: error, CONFIG_URL: error, API_URL: error})
        out = fetches.fetch(REPO)
        assert out["blocked"] is False and out["sources"] == ["nf-core"]

    def test_one_refusal_among_failures_is_enough(self):
        fetches = Fetches(
            errors={
                CRATE_URL: OSError("offline"),
                CONFIG_URL: RemoteURLRejected("blocked"),
                API_URL: RemoteFetchFailed("down"),
            }
        )
        assert fetches.fetch(REPO)["blocked"] is True

    def test_a_refusal_does_not_stop_the_other_documents(self):
        fetches = Fetches(
            texts={CONFIG_URL: NEXTFLOW_CONFIG},
            errors={CRATE_URL: RemoteURLRejected("blocked")},
        )
        out = fetches.fetch(REPO)
        assert out["blocked"] is True and out["version"] == "3.14.0"


# ── the getters used when none are injected ──────────────────────────────────


class TestDefaultGetters:
    @pytest.fixture
    def gateway(self, monkeypatch):
        """Stand-ins for the four fetch functions, recording how they were called."""
        calls: list[tuple] = []

        def record(name, result):
            def fetch(url, **kwargs):
                calls.append((name, url, kwargs))
                return result

            return fetch

        monkeypatch.setattr(remote_fetch, "fetch_validated_text", record("gateway_text", "{}"))
        monkeypatch.setattr(remote_fetch, "fetch_validated_bytes", record("gateway_bytes", b"png"))
        monkeypatch.setattr(remote_fetch, "direct_fetch_text", record("direct_text", "{}"))
        monkeypatch.setattr(remote_fetch, "direct_fetch_bytes", record("direct_bytes", b"png"))
        return calls

    def test_on_a_server_every_read_goes_through_the_gateway(self, monkeypatch, gateway):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
        get_text, get_bytes = default_getters()
        get_text("https://raw.githubusercontent.com/a/b/HEAD/x")
        get_bytes("https://raw.githubusercontent.com/a/b/HEAD/logo.png")
        assert gateway == [
            (
                "gateway_text",
                "https://raw.githubusercontent.com/a/b/HEAD/x",
                {"max_bytes": 512 * 1024},
            ),
            (
                "gateway_bytes",
                "https://raw.githubusercontent.com/a/b/HEAD/logo.png",
                {"max_bytes": 1_000_000},
            ),
        ]

    def test_an_unset_context_fails_closed_to_the_gateway(self, monkeypatch, gateway):
        monkeypatch.delenv("DEPICTIO_CONTEXT", raising=False)
        default_getters()[0]("https://raw.githubusercontent.com/a/b/HEAD/x")
        assert gateway[0][0] == "gateway_text"

    def test_from_the_cli_the_direct_reads_are_used(self, monkeypatch, gateway):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "cli")
        get_text, get_bytes = default_getters()
        get_text("https://raw.githubusercontent.com/a/b/HEAD/x")
        get_bytes("https://raw.githubusercontent.com/a/b/HEAD/logo.png")
        assert [call[0] for call in gateway] == ["direct_text", "direct_bytes"]
        assert gateway[1][2] == {"max_bytes": 1_000_000}

    def test_fetching_without_getters_uses_the_gateway_on_a_server(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
        asked: list[tuple[str, str]] = []

        def text(url, **kwargs):
            asked.append(("text", url))
            return json.dumps(RO_CRATE) if url == CRATE_URL else "{}"

        def blob(url, **kwargs):
            asked.append(("bytes", url))
            return LIGHT

        monkeypatch.setattr(remote_fetch, "fetch_validated_text", text)
        monkeypatch.setattr(remote_fetch, "fetch_validated_bytes", blob)
        monkeypatch.setattr(
            remote_fetch, "direct_fetch_text", lambda url: pytest.fail("a direct read on a server")
        )
        out = fetch_workflow_metadata(REPO)
        assert out["name"] == "nf-core/rnaseq" and out["logo_light"] == _data_uri(LIGHT)
        assert ("text", CRATE_URL) in asked and ("bytes", LIGHT_URL) in asked

    def test_a_gateway_refusal_surfaces_as_blocked(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "server")

        def refuse(url, **kwargs):
            raise RemoteURLRejected("host not allowed")

        monkeypatch.setattr(remote_fetch, "fetch_validated_text", refuse)
        monkeypatch.setattr(remote_fetch, "fetch_validated_bytes", refuse)
        out = fetch_workflow_metadata(REPO)
        assert out["blocked"] is True
        assert out["sources"] == ["nf-core"]

    def test_one_injected_getter_leaves_the_other_to_the_default(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
        blobs: list[str] = []
        monkeypatch.setattr(
            remote_fetch, "fetch_validated_bytes", lambda url, **kw: blobs.append(url) or LIGHT
        )
        monkeypatch.setattr(
            remote_fetch, "fetch_validated_text", lambda url, **kw: pytest.fail("not injected")
        )
        out = fetch_workflow_metadata(REPO, get_text=lambda url: "{}")
        assert blobs == [LIGHT_URL, DARK_URL]
        assert out["logo_light"] == _data_uri(LIGHT)

    def test_injected_getters_are_used_instead_of_the_defaults(self, monkeypatch):
        monkeypatch.setattr(metadata, "default_getters", lambda: pytest.fail("defaults asked for"))
        Fetches().fetch(REPO)
