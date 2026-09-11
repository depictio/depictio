"""Every dashboard YAML shipped under ``depictio/projects/`` must import cleanly.

Why this exists rather than leaning on the CLI's own validation: ``depictio
dashboard validate`` model-validates ``main_dashboard`` and stops. A multi-tab
file's ``tabs:`` entries are never checked — and that is where most of the
shipped surface lives (ampliseq ships six tabs, viralrecon four). Bugs that
reached ``main`` through that gap include an ``advanced_viz`` bound to a
catalog render id that does not exist, and cards whose secondary strip renders
blank because the layout and the config that feeds it were never paired.

The three checks below are deliberately of different kinds:

* **model validation** — the same thing the importer does, applied to every
  tab. ``DashboardDataLite._COMPONENT_TYPE_MAP`` has no entry for ``text`` or
  ``advanced_viz``, so those two fall through the union to ``dict`` and are
  never domain-checked; ``advanced_viz`` is re-validated explicitly here,
  which is what catches a bad ``use:``.
* **secondary-strip config** — every layout draws from a different field, and
  choosing the layout without the field it reads produces an empty strip and
  no error anywhere. The pairing table is copied from the ``secondary_layout``
  field description in ``depictio/models/components/lite.py``.
* **section icons and colours** — an id outside ``SECTION_ICON_OPTIONS`` is one
  the section form cannot offer, so opening that form and saving an unrelated
  field blanks the icon (``iconOptionsWith`` keeps it selectable, but only
  until someone picks another). Bundling itself is no longer the risk:
  ``scripts/generate-icon-subset.mjs`` now scans the shipped dashboard data as
  well as the TS sources, so a YAML-only id reaches the bundle on its own.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from depictio.models.components.advanced_viz.component import AdvancedVizLiteComponent
from depictio.models.models.dashboards import DashboardDataLite

REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECTS_DIR = REPO_ROOT / "depictio" / "projects"
SECTION_ICONS_TS = (
    REPO_ROOT / "depictio" / "viewer" / "src" / "components" / "sections" / "sectionIcons.ts"
)

# Which config field each secondary layout actually reads. Mirrors the
# `secondary_layout` field description in depictio/models/components/lite.py;
# a layout added there and forgotten here is caught by
# `test_layout_requirement_table_covers_every_layout` below.
_STRIP_REQUIREMENTS: dict[str, str | None] = {
    # Drawn from the card's own `aggregations` list.
    "vertical": "aggregations",
    "compact": "aggregations",
    "grid": "aggregations",
    # Compound aggregation; only this layout can draw it.
    "box_plot": "box_plot_stats",
    # Server groups by this column.
    "top_n": "breakdown_col",
    "concentration": "breakdown_col",
    "composition": "breakdown_col",
    "donut": "breakdown_col",
    # Denominator for the fill bar / dial.
    "coverage": "coverage_max",
    "gauge": "coverage_max",
    # Axis the sparkline is bucketed along.
    "trend": "trend_col",
    # QC cut-off rows are counted against.
    "threshold": "threshold_value",
    # Ordered stage columns.
    "attrition": "attrition_cols",
    # Computed wholly server-side from the card's own column.
    "histogram": None,
    "completeness": None,
    "uniqueness": None,
}


def _shipped_yamls() -> list[Path]:
    return sorted(PROJECTS_DIR.glob("**/dashboards/*.yaml"))


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _tabs_of(doc: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(label, dashboard-dict) for every tab a shipped file declares.

    Two shapes ship today: a flat single dashboard, and `main_dashboard` plus
    a `tabs` list. Both are unpacked so a check never sees only the first tab.
    """
    if "main_dashboard" in doc:
        out = [("main_dashboard", doc["main_dashboard"])]
        out += [
            (f"tabs[{i}] {tab.get('title', '?')!r}", tab)
            for i, tab in enumerate(doc.get("tabs") or [])
        ]
        return out
    return [("<root>", doc)]


def _parse_ts_string_list(source: str, const_name: str) -> set[str]:
    """The `value:` literals of one exported array in sectionIcons.ts.

    Parsed rather than imported because the allow-list is TypeScript: it is the
    icon-subset generator's input, so the TS file is the authority and a Python
    copy of it would be the very drift this test exists to prevent.
    """
    match = re.search(rf"export const {const_name}[^=]*=\s*\[(.*?)\n\];", source, re.S)
    assert match, f"{const_name} not found in {SECTION_ICONS_TS}"
    return set(re.findall(r"value:\s*'([^']*)'", match.group(1)))


ALLOWED_SECTION_ICONS = _parse_ts_string_list(SECTION_ICONS_TS.read_text(), "SECTION_ICON_OPTIONS")
ALLOWED_SECTION_COLORS = _parse_ts_string_list(
    SECTION_ICONS_TS.read_text(), "SECTION_COLOR_OPTIONS"
)


@pytest.mark.no_db
def test_shipped_yamls_are_discovered():
    """A glob that silently matches nothing would make every test below vacuous."""
    assert len(_shipped_yamls()) >= 8


@pytest.mark.no_db
def test_layout_requirement_table_covers_every_layout():
    """`_STRIP_REQUIREMENTS` must name every layout the model accepts."""
    field = DashboardDataLite._COMPONENT_TYPE_MAP["card"].model_fields["secondary_layout"]
    declared = set(field.annotation.__args__)  # type: ignore[union-attr]
    assert declared == set(_STRIP_REQUIREMENTS), (
        "secondary_layout gained or lost a value; update _STRIP_REQUIREMENTS "
        f"(model-only: {sorted(declared - set(_STRIP_REQUIREMENTS))}, "
        f"table-only: {sorted(set(_STRIP_REQUIREMENTS) - declared)})"
    )


@pytest.mark.no_db
@pytest.mark.parametrize("path", _shipped_yamls(), ids=_rel)
def test_every_tab_validates(path: Path):
    """Model-validate the main dashboard *and* each tab, not just the first."""
    doc = yaml.safe_load(path.read_text())
    errors: list[str] = []
    for label, tab in _tabs_of(doc):
        try:
            DashboardDataLite.model_validate(tab)
        except Exception as exc:  # pydantic ValidationError or a validator's ValueError
            errors.append(f"{label}: {exc}")
    assert not errors, f"{_rel(path)} does not import:\n" + "\n\n".join(errors)


@pytest.mark.no_db
@pytest.mark.parametrize("path", _shipped_yamls(), ids=_rel)
def test_advanced_viz_components_validate(path: Path):
    """`advanced_viz` falls through the union to `dict` — check it explicitly.

    This is the check that catches a `use:` naming a catalog render id or
    output that does not exist, which otherwise surfaces only as a tile that
    fails to render on a deployed instance.
    """
    doc = yaml.safe_load(path.read_text())
    errors: list[str] = []
    for label, tab in _tabs_of(doc):
        for comp in tab.get("components") or []:
            if not isinstance(comp, dict) or comp.get("component_type") != "advanced_viz":
                continue
            try:
                AdvancedVizLiteComponent.model_validate(comp)
            except Exception as exc:
                errors.append(f"{label} [{comp.get('tag', '?')}]: {exc}")
    assert not errors, f"{_rel(path)} has invalid advanced_viz:\n" + "\n\n".join(errors)


@pytest.mark.no_db
@pytest.mark.parametrize("path", _shipped_yamls(), ids=_rel)
def test_advanced_viz_survives_the_component_union(path: Path):
    """A component that validates alone can still be lost by the union.

    ``DashboardDataLite.components`` is ``list[LiteComponent | dict[str, Any]]``.
    Pydantic's smart union runs a strict pass first, and the ``dict`` member
    matches any mapping, so a component that fails only under strict rules is
    silently kept as a raw dict instead of raising. It reaches the database
    with no ``viz_kind`` and the viewer renders `Unknown advanced viz kind: ""`.

    ``test_advanced_viz_components_validate`` cannot see this: it validates each
    component on its own, where the lax pass applies and everything passes. The
    trigger found in the wild was ``shaded_bands``, typed as a tuple, which YAML
    can only spell as a list.
    """
    doc = yaml.safe_load(path.read_text())
    errors: list[str] = []
    for label, tab in _tabs_of(doc):
        expected = sum(
            1
            for comp in tab.get("components") or []
            if isinstance(comp, dict) and comp.get("component_type") == "advanced_viz"
        )
        if not expected:
            continue
        lite = DashboardDataLite.model_validate(tab)
        degraded = [
            comp.get("tag") or comp.get("index") or "?"
            for comp in lite.components
            if isinstance(comp, dict) and comp.get("component_type") == "advanced_viz"
        ]
        if degraded:
            errors.append(
                f"{label}: {len(degraded)} of {expected} advanced_viz components lost to the "
                f"dict member of the union: {', '.join(degraded)}"
            )
    assert not errors, f"{_rel(path)} degrades advanced_viz:\n" + "\n\n".join(errors)


@pytest.mark.no_db
@pytest.mark.parametrize("path", _shipped_yamls(), ids=_rel)
def test_card_secondary_strips_have_the_config_they_read(path: Path):
    """A layout without the field it draws from renders an empty strip, silently."""
    doc = yaml.safe_load(path.read_text())
    errors: list[str] = []
    for label, tab in _tabs_of(doc):
        for comp in tab.get("components") or []:
            if not isinstance(comp, dict) or comp.get("component_type") != "card":
                continue
            layout = comp.get("secondary_layout", "vertical")
            required = _STRIP_REQUIREMENTS.get(layout)
            if required is None:
                continue
            aggregations = comp.get("aggregations") or []
            if required == "box_plot_stats":
                satisfied = "box_plot_stats" in aggregations
            elif required == "aggregations":
                # `vertical` is the default, so a plain single-metric card
                # lands here with no strip intended at all. Only a layout the
                # author chose on purpose is a promise of a strip.
                if "secondary_layout" not in comp:
                    continue
                satisfied = bool(aggregations)
            else:
                satisfied = bool(comp.get(required))
            if not satisfied:
                errors.append(
                    f"{label} [{comp.get('tag', '?')}]: secondary_layout "
                    f"{layout!r} draws from {required!r}, which is unset"
                )
    assert not errors, f"{_rel(path)} has cards with a blank secondary strip:\n" + "\n".join(errors)


@pytest.mark.no_db
@pytest.mark.parametrize("path", _shipped_yamls(), ids=_rel)
def test_component_sections_are_declared_in_the_right_list(path: Path):
    """A component's `section` must be declared, and in the matching list.

    `filter_sections` and `grid_sections` are two independent lists on purpose:
    a section named "QC" in the left panel and one in the grid are different
    placements that happen to share a name. The cost is that declaring a grid
    section under `filter_sections` fails silently — the section still renders,
    just expanded and with no icon, which looks like a styling slip rather than
    a mis-filed declaration. Interactive components live in the filter panel;
    everything else lives in the grid.
    """
    doc = yaml.safe_load(path.read_text())
    errors: list[str] = []
    for label, tab in _tabs_of(doc):
        declared = {
            "filter_sections": {s.get("name") for s in tab.get("filter_sections") or []},
            "grid_sections": {s.get("name") for s in tab.get("grid_sections") or []},
        }
        for comp in tab.get("components") or []:
            if not isinstance(comp, dict):
                continue
            section = comp.get("section")
            if not section:
                continue
            mine, other = (
                ("filter_sections", "grid_sections")
                if comp.get("component_type") == "interactive"
                else ("grid_sections", "filter_sections")
            )
            if section in declared[mine]:
                continue
            where = f" (it is declared under {other})" if section in declared[other] else ""
            errors.append(
                f"{label} [{comp.get('tag', '?')}]: section {section!r} is not declared "
                f"in {mine}{where} — it renders unstyled and sorts last"
            )
    assert not errors, f"{_rel(path)} has undeclared sections:\n" + "\n".join(errors)


@pytest.mark.no_db
@pytest.mark.parametrize("path", _shipped_yamls(), ids=_rel)
def test_section_icons_and_colors_are_bundled(path: Path):
    """Section icons must be one the section form can offer.

    `iconOptionsWith` keeps a YAML-authored id selectable so opening the form
    does not blank it, but the moment a user picks a different icon the
    original is gone from the list. An id the picker knows is one a user can
    put back.
    """
    doc = yaml.safe_load(path.read_text())
    errors: list[str] = []
    for label, tab in _tabs_of(doc):
        for key in ("filter_sections", "grid_sections"):
            for section in tab.get(key) or []:
                icon = section.get("icon")
                if icon and icon not in ALLOWED_SECTION_ICONS:
                    errors.append(
                        f"{label} {key}[{section.get('name', '?')!r}]: icon {icon!r} is not in "
                        "SECTION_ICON_OPTIONS — it will render as an empty box"
                    )
                color = section.get("color")
                if color and color not in ALLOWED_SECTION_COLORS:
                    errors.append(
                        f"{label} {key}[{section.get('name', '?')!r}]: color {color!r} is not a "
                        f"Mantine palette name in SECTION_COLOR_OPTIONS"
                    )
    assert not errors, f"{_rel(path)} has unbundled section styling:\n" + "\n".join(errors)


@pytest.mark.no_db
@pytest.mark.parametrize("path", _shipped_yamls(), ids=_rel)
def test_upset_set_colouring_declares_its_palette(path: Path):
    """`color_intersections_by: set` without `set_colors` paints the plot black.

    plotly-upset's `_compute_bar_colors` returns `self.color` for every bar when
    no set -> colour map was supplied, and that default is `#333333`. Two shipped
    dashboards were rendering an entirely black UpSet this way, before any
    filter was applied. A template whose set names are only known at ingest
    cannot supply a map, so it has to pick `degree` colouring instead.
    """
    doc = yaml.safe_load(path.read_text())
    errors: list[str] = []
    for label, tab in _tabs_of(doc):
        for comp in tab.get("components") or []:
            if not isinstance(comp, dict):
                continue
            config = comp.get("config") or {}
            if config.get("viz_kind") != "upset_plot":
                continue
            if config.get("color_intersections_by") != "set":
                continue
            if not config.get("set_colors"):
                errors.append(
                    f"{label} [{comp.get('tag', '?')}]: color_intersections_by "
                    "'set' with no set_colors renders every bar #333333; "
                    "supply set_colors or use 'degree'"
                )
    assert not errors, f"{_rel(path)} has an all-black UpSet:\n" + "\n".join(errors)


# A grid row is ~100px. A full-width text tile fits its title plus roughly two
# lines of body in one row; past that the text overflows the tile, because
# TextRenderer applies no maxHeight, overflow or line clamp.
# Roughly what one grid row fits at the full 8-column width. The viewer
# autofits text tiles at render, so this guards the STORED estimate against
# going wildly wrong (which is what the first paint shows), not the final
# rendered size.
# `packages/depictio-react-core/src/gridConfig.ts`.
GRID_COLUMNS = 8

_TEXT_CHARS_PER_ROW = 300

# `[label](https://…)` renders as `label`, so the href is authored characters
# that never reach the tile. Counting it would push a tile over budget for
# adding a link, i.e. penalise the very thing the renderer just learned to do.
_MARKDOWN_LINK = re.compile(r"\[([^\]\n]+)\]\((?:https?://[^)\s]+|/[^)\s]*)\)")


def _rendered_length(body: str) -> int:
    """Characters the reader actually sees, which is what has to fit."""
    return len(_MARKDOWN_LINK.sub(r"\1", body))


@pytest.mark.no_db
@pytest.mark.parametrize(
    "path",
    _shipped_yamls(),
    ids=_rel,
)
def test_text_tiles_are_tall_enough_for_their_body(path: Path):
    """Every shipped dashboard, not just the demo ones.

    Heights are derived rather than hand-pinned: `build_reference_dashboard.py`
    runs the same rule over the tiles it generates, so reworded prose cannot
    silently start overflowing.
    """
    doc = yaml.safe_load(path.read_text())
    errors: list[str] = []
    for label, tab in _tabs_of(doc):
        for comp in tab.get("components") or []:
            if not isinstance(comp, dict) or comp.get("component_type") != "text":
                continue
            body = comp.get("body") or ""
            height = (comp.get("layout") or {}).get("h")
            if height is None:
                continue
            budget = _TEXT_CHARS_PER_ROW * height
            shown = _rendered_length(body)
            if shown > budget:
                errors.append(
                    f"{label} [{comp.get('tag', '?')}]: {shown} chars in h={height} "
                    f"(fits ~{budget}); raise h or trim the body"
                )
    assert not errors, f"{_rel(path)} has overflowing text tiles:\n" + "\n".join(errors)


def _is_multiqc_panel(comp: dict) -> bool:
    """A tile that renders a panel out of the MultiQC report itself."""
    if comp.get("component_type") == "multiqc":
        return True
    if str(comp.get("use") or "").startswith("multiqc/"):
        return True
    return bool(comp.get("selected_module") or comp.get("selected_plot"))


@pytest.mark.no_db
@pytest.mark.parametrize("path", _shipped_yamls(), ids=_rel)
def test_multiqc_tabs_hold_only_multiqc_panels(path: Path):
    """A tab called MultiQC is the MultiQC report, not a second overview page.

    Tiles built from the pipeline's own tool outputs kept accumulating there
    because the MultiQC tab is usually the landing tab, which makes it the
    tempting place for headline numbers. The result was a tab whose name
    promised one thing and whose content answered another, and a reader with a
    MultiQC question had to scroll past cards to reach it.

    Three things are not violations:
      * `text` and `interactive` tiles, the intros and the filters;
      * anything in a persistent pinned section, which appears on every tab by
        design (the sample sheet, the reference tables);
      * a component with `placement: floating`, which overlays the dashboard
        rather than taking a place in the tab's grid.
    """
    doc = yaml.safe_load(path.read_text())
    errors: list[str] = []
    for label, tab in _tabs_of(doc):
        # `main_tab_name` names the main tab; a secondary tab names itself with
        # `title`. Reading only one of the two is how a MultiQC tab that is not
        # the landing tab slips past this check.
        name = tab.get("main_tab_name") or tab.get("title") or ""
        if "multiqc" not in str(name).lower():
            continue
        pinned = {
            section.get("name")
            for section in (tab.get("grid_sections") or [])
            if isinstance(section, dict) and section.get("persistent") and section.get("pin")
        }
        for comp in tab.get("components") or []:
            if not isinstance(comp, dict):
                continue
            if comp.get("component_type") in {"text", "interactive"}:
                continue
            if comp.get("placement") == "floating":
                continue
            if comp.get("section") in pinned:
                continue
            if _is_multiqc_panel(comp):
                continue
            errors.append(
                f"{label} [{comp.get('tag', '?')}]: {comp.get('component_type')} on "
                f"{comp.get('use') or comp.get('data_collection_tag')} in section "
                f"{comp.get('section')!r}, which is not a MultiQC panel"
            )
    assert not errors, f"{_rel(path)} has non-MultiQC tiles on a MultiQC tab:\n" + "\n".join(errors)


@pytest.mark.no_db
@pytest.mark.parametrize("path", _shipped_yamls(), ids=_rel)
def test_tables_are_full_width(path: Path):
    """A table narrower than the grid is not a smaller table, it is a broken one.

    AG Grid keeps its columns at their natural width and scrolls horizontally,
    so a `w: 4` table shows two of its eight columns and spends a third of its
    height on the scrollbar. Half-width tables kept reappearing in shipped
    dashboards because a pair of them looks tidy in the YAML, which is why this
    is a test and not a review note.
    """
    doc = yaml.safe_load(path.read_text())
    errors: list[str] = []
    for label, tab in _tabs_of(doc):
        for comp in tab.get("components") or []:
            if not isinstance(comp, dict) or comp.get("component_type") != "table":
                continue
            layout = comp.get("layout") or {}
            width = layout.get("w")
            if width is None or width == GRID_COLUMNS:
                continue
            errors.append(
                f"{label} [{comp.get('tag', '?')}]: table at w={width}; tables span "
                f"all {GRID_COLUMNS} columns"
            )
    assert not errors, f"{_rel(path)} has narrow tables:\n" + "\n".join(errors)


@pytest.mark.no_db
def test_a_tool_link_costs_the_tile_nothing():
    """The href is authored, not rendered, so it must not eat the height budget."""
    plain = "Peak calling is done by MACS2, per sample."
    linked = "Peak calling is done by [MACS2](https://github.com/macs3-project/MACS), per sample."
    assert _rendered_length(linked) == len(plain)
    assert _rendered_length(plain) == len(plain)
    # A bare bracket pair is not a link and keeps its characters.
    assert _rendered_length("see [1] below") == len("see [1] below")
