"""The report's own chrome: layout rows, branding, notes, captions, footer, methods."""

from __future__ import annotations

import re

import yaml

from depictio.api.v1.services.notebook_export.generator import (
    DCPlan,
    ExportPlan,
    generate_qmd,
)
from depictio.api.v1.services.notebook_export.report_chrome import (
    about_callout,
    description_sections,
    stepper_markdown,
)
from depictio.models.models.analysis_state import AnalysisState

LOGO = "data:image/png;base64,iVBORw0KGgo="
MARK = "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="


def _front(src: str) -> dict:
    return yaml.safe_load(src.split("\n---\n", 1)[0].removeprefix("---\n"))


def _body(src: str) -> str:
    return src.split("\n---\n", 1)[1]


def _plan(tabs, **extra) -> ExportPlan:
    dc_ids = sorted(
        {str(m.get("dc_id")) for t in tabs for m in t["stored_metadata"] if m.get("dc_id")}
    )
    state = AnalysisState.model_validate(
        {"context": {"dashboard_id": str(tabs[0]["dashboard_id"])}}
    )
    return ExportPlan(
        tabs=tabs,
        project=extra.pop("project", None),
        state=state,
        dcs=[
            DCPlan(dc_id=d, tag=f"dc_{i}", initial_rows=10 * (i + 1)) for i, d in enumerate(dc_ids)
        ],
        stages=[],
        title="nf-core/ampliseq",
        **extra,
    )


# ── Overview layout ─────────────────────────────────────────────────────────


def test_the_overview_keeps_its_grid_rows(ampliseq_tabs):
    """About + The run share a row 5:3 as on the dashboard; the steps are a stepper."""
    src = _body(generate_qmd(_plan(ampliseq_tabs)))
    assert '::: {.dpx-grid style="--dpx-cols: minmax(0,5fr) minmax(0,3fr)"}' in src
    grid = src.index("minmax(0,5fr) minmax(0,3fr)")
    assert src.index("About this dashboard") > grid
    assert src.index("'ov-run'") > grid
    # Both are card surfaces, as `surface: card` draws them.
    assert src.count("{.dpx-cell .dpx-surface-card") >= 3
    # The steps list as the stepper's parts: a mark, a label, its links.
    assert "::: {.steps .dpx-steps}" in src
    assert 'class="dpx-step-label">Trim</span>' in src
    assert 'class="dpx-step-text">Primers cut by Cutadapt</span>' in src
    # The four key-figure cards stay one strip, four across.
    assert "card_row([viz_samples, viz_phyla, viz_shannon_diversity, viz_reads_kept])" in src
    assert "cols = n if n <= 4" in src


def test_the_hero_tile_shows_its_logo_in_place_of_its_title(ampliseq_tabs):
    plan = _plan(ampliseq_tabs, logos={"ov-hero": {"light": LOGO, "dark": LOGO + "AA"}})
    src = _body(generate_qmd(plan))
    assert f'<img class="dpx-hero-logo dpx-light-only" src="{LOGO}"' in src
    assert f'src="{LOGO}AA"' in src
    assert "##### nf-core/ampliseq" not in src
    # Without an inlined logo the title stays text (a remote URL is never linked).
    src = _body(generate_qmd(_plan(ampliseq_tabs)))
    assert "##### nf-core/ampliseq" in src
    assert "raw.githubusercontent.com" not in src


def test_a_section_filter_bar_shows_its_controls(ampliseq_tabs):
    src = _body(generate_qmd(_plan(ampliseq_tabs)))
    bar = re.search(r'<div class="dpx-filterbar">(.*?)</div>', src)
    assert bar and "<b>Habitat</b> <i>All</i>" in bar.group(1)


def test_links_to_sections_and_parameters_land_in_the_document(ampliseq_tabs):
    project = {"template_origin": {"run_provenance": [{"key": "a", "value": 1}]}}
    src = _body(generate_qmd(_plan(ampliseq_tabs, project=project)))
    assert "](params:" not in src and "](section:" not in src
    assert '<details id="export-parameters">' in src
    assert "[Settings](#export-parameters)" in src
    # Without a parameters block the step keeps no dangling "Settings".
    src = _body(generate_qmd(_plan(ampliseq_tabs)))
    assert "[Settings]" not in src and "](params:" not in src


# ── Branding, header, footer ────────────────────────────────────────────────


def test_branding_header_and_footer(ampliseq_tabs):
    plan = _plan(
        ampliseq_tabs,
        dashboard_logo=LOGO,
        depictio_mark=MARK,
        dashboard_public=True,
        depictio_version="1.2.3",
        brand={"app_name": "Depictio", "primary": "teal", "logo_data_uri": MARK},
    )
    src = generate_qmd(plan)
    html = _front(src)["format"]["html"]
    bar = html["include-before-body"]["text"]
    assert 'class="dpx-appbar"' in bar and f'src="{LOGO}"' in bar
    assert "Powered by" in bar and 'class="dpx-mark"' in bar
    # The dashboard's mark is the tab icon too.
    assert LOGO in html["include-in-header"]["text"]
    # No big instance logo block in the header any more: the wordmark is only
    # ever the small "Powered by" mark, drawn once from the stylesheet.
    body = _body(src)
    assert "height:44px" not in body
    assert body.count(MARK) == 1
    foot = html["include-after-body"]["text"]
    assert 'class="dpx-footer"' in foot and "Powered by" in foot
    assert "1.2.3" in foot
    assert f"/dashboard/{plan.dashboard_id}" in foot


def test_a_private_dashboard_is_not_linked_from_the_footer(ampliseq_tabs):
    plan = _plan(ampliseq_tabs, dashboard_public=False)
    foot = _front(generate_qmd(plan))["format"]["html"]["include-after-body"]["text"]
    assert f"/dashboard/{plan.dashboard_id}" not in foot
    assert "Live dashboard" not in foot


def test_the_footer_carries_the_projects_licence_only_when_it_has_one(ampliseq_tabs):
    src = generate_qmd(_plan(ampliseq_tabs, project={"name": "P"}))
    assert "Licence" not in _front(src)["format"]["html"]["include-after-body"]["text"]
    src = generate_qmd(_plan(ampliseq_tabs, project={"name": "P", "license": "CC-BY-4.0"}))
    assert "CC-BY-4.0" in _front(src)["format"]["html"]["include-after-body"]["text"]


# ── About this component, captions ──────────────────────────────────────────


def test_about_notes_only_where_the_component_has_text(ampliseq_tabs):
    src = _body(generate_qmd(_plan(ampliseq_tabs)))
    described = [
        m
        for t in ampliseq_tabs
        for m in t["stored_metadata"]
        if m.get("component_type") not in ("text", "interactive", "card", "highlight")
        and str(m.get("description") or "").strip()
    ]
    notes = src.count('.callout-note .dpx-about collapse="true"')
    assert described, "the seeds describe some tiles"
    assert notes >= 1
    # Every note holds real dashboard text: its first words come from a description.
    descriptions = " ".join(
        str(m.get("description") or "") for t in ampliseq_tabs for m in t["stored_metadata"]
    )
    for body in re.findall(r'title="About th[^"]+"\}\n(.*?)\n:{4,}', src, re.S):
        words = re.sub(r"\*\*[^*]+\*\*\s*", "", body).strip().split()[:3]
        assert " ".join(words)[:12] in descriptions or "\n" in body


def test_about_callout_is_empty_without_text():
    assert about_callout("") == ""
    assert about_callout("   ") == ""


def test_description_labels_match_the_popover():
    secs = description_sections(
        "Median per sample.\nHow to read: the box is the IQR.\nSource: doi:10.1093/x; https://a.org"
    )
    assert [s.kind for s in secs] == ["lead", "labelled", "source"]
    assert secs[1].text == "The box is the IQR."
    note = about_callout(
        "Median per sample.\nHow to read: the box is the IQR.\nSource: doi:10.1093/x"
    )
    assert "**How to read.** The box is the IQR." in note
    assert "[doi:10.1093/x](https://doi.org/10.1093/x)" in note
    # "note: x" (lower case) is prose, not a label.
    assert [s.kind for s in description_sections("note: lower case")] == ["lead"]


def test_figures_and_tables_are_numbered_with_stable_labels(ampliseq_tabs):
    src = _body(generate_qmd(_plan(ampliseq_tabs)))
    figs = re.findall(r"^::: \{#(fig-[a-z0-9-]+)\}$", src, re.M)
    tbls = re.findall(r"^::: \{#(tbl-[a-z0-9-]+)\}$", src, re.M)
    assert figs and tbls
    assert len(set(figs + tbls)) == len(figs + tbls)
    # From the component index: the same on every export.
    again = _body(generate_qmd(_plan(ampliseq_tabs)))
    assert re.findall(r"^::: \{#(fig-[a-z0-9-]+)\}$", again, re.M) == figs
    assert "#fig-ov-tree" in "#" + " #".join(figs) or any(f.startswith("fig-ov-") for f in figs)
    # Each caption says where the data came from.
    assert '<span class="dpx-asof">Data: ' in src


def test_stepper_markup():
    md = (
        "::: steps\n"
        "1. ![](icon:mdi:dna) **Denoise** DADA2 · [Settings](params:x) · [Tree](tab:Phylogeny)\n"
        ":::"
    )
    out = stepper_markdown(md, lambda i: f"<i>{i}</i>")
    assert out.splitlines()[0] == "::: {.steps .dpx-steps}"
    assert '<span class="dpx-step-mark"><i>mdi:dna</i></span>' in out
    assert '<span class="dpx-step-links">[Settings](params:x) [Tree](tab:Phylogeny)</span>' in out
    assert '<span class="dpx-step-text">DADA2</span>' in out
    # A link the document cannot hold is dropped, not left dangling.
    out = stepper_markdown(md, lambda i: "", rewrite_link=lambda s: s.split("](")[0][1:])
    assert "dpx-step-links" not in out


# ── Methods and citations ───────────────────────────────────────────────────


def test_methods_cite_only_what_the_export_knows(ampliseq_tabs):
    bare = generate_qmd(_plan(ampliseq_tabs, project=None))
    # MultiQC tiles and the collections are known: still a methods part.
    assert "{#methods}" in bare
    refs = {r["id"] for r in _front(bare)["references"]}
    assert refs == {"multiqc", "depictio"}
    project = {
        "name": "Ampliseq",
        "workflows": [
            {
                "name": "ampliseq",
                "version": "3.1.0",
                "engine": {"name": "nextflow"},
                "catalog": {"name": "nf-core", "url": "https://nf-co.re"},
                "repository_url": "https://github.com/nf-core/ampliseq",
            }
        ],
        "template_origin": {"template_id": "nf-core/ampliseq/3.1.0"},
    }
    src = generate_qmd(_plan(ampliseq_tabs, project=project))
    refs = {r["id"]: r for r in _front(src)["references"]}
    assert refs["wf-nf-core-ampliseq"]["version"] == "3.1.0"
    assert refs["wf-nf-core-ampliseq"]["URL"] == "https://github.com/nf-core/ampliseq"
    body = _body(src)
    assert "[@wf-nf-core-ampliseq]" in body and "`nf-core/ampliseq/3.1.0`" in body
    assert "::: {#refs}" in body


def test_no_methods_without_anything_to_cite(penguins_tabs):
    tabs = [{**t, "stored_metadata": []} for t in penguins_tabs]
    src = generate_qmd(_plan(tabs, project=None))
    assert "{#methods}" not in src and "references" not in _front(src)


def test_the_report_follows_the_readers_colour_scheme(ampliseq_tabs):
    front = _front(generate_qmd(_plan(ampliseq_tabs)))
    assert front["format"]["html"]["respect-user-color-scheme"] is True
    assert front["brand"]["dark"]["color"]["background"] == "#1f1f1f"
    assert front["brand"]["light"]["color"]["background"] == "#ffffff"
    assert "body.quarto-dark" in _body(generate_qmd(_plan(ampliseq_tabs)))
    classic = _front(generate_qmd(_plan(ampliseq_tabs, theme="classic")))
    assert "brand" not in classic and "respect-user-color-scheme" not in classic["format"]["html"]


def test_pdf_adds_a_typst_format(ampliseq_tabs):
    front = _front(generate_qmd(_plan(ampliseq_tabs, pdf=True)))
    assert front["format"]["typst"]["citeproc"] is True
    assert front["format"]["html"]["format-links"] is False
    assert "typst" not in _front(generate_qmd(_plan(ampliseq_tabs)))["format"]
