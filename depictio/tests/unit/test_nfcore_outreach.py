"""Offline unit tests for scripts/nfcore_outreach.py (no network, no gh)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "nfcore_outreach.py"
# The manifest loader rejects anything that is not a real 40-char commit sha.
_SHA = "a" * 40


@pytest.fixture(scope="module")
def nfo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nfcore_outreach", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: the script's dataclasses defer their annotations
    # (`from __future__ import annotations`), and resolving them looks the
    # defining module up in sys.modules.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[spec.name]
        raise
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture()
def template_dir(tmp_path: Path) -> Path:
    """A minimal one-pipeline template tree, shaped like the real ones."""
    import yaml

    root = tmp_path / "nf-core" / "demoseq" / "1.2.0"
    (root / "dashboards").mkdir(parents=True)
    (root / "docs" / "screenshots").mkdir(parents=True)

    (root / "template.yaml").write_text(
        yaml.safe_dump(
            {
                "template": {
                    "template_id": "nf-core/demoseq/1.2.0",
                    "description": "Demo template",
                    "variables": [
                        {"name": "DATA_ROOT", "description": "Run dir", "required": True},
                        {"name": "SAMPLESHEET_FILE", "description": "Path to it, when omitted"},
                        {"name": "SKIP_QC", "description": "For a --skip_qc run (--var SKIP_QC)"},
                    ],
                },
                "workflows": [
                    {
                        "data_collections": [
                            {
                                "data_collection_tag": "counts",
                                "config": {
                                    "type": "Table",
                                    "scan": {"scan_parameters": {"filename": "{DATA_ROOT}/c.tsv"}},
                                },
                            },
                            {
                                "data_collection_tag": "peaks",
                                "optional": True,
                                "config": {
                                    "type": "Table",
                                    "scan": {
                                        "scan_parameters": {
                                            "regex_config": {"pattern": r".*\.bed$"}
                                        }
                                    },
                                },
                            },
                            {
                                "data_collection_tag": "derived",
                                "config": {
                                    "source": "transformed",
                                    "transform": {"recipe": "demo/thing.py"},
                                },
                            },
                        ]
                    }
                ],
            }
        )
    )
    (root / "dashboards" / "base.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "main_dashboard": {
                    "title": "nf-core/demoseq",
                    "subtitle": "The main one",
                    "project_tag": "Demo Project",
                    "main_tab_name": "QC",
                    "grid_sections": [{"name": "Overview"}],
                    "components": [
                        {"component_type": "card", "title": "Samples"},
                        {"component_type": "advanced_viz", "use": "demo/some_render"},
                    ],
                },
                "tabs": [
                    {
                        "title": "Peaks",
                        "subtitle": "The other one",
                        "grid_sections": [{"name": "Calls"}],
                        "components": [{"component_type": "table"}],
                    }
                ],
            }
        )
    )
    (root / "megatest.yaml").write_text(
        yaml.safe_dump(
            {
                "pipeline": "demoseq",
                "version": "1.2.0",
                "results_sha": _SHA,
                "run_root": "route_a/",
                "multiqc": {"version": "1.30"},
                "keys": ["c.tsv"],
            }
        )
    )
    (root / "docs" / "dashboards.md").write_text("# docs")
    (root / "docs" / "screenshots" / "qc.png").write_bytes(b"")
    return tmp_path / "nf-core"


def test_collect_facts_reads_the_shipped_template(nfo: ModuleType, template_dir: Path) -> None:
    facts = nfo.collect_facts("demoseq", "1.2.0", projects_dir=template_dir)

    assert facts.template_id == "nf-core/demoseq/1.2.0"
    assert [t.title for t in facts.tabs] == ["QC", "Peaks"]
    assert facts.tabs[0].sections == ["Overview"]
    assert facts.card_titles == ["Samples"]
    assert facts.catalog_tools == ["demo"]
    assert facts.component_counts == {"advanced_viz": 1, "card": 1, "table": 1}
    assert facts.megatest_sha == _SHA
    assert facts.run_root == "route_a/"
    assert facts.multiqc_version == "1.30"
    assert facts.docs_page is not None
    assert len(facts.screenshots) == 1


def test_data_collections_name_the_paths_a_run_must_publish(
    nfo: ModuleType, template_dir: Path
) -> None:
    facts = nfo.collect_facts("demoseq", "1.2.0", projects_dir=template_dir)
    by_tag = {row["tag"]: row for row in facts.data_collections}

    assert by_tag["counts"]["how"] == "scanned file"
    assert by_tag["counts"]["reads"] == "`{DATA_ROOT}/c.tsv`"
    assert by_tag["peaks"]["how"] == "scanned pattern"
    assert by_tag["peaks"]["optional"] is True
    assert by_tag["derived"]["how"] == "computed"
    assert by_tag["derived"]["reads"] == "`demo/thing.py`"


def test_route_vars_keeps_pipeline_flags_and_drops_path_overrides(nfo: ModuleType) -> None:
    optional = [
        ("SAMPLESHEET_FILE", "Path to it, when omitted"),
        ("SKIP_QC", "For a --skip_qc run (--var SKIP_QC)"),
    ]
    # `--var` alone is the depictio CLI flag every description mentions, so it
    # must not be what makes a variable look like a pipeline route.
    assert nfo._route_vars(optional) == [("SKIP_QC", "For a --skip_qc run (--var SKIP_QC)")]


def test_dashboard_url_falls_back_to_the_list_without_a_map(
    nfo: ModuleType, template_dir: Path
) -> None:
    facts = nfo.collect_facts("demoseq", "1.2.0", projects_dir=template_dir)

    url, deep = nfo.dashboard_url(facts, "https://demo.example.org/", {})
    assert (url, deep) == ("https://demo.example.org/dashboards", False)

    url, deep = nfo.dashboard_url(facts, "https://demo.example.org", {"demoseq": "https://d/1"})
    assert (url, deep) == ("https://d/1", True)


def test_discussion_body_leads_with_a_checklist(nfo: ModuleType, template_dir: Path) -> None:
    facts = nfo.collect_facts("demoseq", "1.2.0", projects_dir=template_dir)
    body = nfo.render_discussion(facts, "https://demo.example.org", "https://docs/{pipeline}/", {})

    # Five boxes, answerable without typing — a round that only accepts prose
    # gets no replies from volunteer maintainers.
    assert body.count("\n- [ ] ") == 5
    assert "nf-core/demoseq writes them" in body
    # And the checklist comes before the reference tables it is a summary of.
    assert body.index("### The two-minute version") < body.index("<details>")

    assert "**Is anything wrong or misleading?**" in body
    assert "**What do you always look at that is not here?**" in body
    assert "**Which real runs would this not fit?**" in body
    # Questions quote this template's own content back, which is what makes
    # them answerable rather than rhetorical.
    assert "`Samples`" in body
    assert "`SKIP_QC`" in body
    assert "`SAMPLESHEET_FILE`" not in body
    assert f"results-{_SHA}" in body


def test_outreach_writes_a_bundle_per_pipeline(
    nfo: ModuleType, template_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "bundles"
    rc = nfo.main(
        [
            "--projects-dir",
            str(template_dir),
            "--out-dir",
            str(out),
            "--no-pr-lookup",
        ]
    )

    assert rc == 0
    assert (out / "demoseq.md").is_file()
    assert (out / "demoseq.slack.md").is_file()
    assert "#demoseq" in (out / "demoseq.slack.md").read_text()
    epic = (out / "EPIC.md").read_text()
    assert "nf-core/demoseq" in epic
    # No dashboard URL was supplied, so the round still owes this pipeline a link.
    assert "⚠ needs link" in epic
    assert json.loads((out / "facts.json").read_text())[0]["pipeline"] == "demoseq"


def test_discussion_title_is_stable_across_runs(nfo: ModuleType, template_dir: Path) -> None:
    facts = nfo.collect_facts("demoseq", "1.2.0", projects_dir=template_dir)
    # `--create-discussions` skips a title it already finds posted, so the title
    # drifting would silently double-post the whole round.
    assert nfo.discussion_title(facts) == (
        "[demoseq] Depictio dashboard for nf-core/demoseq 1.2.0: does it look right to you?"
    )


def test_create_discussions_skips_titles_already_posted(
    nfo: ModuleType, template_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The round is 12 pipelines across 12 Slack channels — a double post is loud."""
    facts = nfo.collect_facts("demoseq", "1.2.0", projects_dir=template_dir)
    posted: list[dict] = []

    def fake_graphql(query: str, **variables: str) -> dict:
        if "createDiscussion" in query:
            posted.append(dict(variables))
            return {"createDiscussion": {"discussion": {"url": "https://new/thread"}}}
        return {
            "repository": {
                "id": "R_1",
                "discussionCategories": {"nodes": [{"id": "C_1", "name": "Pipeline templates"}]},
                "discussions": {
                    "nodes": [{"title": nfo.discussion_title(facts), "url": "https://old/thread"}]
                },
            }
        }

    monkeypatch.setattr(nfo.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(nfo, "_gh_graphql", fake_graphql)

    urls = nfo.create_discussions(
        [(facts, nfo.discussion_title(facts), "body")], "depictio/depictio", "Pipeline templates"
    )

    assert posted == []
    assert urls == {"demoseq": "https://old/thread"}


def test_create_discussions_rejects_an_unknown_category(
    nfo: ModuleType, template_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = nfo.collect_facts("demoseq", "1.2.0", projects_dir=template_dir)

    monkeypatch.setattr(nfo.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(
        nfo,
        "_gh_graphql",
        lambda query, **_v: {
            "repository": {
                "id": "R_1",
                "discussionCategories": {"nodes": [{"id": "C_1", "name": "General"}]},
                "discussions": {"nodes": []},
            }
        },
    )

    with pytest.raises(SystemExit, match="Pipeline templates"):
        nfo.create_discussions([(facts, "t", "b")], "depictio/depictio", "Pipeline templates")


def test_screenshots_are_paired_with_the_tab_they_show(nfo: ModuleType, template_dir: Path) -> None:
    """Filenames are tab slugs, so the caption can name the tab a reviewer would fault."""
    (template_dir / "demoseq" / "1.2.0" / "docs" / "screenshots" / "peaks.png").write_bytes(b"")
    (template_dir / "demoseq" / "1.2.0" / "docs" / "screenshots" / "stray.png").write_bytes(b"")
    facts = nfo.collect_facts("demoseq", "1.2.0", projects_dir=template_dir)

    paired = nfo.screenshots_for_tabs(facts, "https://img.example/")

    # Tab order first (QC, Peaks), then anything with no matching tab.
    assert [title for title, _url in paired] == ["QC", "Peaks", "Stray"]
    assert paired[0][1].startswith("https://img.example/")
    assert paired[0][1].endswith("/qc.png")


def test_discussion_embeds_the_hero_shot_and_folds_the_rest(
    nfo: ModuleType, template_dir: Path
) -> None:
    (template_dir / "demoseq" / "1.2.0" / "docs" / "screenshots" / "peaks.png").write_bytes(b"")
    facts = nfo.collect_facts("demoseq", "1.2.0", projects_dir=template_dir)

    body = nfo.render_discussion(
        facts, "https://demo.example.org", "https://docs/{pipeline}/", {}, "https://img.example"
    )
    assert "![QC](https://img.example/" in body
    assert "<details>" in body
    assert "![Peaks](https://img.example/" in body

    # An empty base is how a caller asks for a text-only bundle.
    assert "![QC](" not in nfo.render_discussion(
        facts, "https://demo.example.org", "https://docs/{pipeline}/", {}, ""
    )
