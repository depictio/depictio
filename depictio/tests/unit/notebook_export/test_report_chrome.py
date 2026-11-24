"""The report's own chrome: layout rows, branding, notes, captions, footer, methods."""

from __future__ import annotations

import copy
import re
import shutil
import subprocess

import pytest
import yaml

from depictio.api.v1.services.notebook_export.generator import (
    DCPlan,
    ExportPlan,
    generate_qmd,
)
from depictio.api.v1.services.notebook_export.report_chrome import (
    TabLinkInfo,
    about_callout,
    description_sections,
    findings_markdown,
    parse_stat_row,
    pdf_structures,
    stepper_markdown,
    tab_tiles_markdown,
)
from depictio.models.models.analysis_state import AnalysisState
from depictio.models.models.report_layer import ReportLayer
from depictio.notebook.typst import LANDSCAPE_TABLE_ROWS

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


#: The report laid out in the dashboard's rows (its settings' other width).
_ROWS = {"settings": {"tile_width": "row"}}


def test_a_full_width_tile_leaves_its_row(ampliseq_tabs):
    """The layer's ``full_width`` takes a tile out of the dashboard row it
    shares: the 5:3 row splits into two tiles of their own, each the page's
    width, in the same order."""
    main, run = next(
        (t, m) for t in ampliseq_tabs for m in t["stored_metadata"] if m.get("index") == "ov-run"
    )
    layer = ReportLayer.model_validate(
        {
            **_ROWS,
            "tiles": [
                {
                    "tab_id": str(main["dashboard_id"]),
                    "component_id": str(run["index"]),
                    "full_width": True,
                }
            ],
        }
    )
    before = _body(
        generate_qmd(_plan(ampliseq_tabs, report_layer=ReportLayer.model_validate(_ROWS)))
    )
    src = _body(generate_qmd(_plan(ampliseq_tabs, report_layer=layer)))
    # That row is gone (other tabs keep their own 5:3 rows), its tiles stay.
    assert src.count('layout="[5,3]"') == before.count('layout="[5,3]"') - 1
    study, own = src.index("The study"), src.index("'ov-run'")
    assert study < own
    assert 'layout="[5,3]"' not in src[study:own]


def test_the_overview_keeps_its_grid_rows(ampliseq_tabs):
    """The study + The run share a row 5:3 as on the dashboard (the report in
    the dashboard's rows); the steps are a stepper."""
    src = _body(generate_qmd(_plan(ampliseq_tabs, report_layer=ReportLayer.model_validate(_ROWS))))
    # Quarto's own layout: a flex row on the page, a typst grid in the PDF.
    assert '::: {.dpx-grid layout="[5,3]"}' in src
    grid = src.index('layout="[5,3]"')
    assert src.index("The study") > grid
    assert src.index("'ov-run'") > grid
    # Both are card surfaces, as `surface: card` draws them.
    assert src.count("{.dpx-cell .dpx-surface-card") >= 3
    # The steps list as the stepper's parts: a mark, a label, its links.
    assert "::: {.steps .dpx-steps" in src
    assert 'class="dpx-step-label">Trim</span>' in src
    assert 'class="dpx-step-text">Primers cut by Cutadapt</span>' in src
    # The four key-figure cards stay one strip, two to a line.
    assert "card_row([viz_samples, viz_phyla, viz_shannon_diversity, viz_reads_kept])" in src
    assert "cols = min(len(cards), 2)" in src


def test_a_remote_logo_is_never_linked(ampliseq_tabs):
    # Without an inlined logo the title stays text: a remote URL is never linked.
    src = _body(generate_qmd(_plan(ampliseq_tabs)))
    assert "##### nf-core/ampliseq" in src
    assert "raw.githubusercontent.com" not in src


def test_a_section_filter_bar_shows_its_controls(ampliseq_tabs):
    src = _body(generate_qmd(_plan(ampliseq_tabs)))
    bar = re.search(r'<div class="dpx-filterbar">(.*?)</div>', src)
    assert bar and "<b>Habitat</b> <i>All</i>" in bar.group(1)


def test_links_to_sections_and_parameters_land_in_the_document(ampliseq_tabs):
    project = {"template_origin": {"run_provenance": [{"key": "a", "value": 1}]}}
    src = _body(
        generate_qmd(_plan(ampliseq_tabs, project=project, icons={"mdi:tune-variant": "<svg/>"}))
    )
    assert "](params:" not in src and "](section:" not in src
    assert '<details id="export-parameters">' in src
    # An icon alone (the live stepper's), its name as the tooltip.
    assert 'class="dpx-step-link" href="#export-parameters" title="Settings"' in src
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
    # A MultiQC tile is captioned by its plot's name, never its raw key.
    assert "**General statistics**." in src
    assert "**general_stats**" not in src


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


def test_a_steps_accent_and_icon_links():
    md = (
        "::: steps\n"
        "1. ![](icon:mdi:dna) **Denoise** DADA2 · [Settings](params:x) · [Tree](tab:Phylogeny)"
        " · [Docs](https://example.org)\n"
        ":::"
    )

    def step_link(label, target):
        if target.startswith("tab:"):
            return f'<a class="dpx-step-link" title="{label}"><i>tab</i></a>'
        return "" if target.startswith("params:") else None

    out = stepper_markdown(
        md,
        lambda i: "",
        rewrite_link=lambda s: s,
        accent="#40c057",
        step_link=step_link,
    )
    assert out.splitlines()[0] == '::: {.steps .dpx-steps style="--dpx-accent: #40c057"}'
    # The tab as an icon link, the missing params dropped, the external link kept as text.
    assert '<a class="dpx-step-link" title="Tree"><i>tab</i></a> [Docs](https://example.org)' in out
    assert "Settings" not in out


def _tab(name):
    return {
        "community": TabLinkInfo("Community", "tab-community", "mdi:bacteria", "#12b886", "Who?"),
        "alpha": TabLinkInfo("Alpha", "tab-alpha", "mdi:chart", "#be4bdb", None),
    }.get(name.strip().lower())


_FINDINGS = (
    "- **{{share}}** of the community is {{top}} – the most abundant phylum"
    " [Community](tab:Community)\n"
    "- **5%** FDR – ANCOM-BC [Gone](tab:Nowhere)\n"
)


def test_a_findings_list_is_read_as_the_live_one():
    row = parse_stat_row("**{{share}}** is high – context [Community](tab:Community)")
    assert row and (row.stat, row.claim, row.context) == ("{{share}}", "is high", "context")
    assert row.link == "[Community](tab:Community)"
    # A figure with no digit, a fact without context or link: not a result.
    assert parse_stat_row("**Samples** are many – context") is None
    assert parse_stat_row("**16S** amplicons") is None
    out = findings_markdown(_FINDINGS, tab_link=_tab)
    assert out.count("{.dpx-finding}") == 2 and "::: {.dpx-findings}" in out
    # The figure wears its tab's colour; the way in is the document's anchor.
    assert '[{{share}}]{.dpx-finding-stat style="color: #12b886"}' in out
    assert (
        '[[Community](#tab-community)]{.dpx-finding-link style="--dpx-link-color: #12b886"}' in out
    )
    # A tab the document lacks: the row stays, without a link or a colour.
    assert "[5%]{.dpx-finding-stat}" in out and "Gone" not in out
    # Any other list is left as written, and one item that is no result keeps it so.
    plain = "- a\n- b\n"
    assert findings_markdown(plain, tab_link=_tab) == plain
    mixed = _FINDINGS + "- just text\n"
    assert findings_markdown(mixed, tab_link=_tab) == mixed


def _icon(icon, color):
    return f'<svg data-color="{color}"/>' if icon else ""


def test_a_list_of_tab_links_is_drawn_as_tiles():
    md = "### Taxa\n- [Community & Diversity](tab:Community)\n- [Alpha](tab:Alpha): own line\n"
    out = tab_tiles_markdown(md, tab_link=_tab, icon_html=_icon)
    assert "::: {.dpx-tab-tiles}" in out and out.count("{.dpx-tab-tile ") == 2
    assert 'style="--dpx-tile-color: #12b886"' in out
    assert '<svg data-color="#12b886"/>' in out
    assert "[Community & Diversity](#tab-community){.dpx-tab-tile-name}" in out
    # The tab's own subtitle, unless the author wrote a line.
    assert "[Who?]{.dpx-tab-tile-line}" in out and "[own line]{.dpx-tab-tile-line}" in out
    # A numbered list numbers its tiles.
    numbered = tab_tiles_markdown(
        "1. [Alpha](tab:Alpha)\n2. [Community](tab:Community)\n", tab_link=_tab, icon_html=_icon
    )
    assert "[01]{.dpx-tab-tile-num}" in numbered and "[02]{.dpx-tab-tile-num}" in numbered
    # Prose that merely mentions a tab stays a list.
    prose = "- see [Alpha](tab:Alpha) for more\n- [Community](tab:Community)\n"
    assert tab_tiles_markdown(prose, tab_link=_tab, icon_html=_icon) == prose
    # Every tab missing: the list goes, and the heading announcing it.
    gone = "text\n\n### Data\n- [X](tab:Nowhere)\n\nafter\n"
    out = tab_tiles_markdown(gone, tab_link=_tab, icon_html=_icon)
    assert "Data" not in out and "Nowhere" not in out and "after" in out


def test_the_pdf_draws_findings_tiles_and_step_icons():
    svg = '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M0 0h24v24z"/></svg>'
    md = (
        _FINDINGS
        + "\nBetween.\n\n- [Community](tab:Community)\n- [Alpha](tab:Alpha)\n\n"
        + "::: steps\n1. ![](icon:mdi:dna) **Trim** Cut · [Settings](params:p) · [T](tab:Community)\n:::\n"
    )
    out = pdf_structures(md, lambda i: svg, accent="#40c057", tab_link=_tab)
    assert '#dpx-findings((("{{share}}", "of the community is {{top}}"' in out
    assert 'rgb("#12b886")' in out and "#dpx-tab-tiles(" in out
    steps = re.search(r"#dpx-steps\(\(\((.*)\), rgb", out)
    assert steps and steps.group(1).count('fill=\\"#12b886\\"') >= 1
    # The page keeps the list as written, in an HTML-only block.
    assert out.count('when-format="html"') >= 3
    # A params icon only when the document holds the parameters.
    bare = pdf_structures(md, lambda i: svg, accent="#40c057", tab_link=_tab, has_params=False)
    assert bare.count("<svg") < out.count("<svg")


@pytest.mark.skipif(shutil.which("quarto") is None, reason="quarto (typst) is not installed")
def test_the_typst_definitions_compile(tmp_path):
    from depictio.api.v1.services.notebook_export.pdf_typst import typst_preamble

    svg = '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M0 0h24v24z"/></svg>'
    md = (
        _FINDINGS.replace("{{share}}", "41%").replace("{{top}}", "X")
        + "\nBetween.\n\n1. [Community](tab:Community)\n2. [Alpha](tab:Alpha)\n\n"
        + "::: steps\n1. ![](icon:mdi:dna) **Trim** Cut · [Settings](params:p) · [T](tab:Community)\n"
        + "2. **Next** No links\n:::\n"
    )
    out = pdf_structures(md, lambda i: svg, accent="#40c057", tab_link=_tab)
    calls = "\n".join(re.findall(r"````\{=typst\}\n(.*?)\n````", out, re.S))
    assert calls.count("#dpx-") == 3
    doc = tmp_path / "doc.typ"
    doc.write_text(typst_preamble(title="T", subtitle=None, primary="#228be6") + "\n" + calls)
    done = subprocess.run(
        ["quarto", "typst", "compile", str(doc), str(tmp_path / "doc.pdf")],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "doc.pdf").stat().st_size > 0


def test_the_overview_draws_its_steps_findings_and_tiles(ampliseq_tabs):
    src = _body(generate_qmd(_plan(ampliseq_tabs, icons={"mdi:tune-variant": "<svg/>"})))
    # The stepper takes the tile's own accent (green on the dashboard).
    assert '::: {.steps .dpx-steps style="--dpx-accent: #40c057"}' in src
    # The findings list, each figure in its tab's colour.
    assert "::: {.dpx-findings}" in src and "{.dpx-finding-stat style=" in src
    # The how-to-read lists: one tile per tab the document holds.
    assert "::: {.dpx-tab-tiles}" in src and "{.dpx-tab-tile-name}" in src
    assert "](tab:" not in src


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


# ── One place per name ──────────────────────────────────────────────────────


def _hero_plan(ampliseq_tabs, **extra):
    return _plan(ampliseq_tabs, logos={"ov-hero": {"light": LOGO, "dark": LOGO + "AA"}}, **extra)


def test_the_first_tabs_logo_is_the_title_and_not_repeated_in_its_tile(ampliseq_tabs):
    src = generate_qmd(_hero_plan(ampliseq_tabs))
    body = _body(src)
    # The H1 shows the logo (its text kept for the contents and screen readers)...
    assert "text-indent: -10000px" in body and f"url('{LOGO}')" in body
    assert f"body.quarto-dark h1.title {{ background-image: url('{LOGO}AA'); }}" in body
    assert "print-color-adjust: exact" in body
    assert _front(src)["title"] == "nf-core/ampliseq"
    # ...and the tile draws neither the logo nor its title again; its prose stays.
    assert 'class="dpx-hero-logo' not in body
    assert "##### nf-core/ampliseq" not in body
    assert "Amplicon reads turned into a census" in body


def test_without_a_header_logo_the_title_is_text_once(ampliseq_tabs):
    body = _body(generate_qmd(_plan(ampliseq_tabs)))
    assert "text-indent: -10000px" not in body
    assert "##### nf-core/ampliseq" in body  # the tile keeps its own title


def test_a_logo_on_a_later_tile_is_not_the_title(ampliseq_tabs):
    tabs = [dict(t) for t in ampliseq_tabs]
    main = next(t for t in tabs if t.get("is_main_tab"))
    plan = _plan(tabs, logos={"ov-about": {"light": LOGO}})
    body = _body(generate_qmd(plan))
    # ov-hero (no logo here) leads the tab, so nothing is promoted to the title.
    assert "text-indent: -10000px" not in body and 'class="dpx-hero-logo"' in body
    assert main["dashboard_id"]


def test_the_header_bar_does_not_repeat_the_title(ampliseq_tabs):
    for plan in (_hero_plan(ampliseq_tabs, dashboard_logo=LOGO), _plan(ampliseq_tabs)):
        bar = _front(generate_qmd(plan))["format"]["html"]["include-before-body"]["text"]
        assert "dpx-appbar-title" not in bar and "nf-core/ampliseq" not in bar
        # No tab breadcrumb: the first part's heading follows right under it.
        assert "Overview" not in bar and "›" not in bar
        assert "Powered by" in bar
    bar = _front(generate_qmd(_hero_plan(ampliseq_tabs, dashboard_logo=LOGO)))["format"]["html"][
        "include-before-body"
    ]["text"]
    assert f'src="{LOGO}"' in bar  # the dashboard's mark stays


def test_a_tab_description_equal_to_the_subtitle_is_not_repeated(ampliseq_tabs):
    main = next(t for t in ampliseq_tabs if t.get("is_main_tab"))
    subtitle = main["subtitle"]
    body = _body(generate_qmd(_plan(ampliseq_tabs, subtitle=subtitle)))
    assert f"*{subtitle}*" not in body
    # A different subtitle leaves the tab's own description in place.
    body = _body(generate_qmd(_plan(ampliseq_tabs, subtitle="Something else")))
    assert f"*{subtitle}*" in body


# ── The PDF's page ──────────────────────────────────────────────────────────


def _typst_block(src: str) -> str:
    m = re.search(r"````\{=typst\}\n(.*?)\n````", src, re.S)
    assert m, "the PDF's page opens the body as a raw typst block"
    return m.group(1)


def _png_uri(w: int = 4, h: int = 2) -> str:
    import base64
    import struct

    head = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h)
    return "data:image/png;base64," + base64.b64encode(head + b"\x08\x02\x00\x00\x00").decode()


def test_the_pdf_carries_its_page(ampliseq_tabs):
    plan = _plan(
        ampliseq_tabs,
        pdf=True,
        depictio_mark=MARK,
        logos={"ov-hero": {"light": _png_uri()}},
    )
    src = generate_qmd(plan)
    typst = _front(src)["format"]["typst"]
    # Quarto's centred title block and contents are left out: the page's own.
    assert typst["title"] == "" and typst["toc"] is False
    assert typst["shift-heading-level-by"] == -1
    block = _typst_block(_body(src))
    # Inter first, a fallback chain after it, a matching mono for code.
    assert '#let dpx-sans = ("Inter", "Inter Variable", "Roboto"' in block
    assert '"DejaVu Sans")' in block and '#let dpx-mono = ("JetBrains Mono"' in block
    # Page 1 the title page, page 2 the contents alone, then the body.
    title_page = block.index("#page(header: none, footer: none, numbering: none)[")
    contents = block.index("#outline(title: text(size: 17pt)[Contents]")
    body_pages = block.index('#set page(numbering: "1", header: context')
    assert title_page < contents < body_pages
    assert block.count("#page(header: none, footer: none, numbering: none)[") == 2
    # The running header (mark + title, the tab in view) and footer.
    assert "query(heading.where(level: 2))" in block and "dpx-title" in block
    assert "Powered by" in block and "counter(page).display()" in block
    # The title page shows the dashboard's logo (as SVG text typst can read).
    assert "#dpx-logo(84pt)" in block and "<svg" in block
    # Tab colours by heading label.
    assert '"tab-multiqc": rgb(' in block


def test_the_mono_pdf_emits_no_tab_colours(ampliseq_tabs):
    block = _typst_block(_body(generate_qmd(_plan(ampliseq_tabs, pdf=True, pdf_style="mono"))))
    assert "#let dpx-colors = (:)" in block
    assert '#let dpx-accent = rgb("#212529")' in block
    colour = _typst_block(_body(generate_qmd(_plan(ampliseq_tabs, pdf=True))))
    assert "#let dpx-colors = (:)" not in colour


def test_no_typst_page_without_the_pdf(ampliseq_tabs):
    assert "{=typst}" not in generate_qmd(_plan(ampliseq_tabs))


def test_the_pdf_style_is_validated():
    import pytest
    from pydantic import ValidationError

    from depictio.models.models.analysis_state import NotebookExportRequest

    state = {"context": {"dashboard_id": "646b0f3c1e4a2d7f8e5b8ca2"}}
    assert NotebookExportRequest.model_validate({"state": state}).pdf_style == "colour"
    assert (
        NotebookExportRequest.model_validate({"state": state, "pdf_style": "mono"}).pdf_style
        == "mono"
    )
    with pytest.raises(ValidationError):
        NotebookExportRequest.model_validate({"state": state, "pdf_style": "sepia"})


# ── No orphan text ──────────────────────────────────────────────────────────


def test_a_link_with_no_target_goes_with_its_label():
    from depictio.api.v1.services.notebook_export.report_chrome import ORPHAN, drop_orphan_links

    assert drop_orphan_links(f"between groups. {ORPHAN}\n") == "between groups.\n"
    assert drop_orphan_links(f"Trim · {ORPHAN} · [Tab](#t)") == "Trim · [Tab](#t)"
    assert (
        drop_orphan_links(f"- **Samplesheet** [12 rows](#s), its path in {ORPHAN}")
        == "- **Samplesheet** [12 rows](#s)"
    )
    assert drop_orphan_links(f"- {ORPHAN}\n- [B](#b)") == "- [B](#b)"
    assert drop_orphan_links(f"- ![](icon:mdi:x) **Tools** {ORPHAN}\nnext") == "next"
    assert drop_orphan_links("untouched [a](#a)") == "untouched [a](#a)"


def test_run_parameters_never_linger_as_stray_text(ampliseq_tabs):
    # No parameters block in this export: the hero's "[Run parameters](params:)"
    # goes, label and all, and no link is left pointing at nothing.
    body = _body(generate_qmd(_plan(ampliseq_tabs)))
    assert "Run parameters" not in body
    assert "](params:" not in body and "\x00" not in body
    assert "what differs between groups." in body
    # With one, it is a link to it.
    project = {"template_origin": {"run_provenance": [{"key": "a", "value": 1}]}}
    body = _body(generate_qmd(_plan(ampliseq_tabs, project=project)))
    assert "[Run parameters](#export-parameters)" in body


def test_a_tab_name_with_parentheses_is_a_link_not_stray_text(ampliseq_tabs):
    body = _body(generate_qmd(_plan(ampliseq_tabs)))
    assert "(CTD))" not in body
    assert "[Environment (CTD)](#tab-environment-ctd)" in body
    # A tab the family does not hold (the how-to-read list names SIDLE) is
    # left out rather than listed as plain text.
    assert "\n- SIDLE" not in body


def test_a_headings_aside_is_the_pages_only(ampliseq_tabs):
    body = _body(generate_qmd(_plan(ampliseq_tabs)))
    line = next(ln for ln in body.split("\n") if "{#filters}" in ln)
    assert (
        '[<span class="dpx-h-note">none active</span>]{.content-visible when-format="html"}' in line
    )


# ── The PDF's structure (round 3) ───────────────────────────────────────────


def _pdf_src(ampliseq_tabs, **extra):
    project = {
        "name": "Ampliseq",
        "workflows": [
            {
                "name": "ampliseq",
                "version": "3.1.0",
                "engine": {"name": "nextflow"},
                "catalog": {"name": "nf-core"},
            }
        ],
        "template_origin": {"template_id": "nf-core/ampliseq/3.1.0"},
    }
    return generate_qmd(_plan(ampliseq_tabs, pdf=True, project=project, **extra))


def test_the_cover_says_what_the_file_is_and_carries_the_real_fields(ampliseq_tabs):
    block = _typst_block(_body(_pdf_src(ampliseq_tabs, dashboard_public=True)))
    assert "DASHBOARD REPORT" in block
    assert "A static report of the interactive Depictio dashboard" in block
    assert "live at" in block
    for label, value in (
        ("Project", "Ampliseq"),
        ("Pipeline", "nf-core/ampliseq 3.1.0 (nextflow)"),
        ("Template", "nf-core/ampliseq/3.1.0"),
        ("Exported state", "No filter active"),
    ):
        assert f'[#"{label}"]' in block and value in block, label
    assert '[#"Tabs"]' in block and "Overview, MultiQC" in block
    assert '[#"Data read"]' in block and "data collections" in block
    # Nothing made up: a private dashboard has no live link, a project with
    # no workflow no pipeline row.
    private = _typst_block(_body(generate_qmd(_plan(ampliseq_tabs, pdf=True))))
    assert "live at" not in private and '[#"Pipeline"]' not in private


def test_the_running_header_names_the_report(ampliseq_tabs):
    block = _typst_block(_body(_pdf_src(ampliseq_tabs)))
    assert "#dpx-title] · Dashboard report" in block
    assert "tabs.last().body" in block


def test_the_contents_are_in_the_text_colour(ampliseq_tabs):
    for style in ("colour", "mono"):
        block = _typst_block(_body(_pdf_src(ampliseq_tabs, pdf_style=style)))
        assert "#show outline.entry: it =>" not in block  # no per-entry colouring


def test_every_tab_after_the_first_is_an_appendix(ampliseq_tabs):
    body = _body(_pdf_src(ampliseq_tabs))
    assert "## Appendices {#appendices}" in body
    assert body.count("{#appendices}") == 1
    assert '[Appendix A — MultiQC]{.content-visible when-format="typst"}' in body
    assert '[MultiQC]{.content-visible when-format="html"}' in body
    assert "Appendix A — Overview" not in body  # the overview is the report
    # The page keeps its tabs: no appendices without the PDF.
    plain = _body(generate_qmd(_plan(ampliseq_tabs)))
    assert "Appendix" not in plain and "{#appendices}" not in plain


def test_headings_carry_their_icon_in_the_pdf(ampliseq_tabs):
    plan = _plan(ampliseq_tabs, pdf=True)
    plan.icons = {"mdi:counter": '<svg viewBox="0 0 24 24"><path fill="currentColor"/></svg>'}
    block = _typst_block(_body(generate_qmd(plan)))
    m = re.search(r"#let dpx-icons = \((.*?)\)\n", block)
    assert m and '"sec-key-figures": "<svg' in m.group(1)
    # In the heading's colour, as an SVG typst reads (xmlns added).
    assert "xmlns=" in m.group(1) and "currentColor" not in m.group(1)


def test_the_stepper_and_fact_list_are_drawn_for_the_pdf(ampliseq_tabs):
    body = _body(_pdf_src(ampliseq_tabs))
    assert "#dpx-steps((" in body and "#dpx-facts((" in body
    # The page keeps its own markup for them.
    assert ':::: {.content-visible when-format="html"}' in body
    assert "#dpx-steps" not in _body(generate_qmd(_plan(ampliseq_tabs)))


def test_the_kpi_strip_is_a_card_grid_in_the_pdf():
    from depictio.notebook import StaticCard, static_card_row

    out = static_card_row([StaticCard("Samples", "12"), StaticCard("Phyla", "57")])
    assert '#dpx-kpis(dpx-kpi("Samples", "12"), dpx-kpi("Phyla", "57"))' in out
    assert out.strip().startswith("````{=typst}")


def test_icons_are_svg_typst_can_read_without_the_network():
    from depictio.notebook.typst import colored_svg

    svg = colored_svg(
        '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M0 0"/></svg>', "#fd7e14"
    )
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg and "#fd7e14" in svg
    assert colored_svg(None, "#000") is None


def test_the_table_builder():
    import polars as pl

    from depictio.notebook.typst import table

    df = pl.DataFrame(
        {
            "sample": [f"SRR100701{i:02d}" for i in range(40)],
            "count": list(range(1000, 1040)),
            "share": [0.123456] * 40,
            **{f"c{i}": ["x"] * 40 for i in range(9)},
        }
    )
    out = table(df)
    assert out.strip().startswith("````{=typst}") and "#dpx-table(" in out
    # Numbers right-aligned and formatted like the dashboard's.
    assert "align: (left, right, right, left," in out
    assert '"1,000"' in out and '"0.1235"' in out
    # Widths from what the columns hold, never more than the page.
    assert re.search(r"columns: \((\d+\.\d+fr, ?)+\)", out)
    # 12 columns: more than a portrait page holds, all of them on a
    # landscape one (the mark the preamble's show rule reads).
    assert "#dpx-wide[" in out
    assert f"Showing {LANDSCAPE_TABLE_ROWS} of 40 rows; the HTML report has the whole table." in out


def test_a_tile_that_cannot_be_drawn_is_named_not_numbered():
    from depictio.notebook.components import DepictioComponent, readable_name

    assert readable_name("general_stats") == "General statistics"
    assert readable_name("Per Base N Content") == "Per Base N Content"

    class _C(DepictioComponent):
        pass

    comp = _C.__new__(_C)
    comp.meta = {"index": "1bba76a2-2824-46b9-bad2-0add3f6fc001", "selected_plot": "general_stats"}
    assert comp.title == "General statistics"
    comp.meta = {"index": "1bba76a2-2824-46b9-bad2-0add3f6fc001", "component_type": "multiqc"}
    assert "1bba76a2" not in comp.title


def test_the_pdf_holds_the_parameters_its_links_point_to(ampliseq_tabs):
    project = {"template_origin": {"run_provenance": [{"group": "g", "key": "input", "value": 1}]}}
    body = _body(generate_qmd(_plan(ampliseq_tabs, project=project, pdf=True)))
    assert "[Run parameters](#export-parameters)" in body
    # The page's target is its header fold; the PDF's a part of its own.
    assert "## Run parameters {#export-parameters}" in body
    assert "#dpx-table(" in body.split("{#export-parameters}")[1]
    assert "## Run parameters" not in _body(generate_qmd(_plan(ampliseq_tabs, project=project)))


def test_static_figures_give_crowded_category_labels_room(monkeypatch):
    import plotly.graph_objects as go

    from depictio.notebook import components as c

    # MultiQC's FastQC status heatmap: ten wrapped labels, a fixed flat angle.
    labels = [
        "Basic <br>Statistics",
        "Per Base <br>Sequence <br>Quality",
        "Per <br>Sequence <br>Quality <br>Scores",
        "Per Base <br>Sequence <br>Content",
        "Per <br>Sequence <br>GC Content",
        "Per Base N<br> Content",
        "Sequence <br>Length <br>Distribution",
        "Sequence <br>Duplication<br> Levels",
        "Overrepresented<br> Sequences",
        "Adapter <br>Content",
    ]
    fig = go.Figure(go.Heatmap(z=[[0] * 10] * 4, y=[f"SRR1007013{i}_1" for i in range(4)]))
    fig.update_layout(
        height=400,
        xaxis={
            "type": "category",
            "tickmode": "array",
            "tickvals": list(range(10)),
            "ticktext": labels,
            "tickangle": 0,
        },
    )
    c.fit_category_axes(fig, 720)
    assert fig.layout.xaxis.tickangle == -45
    assert fig.layout.xaxis.automargin and fig.layout.yaxis.automargin
    assert "Per Sequence Quality Scores" in fig.layout.xaxis.ticktext
    assert not any("<br>" in t for t in fig.layout.xaxis.ticktext)
    assert fig.layout.height > 400  # the plot keeps its height under the labels

    # Slots narrower than a line of text: upright labels.
    many = go.Figure(go.Bar(x=[f"sample_number_{i}" for i in range(80)], y=[1] * 80))
    many.update_layout(height=400)
    c.fit_category_axes(many, 720)
    assert many.layout.xaxis.tickangle == -90

    # Labels that fit, numbers and dates are left as the author drew them.
    for x in (["A", "B", "C"], [1, 2, 3], ["2023-01-01", "2023-02-01", "2023-03-01"]):
        f = go.Figure(go.Bar(x=x, y=[1, 2, 3]))
        f.update_layout(height=400)
        c.fit_category_axes(f, 720)
        assert f.layout.xaxis.tickangle is None and f.layout.height == 400

    # A figure in a row is drawn at its share of the column.
    seen = {}
    monkeypatch.setattr(
        go.Figure, "to_image", lambda self, **kw: seen.update(kw) or b"png", raising=True
    )
    c.set_static_width(360)
    try:
        assert c.figure_png(go.Figure(go.Bar(x=[1], y=[1])))
        assert seen["width"] == 360
    finally:
        c.set_static_width(None)


def test_a_section_description_and_its_note_stay_two_lines(penguins_tabs):
    for pdf in (False, True):
        body = _body(generate_qmd(_plan(penguins_tabs, pdf=pdf)))
        note = "*On the dashboard this section is shown on every tab"
        assert note in body
        before = body.split(note, 1)[0]
        # A markdown hard break, which a typst page keeps; never a bare <br>.
        assert before.endswith("*\\\n"), before[-80:]
        assert "*<br>*On the dashboard" not in body


def test_a_pdf_card_prints_its_value_in_the_cards_own_format():
    from depictio.notebook.components import CardComponent

    def card(value, **meta):
        comp = CardComponent.__new__(CardComponent)
        comp.meta = {"index": "c1", "title": "Shannon", "aggregation": "median", **meta}
        comp._data = {"value": value, "secondary": None, "icon_svg": None}
        return comp

    assert '"7.70"' in card(7.7049, decimals=2)._typst_card_()
    assert '"61.5"' in card(61.52, decimals=1)._typst_card_()
    assert '"41%"' in card(0.41, format="percent")._typst_card_()
    assert '"214.3k"' in card(214321, format="si")._typst_card_()
    # No format: the dashboard's magnitude-aware rounding, not four digits.
    assert '"7.71"' in card(7.7051)._typst_card_()
    assert '"12"' in card(12)._typst_card_()
    # `format` wins over `decimals`, as in the app.
    assert '"41%"' in card(0.41, format="percent", decimals=2)._typst_card_()
    # The box-plot strip reads the same format.
    boxed = card(
        7.7049,
        decimals=2,
        secondary_layout="box_plot",
    )
    boxed._data["secondary"] = {"box_plot_stats": {"min": 5.2511, "median": 7.7049, "max": 9.4}}
    assert 'dpx-range("5.25", "7.70", "9.40")' in boxed._typst_card_()


def test_a_failed_tiles_caption_does_not_claim_data(ampliseq_tabs):
    from depictio.api.v1.services.notebook_export.pdf_typst import DEFINITIONS, TYPST_TILE_DONE

    body = _body(generate_qmd(_plan(ampliseq_tabs, pdf=True)))
    # The PDF's badge is typst, silent under a tile that failed; the HTML's
    # is the same span as ever.
    assert re.search(
        r'\[<span class="dpx-asof">Data: [^<]+</span>\]\{\.content-visible when-format="html"\}'
        r'`#dpx-asof\("Data: [^"]+"\)`\{=typst\}',
        body,
    )
    assert "dpx-failed.update(true)" in DEFINITIONS.split("#let dpx-note", 1)[1].split("#let", 1)[0]
    assert "if not dpx-failed.get()" in DEFINITIONS
    # A tile with no caption (here a card on its own) clears the mark itself.
    tabs = copy.deepcopy(ampliseq_tabs)
    lone = next(m for m in tabs[0]["stored_metadata"] if m.get("component_type") == "figure")
    lone.update(component_type="card", aggregation="count", column_name="sample")
    assert TYPST_TILE_DONE in _body(generate_qmd(_plan(tabs, pdf=True)))
    assert TYPST_TILE_DONE not in _body(generate_qmd(_plan(tabs)))
    html_only = _body(generate_qmd(_plan(ampliseq_tabs)))
    assert "dpx-asof(" not in html_only and TYPST_TILE_DONE not in html_only
    assert '<span class="dpx-asof">Data: ' in html_only


# ── Report settings ─────────────────────────────────────────────────────────


def _with_settings(tabs, **settings) -> str:
    layer = ReportLayer.model_validate({"settings": settings})
    return generate_qmd(_plan(tabs, report_layer=layer, pdf=True))


def test_report_settings_default_to_the_report_as_it_was(ampliseq_tabs):
    """A layer with every setting at its default exports what no layer does."""
    assert _with_settings(ampliseq_tabs) == generate_qmd(
        _plan(ampliseq_tabs, report_layer=ReportLayer().model_dump(), pdf=True)
    )
    src = _with_settings(ampliseq_tabs)
    front = _front(src)
    assert front["format"]["html"]["toc"] is True
    assert front["format"]["html"]["code-tools"] is True
    assert front["format"]["typst"]["papersize"] == "a4"
    for part in ("Export details", "How to run", "Methods and citations", "dpx-asof", "Contents"):
        assert part in src
    assert "#set figure(numbering: none)" not in src
    assert "#set page(flipped: true)" not in src
    assert 'data-viz-controls="popover"' in front["format"]["html"]["include-before-body"]["text"]


def test_report_settings_take_parts_out(ampliseq_tabs):
    src = _with_settings(
        ampliseq_tabs,
        toc=False,
        code=False,
        export_details=False,
        how_to_run=False,
        methods=False,
        provenance=False,
    )
    front = _front(src)
    assert front["format"]["html"]["toc"] is False
    assert front["format"]["html"]["code-tools"] is False
    assert "references" not in front
    body = _body(src)
    # The typst preamble still defines ``dpx-asof``; no tile calls it.
    for part in (
        "Export details",
        "How to run",
        "Methods and citations",
        'class="dpx-asof"',
        "`#dpx-asof(",
        "[Contents]",
    ):
        assert part not in body, part


def test_report_settings_shape_the_pdf_and_the_captions(ampliseq_tabs):
    src = _with_settings(
        ampliseq_tabs, paper="letter", landscape=True, numbering=False, viz_controls="rail"
    )
    front = _front(src)
    assert front["format"]["typst"]["papersize"] == "us-letter"
    assert "#set page(flipped: true)" in src
    assert "#set figure(numbering: none)" in src
    assert "(?:Figure|Table)" in front["format"]["html"]["include-after-body"]["text"]
    assert 'data-viz-controls="rail"' in front["format"]["html"]["include-before-body"]["text"]


def test_every_tile_is_full_width_by_default(ampliseq_tabs):
    """A report reads top to bottom: no dashboard row unless asked for."""
    before = _body(_with_settings(ampliseq_tabs, tile_width="row"))
    assert 'layout="[5,3]"' in before
    src = _body(generate_qmd(_plan(ampliseq_tabs)))
    assert 'layout="[5,3]"' not in src
    # Cards keep their strip.
    assert "card_row([viz_samples, viz_phyla, viz_shannon_diversity, viz_reads_kept])" in src


def test_a_tile_can_keep_its_dashboard_row(ampliseq_tabs):
    """Under the full-width default, two tiles both set to their row share it."""
    main = next(
        t for t in ampliseq_tabs for m in t["stored_metadata"] if m.get("index") == "ov-run"
    )
    row = [m["index"] for m in main["stored_metadata"] if m.get("index") in ("ov-run", "ov-study")]
    layer = ReportLayer.model_validate(
        {
            "tiles": [
                {"tab_id": str(main["dashboard_id"]), "component_id": str(i), "full_width": False}
                for i in row
            ]
        }
    )
    src = _body(generate_qmd(_plan(ampliseq_tabs, report_layer=layer)))
    assert src.count('layout="[5,3]"') == 1


def test_a_large_table_opens_a_pdf_page(ampliseq_tabs):
    on = _with_settings(ampliseq_tabs)
    off = _with_settings(ampliseq_tabs, table_page_break=False)
    assert "`#pagebreak(weak: true)`{=typst}" in on
    assert "`#pagebreak(weak: true)`{=typst}" not in off


def test_a_section_opening_on_a_large_table_turns_the_page_before_its_heading(ampliseq_tabs):
    # The break sits before the section's heading, never between the heading
    # and its table: a heading alone at the foot of a page is not read.
    on = _with_settings(ampliseq_tabs)
    br = "`#pagebreak(weak: true)`{=typst}"
    section = on.index(':Sample sheet"}')
    head = on.rindex("::::", 0, section)
    assert on[:head].rstrip().endswith(br)
    heading = on.index("Sample sheet</span>", section)
    table = on.index("{#tbl-", heading)
    assert br not in on[heading:table]


def test_a_highlight_keeps_its_lead_and_title_with_its_figure_in_the_pdf(ampliseq_tabs):
    # The "From the ... tab." line was left at the foot of a page the figure
    # moved off; in the PDF it rides a sticky block with the figure's title.
    src = _with_settings(ampliseq_tabs)
    at = src.index("*From the [")
    opened = src.rindex("#block(sticky: true)[", 0, at)
    assert "```" not in src[opened:at].replace("```\n\n", "", 1)
    assert "Phylum composition per group" in src[opened:at]
    assert src.index("```{=typst}\n]\n```", at) > at
    html = generate_qmd(_plan(ampliseq_tabs))
    assert "*From the [" in html and "#block(sticky: true)[" not in html


def test_a_section_description_keeps_with_what_follows_in_the_pdf(ampliseq_tabs):
    # "Key figures" and its line were left at the foot of a page whose cards
    # moved on; a section opening on a wide table left both on a portrait page
    # before its landscape one. The PDF draws the line through `dpx-lead`,
    # which keeps with the tile and moves with its heading.
    src = _with_settings(ampliseq_tabs)
    heading = src.index("Key figures</span>")
    lead = src.index("#dpx-lead((", heading)
    assert '"The run in four numbers.' in src[lead : src.index("\n", lead)]
    assert src.rindex('{.content-visible when-format="html"}', heading, lead) > heading
    html = generate_qmd(_plan(ampliseq_tabs))
    assert "#dpx-lead(" not in html and "*The run in four numbers" in html


def test_a_tab_map_is_kept_on_one_pdf_page(ampliseq_tabs):
    src = _with_settings(ampliseq_tabs)
    tiles = src.index("#dpx-tab-tiles(")
    opened = src.rindex("#block(breakable: false)[", 0, tiles)
    assert "```{=typst}\n]\n```" in src[tiles:]
    assert src.count("#dpx-tab-tiles(", opened, src.index("```{=typst}\n]\n```", tiles)) >= 2


def test_tables_wear_the_dashboard_colours(ampliseq_tabs):
    src = _body(generate_qmd(_plan(ampliseq_tabs)))
    assert "colors=depictio_category_colors)" in src
