"""The template docs page generator and the page.yaml schema it reads."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from depictio.dev_scripts import gen_template_pages as gen
from depictio.models.models.template_docs import TemplateDocs

_NF_CORE = Path(__file__).resolve().parents[2] / "projects" / "nf-core"

_CARD_ONLY = {
    "generate_page": False,
    "page_title": "Toy",
    "status": "draft",
    "card_blurb": "A toy pipeline.",
    "index_summary": "Toy",
}


def _page(**overrides):
    tabs = [
        {"title": "MultiQC", "question": "Q0?", "description": "D0."},
        {"title": "Counts", "summary": "how many", "question": "Q1?", "description": "D1."},
    ]
    data = {
        **_CARD_ONLY,
        "generate_page": True,
        "subtitle": "Sub.",
        "intro": "Intro:",
        "quick_start": "Copy the sheet.",
        "run_vars": ["A=1", "B=2"],
        "reference": "Reads things.",
        "tabs_intro": "Two tabs.",
        "tabs": tabs,
        "running": "Run it.",
        "data_structure": "A tree.",
        "validation": "A megatest.",
        "callouts": [
            {"kind": "warning", "title": "Mind", "body": "Careful.", "position": "running"}
        ],
    }
    data.update(overrides)
    return data


_DASHBOARD = {
    "main_dashboard": {
        "main_tab_name": "MultiQC",
        "tab_icon": "/assets/images/logos/multiqc_icon_color.svg",
        "filter_sections": [
            {"name": "Sample scope", "persistent": True, "pin": "top"},
        ],
        "grid_sections": [
            {"name": "At a glance", "persistent": True, "pin": "top"},
            {"name": "Reads", "collapsed": True},
        ],
        "components": [
            {"component_type": "interactive", "section": "Sample scope", "title": "Sample"},
            {
                "component_type": "interactive",
                "section": "Sample scope",
                "title": "{GROUP_COL_DISPLAY}",
            },
            {"component_type": "card", "section": "At a glance", "title": "c1", "use": "x/y"},
            {"component_type": "card", "section": "At a glance", "title": "c2"},
            {"component_type": "text", "section": "Reads", "title": "ignored"},
            {"component_type": "multiqc", "section": "Reads", "selected_plot": "fastqc"},
        ],
    },
    "tabs": [
        {
            "title": "Counts",
            "tab_order": 1,
            "tab_icon": "mdi:target-arrow",
            "tab_icon_color": "teal",
            "filter_sections": [{"name": "Expression"}],
            "grid_sections": [{"name": "Matrix"}],
            "components": [
                {
                    "component_type": "interactive",
                    "section": "Expression",
                    "title": "Depth",
                    "interactive_component_type": "RangeSlider",
                },
                {"component_type": "table", "section": "Matrix", "title": "Counts table"},
            ],
        }
    ],
}


def _pipeline(tmp_path: Path, page: dict) -> gen.PipelineDocs:
    """A toy nf-core/toy 1.0.0 template (plus a 0.9.0) with the page and dashboard above."""
    tpl = tmp_path / "templates" / "toy"
    for version in ("0.9.0", "1.0.0"):
        vdir = tpl / version
        (vdir / "dashboards").mkdir(parents=True)
        template = {
            "template": {
                "template_id": f"nf-core/toy/{version}",
                "description": "toy",
                "version": "1.0.0",
                "dashboards": ["dashboards/base.yaml"],
            }
        }
        (vdir / "template.yaml").write_text(yaml.safe_dump(template))
        (vdir / "dashboards" / "base.yaml").write_text(yaml.safe_dump(_DASHBOARD))
    (tpl / "1.0.0" / "docs").mkdir()
    (tpl / "1.0.0" / "docs" / "page.yaml").write_text(yaml.safe_dump(page))
    loaded = gen.load_pipeline(tpl)
    assert loaded is not None
    return loaded


@pytest.fixture(autouse=True)
def _repo_root(tmp_path, monkeypatch):
    # render_page prints the page.yaml path relative to the repo root.
    monkeypatch.setattr(gen, "_REPO_ROOT", tmp_path)


class TestSchema:
    def test_card_only_page_needs_no_prose(self):
        assert TemplateDocs(**_CARD_ONLY).tabs == []

    def test_generated_page_requires_its_prose(self):
        with pytest.raises(ValidationError, match="validation"):
            TemplateDocs(**{**_page(), "validation": None})

    def test_unknown_key_is_rejected(self):
        with pytest.raises(ValidationError):
            TemplateDocs(**_page(sumary="typo"))

    def test_duplicate_tab_titles_are_rejected(self):
        tab = {"title": "A", "question": "?", "description": "."}
        with pytest.raises(ValidationError, match="duplicate"):
            TemplateDocs(**_page(tabs=[tab, tab]))


class TestLoading:
    def test_reads_latest_version_and_lists_all(self, tmp_path):
        p = _pipeline(tmp_path, _page())
        assert p.version == "1.0.0"
        assert p.versions == ["1.0.0", "0.9.0"]
        assert [t.title for t in p.tabs] == ["MultiQC", "Counts"]

    def test_tab_missing_from_page_fails(self, tmp_path):
        page = _page(tabs=[{"title": "MultiQC", "question": "?", "description": "."}])
        with pytest.raises(gen.DocsError, match="missing: \\['Counts'\\]"):
            _pipeline(tmp_path, page)

    def test_card_only_page_skips_tab_check(self, tmp_path):
        assert _pipeline(tmp_path, _CARD_ONLY).tabs


class TestRendering:
    def test_filters_line(self, tmp_path):
        main, counts = _pipeline(tmp_path, _page()).tabs
        assert gen.render_filters_line(main) == (
            "**Filters** · `Sample` and `<GROUP_COL>` in a *Sample scope* group, "
            "on every tab, pinned to the top."
        )
        assert gen.render_filters_line(counts) == (
            "**Filters** · `Depth` range in an *Expression* group."
        )

    def test_components_table(self, tmp_path):
        main, _ = _pipeline(tmp_path, _page()).tabs
        assert gen.render_components_table(main) == [
            "| Section | What it holds |",
            "|---|---|",
            "| At a glance | 2 cards (pinned) |",
            "| Reads | *fastqc* (collapsed) |",
        ]

    def test_long_section_is_summarised(self):
        tiles = [{"component_type": "multiqc", "title": f"p{i}"} for i in range(8)]
        assert gen._section_cell(tiles) == "*p0*, *p1*, *p2*, and 5 more"

    def test_page(self, tmp_path):
        p = _pipeline(tmp_path, _page())
        docs_dir = tmp_path / "docs"
        shots = docs_dir / "images" / "pipeline-templates" / "nf-core" / "toy"
        shots.mkdir(parents=True)
        (shots / "counts_light.png").write_bytes(b"")
        (shots / "counts_dark.png").write_bytes(b"")
        page = gen.render_page(p, docs_dir)

        assert "template-status-draft" in page
        assert '<option value="0.9.0">0.9.0</option>' in page
        assert "  --var A=1 \\\n      --var B=2\n" in page
        # icon alias for a name the docs theme lacks, colour class, dark twin
        assert '=== ":material-bullseye-arrow:{ .mc-teal } Counts"' in page
        assert "counts_dark.png#only-dark" in page
        # no screenshot for the MultiQC tab: none on disk
        assert "multiqc_light.png" not in page
        # only tabs with a summary are listed in the intro
        assert "- :material-bullseye-arrow: **Counts**: how many" in page
        assert "**MultiQC**:" not in page
        assert "1 of its 4 tiles carry a `use:`" in page
        # one reference include per version, the latest through its alias
        assert '_generated/toy-latest.md"' in page
        assert '_generated/toy-0.9.0.md"' in page
        assert page.index('!!! warning "Mind"') > page.index("Run it.")
        assert "which is what keeps it a Draft." in page
        assert "\n\n\n" not in page

    def test_use_count_tokens_replace_the_standard_sentence(self, tmp_path):
        p = _pipeline(tmp_path, _page(reference="{use_count} of {tile_count} tiles, see `x/*`."))
        page = gen.render_page(p, tmp_path / "docs")
        assert "1 of 4 tiles, see `x/*`." in page
        assert "carry a `use:`" not in page

    def test_title_and_placeholders_are_escaped(self, tmp_path):
        p = _pipeline(tmp_path, _page(page_title="CUT&RUN"))
        page = gen.render_page(p, tmp_path / "docs")
        assert 'title: "CUT&RUN"' in page
        assert "CUT&amp;RUN</h1>" in page
        assert gen._vars_as_code("Per-{GROUP_COL_DISPLAY} view") == "Per-`GROUP_COL` view"


class TestRegistries:
    def test_card_and_row_are_replaced_in_place(self, tmp_path):
        p = _pipeline(tmp_path, _CARD_ONLY)
        catalog = (
            '<div>\n  <a class="template-card" href="nf-core/toy/" old>\n  </a>\n\n'
            '  <a class="template-card" href="nf-core/zzz/">\n  </a>\n</div>'
        )
        updated = gen.update_catalog(catalog, [p])
        assert updated.count('href="nf-core/toy/"') == 1
        assert 'data-tpl-status="draft"' in updated
        assert updated.index("nf-core/toy/") < updated.index("nf-core/zzz/")

        index = "| T | P | V |\n|---|---|---|\n| [toy](toy.md) | old | 0.1 |\n"
        assert "| [toy](toy.md) | Toy | 0.9.0, 1.0.0 |" in gen.update_index(index, [p])

    def test_new_card_and_row_are_appended(self, tmp_path):
        p = _pipeline(tmp_path, _CARD_ONLY)
        catalog = '<div>\n  <a class="template-card" href="nf-core/aaa/">\n  </a>\n</div>'
        assert gen.update_catalog(catalog, [p]).rstrip().endswith("</a>\n</div>")
        index = "| T | P | V |\n|---|---|---|\n| [aaa](aaa.md) | A | 1 |\n\nMore text."
        lines = gen.update_index(index, [p]).split("\n")
        assert lines[3].startswith("| [toy](toy.md) |")


@pytest.mark.parametrize(
    "page_yaml",
    sorted(_NF_CORE.glob("*/*/docs/page.yaml")),
    ids=lambda p: p.parts[-4],
)
def test_every_page_yaml_matches_its_dashboard(page_yaml: Path):
    """Each committed page.yaml validates and names exactly its dashboard's tabs."""
    assert gen.load_pipeline(page_yaml.parents[2]) is not None
