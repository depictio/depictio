"""Icons and colours of a composed dashboard, after the reference dashboards.

The seeded reference dashboards (iris, penguins, nf-core/ampliseq,
nf-core/viralrecon) set the rules this follows:

- a card's colour and icon say **what it measures**, not where it sits: the
  samples are teal with a flask on every tab, coverage is cyan, a percentage
  blue, taxa green. A section never shows the same colour twice, and a card
  nothing names takes the next free colour of the reference palette;
- a card's icon falls back on its secondary layout (a box plot's, a donut's);
- a tab's first section wears the tab's colour; the next ones change hue and
  take an icon from what they hold (a scatter, bars, a tree); tables stay
  gray; the hues start at a different place on each tab;
- filters are coloured by what they filter, like cards; their sections wear
  the tab's colour.

Nothing here knows a tool. Sections and tabs take Mantine colour names, cards
and filters hex (the card sets them as CSS).

Every icon used here must reach the viewer's production icon subset, built
from the literals in viewer sources and shipped dashboards only
(``depictio/viewer/scripts/generate-icon-subset.mjs``); a unit test checks it.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Iterable
from typing import Any

# The reference dashboards' card palette, in an order that keeps neighbours apart.
CARD_PALETTE = (
    "#1976D2",
    "#F68B33",
    "#9C27B0",
    "#2E7D32",
    "#E74C3C",
    "#00BCD4",
    "#3F51B5",
    "#8BC34A",
    "#FF9800",
    "#984EA3",
    "#E91E63",
    "#26A69A",
)
# Their filter palette (seaborn's, as iris and penguins use it).
FILTER_PALETTE = (
    "#4C72B0",
    "#DD8452",
    "#55A467",
    "#C44E52",
    "#8172B2",
    "#937860",
    "#DA8BC3",
    "#159090",
)
SAMPLE_COLOR = "#45B8AC"
# Sections after a tab's first: hues apart from each other, none pale on white.
SECTION_CYCLE = ("grape", "indigo", "cyan", "violet", "teal", "orange", "pink", "blue")

# What a column measures, by the words of its name → (icon, colour). First
# match wins, so the more specific come first ("gc" before "percent": "GC
# content (%)" is about GC).
_ENTITIES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("sample", "samples"), "mdi:flask", SAMPLE_COLOR),
    (("gc",), "mdi:dna", "#4CAF50"),
    (
        ("pvalue", "padj", "qvalue", "fdr", "pval", "significance", "significant"),
        "mdi:alert-circle",
        "#E74C3C",
    ),
    (
        ("log2fc", "logfc", "fold", "fc", "delta", "diff", "change"),
        "mdi:chart-line-variant",
        "#F68B33",
    ),
    (
        ("pct", "percent", "percentage", "frac", "fraction", "ratio", "rate", "prop"),
        "mdi:percent",
        "#1976D2",
    ),
    (("coverage", "cov", "depth"), "mdi:chart-areaspline", "#00BCD4"),
    (("dup", "dups", "duplicate", "duplicates", "duplication"), "mdi:content-duplicate", "#9C27B0"),
    (
        ("identity", "ani", "similarity", "match", "matches", "containment"),
        "mdi:fingerprint",
        "#3F51B5",
    ),
    (("length", "len", "size", "bp", "kb", "mb", "width", "insert"), "mdi:ruler", "#F68B33"),
    (("quality", "qual", "phred", "mapq", "q30", "q20"), "mdi:check-decagram", "#2E7D32"),
    (("score", "confidence", "probability", "prob"), "mdi:gauge", "#7B1FA2"),
    (
        ("shannon", "simpson", "diversity", "evenness", "richness", "entropy", "chao1"),
        "mdi:chart-bell-curve",
        "#F68B33",
    ),
    (
        (
            "species",
            "taxon",
            "taxa",
            "genus",
            "taxonomy",
            "otu",
            "asv",
            "bacteria",
            "rank",
            "phylum",
            "kingdom",
        ),
        "mdi:bacteria",
        "#8BC34A",
    ),
    (("virus", "viral", "phage", "lineage", "clade"), "mdi:virus", "#E74C3C"),
    (("protein", "peptide", "amino", "aa"), "mdi:molecule", "#4CAF50"),
    (
        ("gene", "genes", "transcript", "transcripts", "exon", "sequence", "seq", "contig", "orf"),
        "mdi:dna",
        "#4CAF50",
    ),
    (
        ("abundance", "expression", "tpm", "fpkm", "cpm", "rpkm", "intensity", "copy"),
        "mdi:chart-bar",
        "#FF9800",
    ),
    (("read", "reads", "count", "counts", "num", "number", "total", "n"), "mdi:counter", "#3F51B5"),
    (
        ("error", "errors", "mismatch", "mismatches", "fail", "failed", "missing"),
        "mdi:alert-outline",
        "#F68B33",
    ),
    (("strand", "orientation", "direction"), "mdi:arrow-left-right", "#1976D2"),
    (("start", "end", "stop", "position", "pos", "coord"), "mdi:map-marker", "#FF9800"),
    (("time", "duration", "runtime", "seconds", "elapsed"), "mdi:clock-outline", "#377EB8"),
    (("date", "year", "day", "month", "season"), "mdi:calendar-outline", "#00BCD4"),
    (("mass", "weight"), "mdi:scale-balance", "#FF9800"),
    (("temperature", "temp"), "mdi:thermometer", "#E74C3C"),
    (
        ("lat", "latitude", "lon", "longitude", "location", "site", "country", "island"),
        "mdi:map-marker-outline",
        "#984EA3",
    ),
    (("group", "groups", "condition", "treatment", "population", "cohort"), "mdi:earth", "#984EA3"),
)
# A card nothing names: the icon of how it shows its value.
_LAYOUT_ICON = {
    "box_plot": "mdi:chart-box-outline",
    "histogram": "mdi:chart-histogram",
    "grid": "mdi:grid-large",
    "compact": "mdi:chart-box-outline",
    "vertical": "mdi:chart-box-outline",
    "donut": "mdi:chart-donut",
    "composition": "mdi:chart-donut",
    "top_n": "mdi:chart-bar",
    "concentration": "mdi:format-list-group",
    "threshold": "mdi:check-decagram",
    "gauge": "mdi:gauge",
    "coverage": "mdi:counter",
    "uniqueness": "mdi:decimal",
    "completeness": "mdi:check-circle-outline",
    "trend": "mdi:chart-line",
}
_AGG_ICON = {"nunique": "mdi:shape-outline", "count": "mdi:counter", "sum": "mdi:sigma"}
_FILTER_DEFAULT_ICON = "mdi:filter-variant"
# A section's icon from what it holds: advanced visualisation kinds and figure
# types, by the words of their name.
_SECTION_ICONS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("sunburst", "donut", "pie", "composition"), "mdi:chart-donut"),
    (("tree", "phylogeny", "phylogenetic", "dendrogram"), "mdi:family-tree"),
    (("upset", "venn", "overlap", "set"), "mdi:set-merge"),
    (("sankey", "flow", "alluvial"), "mdi:relation-many-to-many"),
    (
        ("pca", "pcoa", "umap", "tsne", "ordination", "embedding", "clustering"),
        "mdi:chart-scatter-plot-hexbin",
    ),
    (("coverage", "track", "depth", "profile"), "mdi:chart-areaspline"),
    (("heatmap", "matrix", "dotplot", "dot"), "mdi:grid-large"),
    (("volcano", "manhattan", "ma", "scatter", "scatter_xy"), "mdi:chart-scatter-plot"),
    (("box", "violin", "strip"), "mdi:chart-box-outline"),
    (("histogram", "density", "distribution"), "mdi:chart-bell-curve"),
    (("line", "rarefaction", "curve", "trend"), "mdi:chart-line"),
    (("bar", "barplot", "stacked", "lollipop"), "mdi:chart-bar"),
)


def words(text: str) -> list[str]:
    """``shannon_entropy`` / ``readsMapped`` / ``GC content (%)`` → lower-case words."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    found = [w.lower() for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]
    if "%" in text:
        found.append("percent")
    return found


def entity(column: str | None) -> tuple[str, str] | None:
    """(icon, colour) of what ``column`` measures, when its words say."""
    said = set(words(column or ""))
    for vocabulary, icon, color in _ENTITIES:
        if said & set(vocabulary):
            return icon, color
    return None


def icon_for(
    column: str | None,
    aggregation: str | None = None,
    default: str | None = None,
    layout: str | None = None,
) -> str:
    """The icon of a card (or filter) reading ``column``."""
    found = entity(column)
    if found:
        return found[0]
    if layout in _LAYOUT_ICON:
        return _LAYOUT_ICON[layout]
    return _AGG_ICON.get(aggregation or "", default or "mdi:chart-box-outline")


def _stable(text: str, n: int) -> int:
    return zlib.crc32(text.encode()) % n


def _free(color: str, used: set[str], palette: tuple[str, ...], seed: str) -> str:
    """``color``, or the next palette colour this section has not used yet."""
    if color not in used:
        return color
    start = _stable(seed, len(palette))
    for i in range(len(palette)):
        candidate = palette[(start + i) % len(palette)]
        if candidate not in used:
            return candidate
    return color


def section_colors(
    names: Iterable[str], tab_color: str, fixed: dict[str, str] | None = None, seed: str = ""
) -> dict[str, str]:
    """A colour per section: the tab's first, then hues apart from it.

    ``fixed`` keeps a section's own colour (a table section stays gray);
    ``seed`` (the tab's title) sets where the hues start, so two tabs do not
    repeat one sequence.
    """
    fixed = fixed or {}
    cycle = [c for c in SECTION_CYCLE if c != tab_color]
    offset = _stable(seed, len(cycle)) if seed else 0
    colors: dict[str, str] = {}
    i = 0
    for name in names:
        if name in colors:
            continue
        if name in fixed:
            colors[name] = fixed[name]
        elif tab_color != "gray" and (not colors or all(n in fixed for n in colors)):
            # The first section wears the tab's colour; a gray tab (Other
            # data) has none to lend, so its sections start on the cycle.
            colors[name] = tab_color
        else:
            colors[name] = cycle[(offset + i) % len(cycle)]
            i += 1
    return colors


def section_icon(components: Iterable[dict[str, Any]], default: str) -> str:
    """A section's icon from what it holds: its first chart's kind, else cards or a table."""
    members = list(components)
    for component in members:
        kind = component.get("component_type")
        name = component.get("viz_kind") or component.get("visu_type") or ""
        if kind == "multiqc":
            return "mdi:chart-bar"
        if kind in ("advanced_viz", "figure") and name:
            said = set(words(str(name))) | {str(name).lower()}
            for vocabulary, icon in _SECTION_ICONS:
                if said & set(vocabulary):
                    return icon
    kinds = {c.get("component_type") for c in members}
    if kinds and kinds <= {"table"}:
        return "mdi:table"
    if "card" in kinds and not kinds & {"figure", "advanced_viz", "multiqc"}:
        return "mdi:counter"
    return default


def style_card(component: dict[str, Any], used: set[str]) -> None:
    found = entity(component.get("column_name"))
    seed = str(component.get("column_name") or component.get("title") or "")
    color = found[1] if found else CARD_PALETTE[_stable(seed, len(CARD_PALETTE))]
    color = _free(color, used, CARD_PALETTE, seed)
    used.add(color)
    component.setdefault(
        "icon_name",
        icon_for(
            component.get("column_name"),
            component.get("aggregation"),
            layout=component.get("secondary_layout"),
        ),
    )
    component.setdefault("icon_color", color)
    component.setdefault("title_color", color)


def style_filter(component: dict[str, Any], used: set[str]) -> None:
    found = entity(component.get("column_name"))
    seed = str(component.get("column_name") or component.get("title") or "")
    color = found[1] if found else FILTER_PALETTE[_stable(seed, len(FILTER_PALETTE))]
    color = _free(color, used, FILTER_PALETTE, seed)
    used.add(color)
    component.setdefault(
        "icon_name", icon_for(component.get("column_name"), default=_FILTER_DEFAULT_ICON)
    )
    component.setdefault("custom_color", color)
    component.setdefault("title_size", "md")


def style_document(
    document: dict[str, Any], tab_color: str, keep_icons: Iterable[str] = ()
) -> None:
    """Colour one tab: sections by place, cards and filters by what they measure.

    ``keep_icons``: sections whose icon is chosen by the caller (the
    Overview's), not from their content.
    """
    keep = set(keep_icons)
    components = document.get("components") or []
    grid = document.get("grid_sections") or []
    fixed = {s["name"]: s["color"] for s in grid if s.get("icon") == "mdi:table"}
    colors = section_colors(
        [s["name"] for s in grid], tab_color, fixed, seed=str(document.get("title", ""))
    )
    for section in grid:
        section["color"] = colors.get(section["name"], section.get("color") or tab_color)
        if section["name"] not in keep and section.get("icon") != "mdi:table":
            members = [
                c
                for c in components
                if c.get("section") == section["name"] and c.get("component_type") != "interactive"
            ]
            section["icon"] = section_icon(members, section.get("icon") or "mdi:chart-box-outline")
    for section in document.get("filter_sections") or []:
        if not section.get("persistent"):
            section["color"] = colors.get(section["name"], tab_color)
    used: dict[tuple[str, str | None], set[str]] = {}
    for component in components:
        kind = component.get("component_type")
        if kind == "card":
            style_card(component, used.setdefault(("card", component.get("section")), set()))
        elif kind == "interactive":
            style_filter(component, used.setdefault(("filter", component.get("section")), set()))
