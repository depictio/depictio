"""Icons and colours of a composed dashboard.

Nothing here knows a tool. A card's icon comes from the words of the column it
reads (``reads`` → counter, ``length`` → ruler, ``coverage`` → layers); a
section's colour from its place in its tab (the first takes the tab's, the
next ones cycle through a palette, tables stay gray); a card or a filter takes
its section's colour, so a tool's tiles read as one block.

Sections and tabs take Mantine colour names; card and filter accents take hex
(the card sets them as CSS), the Mantine shade-6 and shade-7 of the same name.

Every icon used here must reach the viewer's production icon subset, which is
built from the literals in viewer sources and shipped dashboards: the ones
below all appear there (``depictio/viewer/scripts/generate-icon-subset.mjs``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

# Mantine's default palette: shade 6 (icons, accents) and 7 (titles, on white).
SHADE_6 = {
    "gray": "#868e96",
    "red": "#fa5252",
    "pink": "#e64980",
    "grape": "#be4bdb",
    "violet": "#7950f2",
    "indigo": "#4c6ef5",
    "blue": "#228be6",
    "cyan": "#15aabf",
    "teal": "#12b886",
    "green": "#40c057",
    "lime": "#82c91e",
    "yellow": "#fab005",
    "orange": "#fd7e14",
}
SHADE_7 = {
    "gray": "#495057",
    "red": "#f03e3e",
    "pink": "#d6336c",
    "grape": "#ae3ec9",
    "violet": "#7048e8",
    "indigo": "#4263eb",
    "blue": "#1c7ed6",
    "cyan": "#1098ad",
    "teal": "#0ca678",
    "green": "#37b24d",
    "lime": "#74b816",
    "yellow": "#f59f00",
    "orange": "#f76707",
}
# Sections after a tab's first: hues apart from each other, none pale on white.
SECTION_CYCLE = ("indigo", "teal", "grape", "orange", "cyan", "pink", "blue", "violet", "green")

# Words of a column name → its card's icon. First match wins, so the more
# specific come first ("gc" before "percent": "GC content (%)" is about GC).
_ICON_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("sample", "samples"), "mdi:test-tube"),
    (("gc",), "mdi:dna"),
    (("pvalue", "padj", "qvalue", "fdr", "pval", "significance"), "mdi:target"),
    (("log2fc", "logfc", "fold", "fc", "delta", "diff", "change"), "mdi:delta"),
    (("pct", "percent", "percentage", "frac", "fraction", "ratio", "rate", "prop"), "mdi:percent"),
    (("coverage", "cov", "depth"), "mdi:layers-outline"),
    (("dup", "dups", "duplicate", "duplicates", "duplication"), "mdi:content-duplicate"),
    (("identity", "ani", "similarity", "match", "matches", "containment"), "mdi:fingerprint"),
    (("length", "len", "size", "bp", "kb", "mb", "width", "insert"), "mdi:ruler"),
    (("quality", "qual", "phred", "mapq", "q30", "q20"), "mdi:check-decagram"),
    (("score", "confidence", "probability", "prob"), "mdi:gauge"),
    (
        ("shannon", "simpson", "diversity", "evenness", "richness", "entropy", "chao1"),
        "mdi:chart-bell-curve",
    ),
    (
        ("species", "taxon", "taxa", "genus", "taxonomy", "otu", "asv", "bacteria", "rank"),
        "mdi:bacteria-outline",
    ),
    (("virus", "viral", "phage"), "mdi:virus"),
    (("protein", "peptide", "amino", "aa"), "mdi:molecule"),
    (
        ("gene", "genes", "transcript", "transcripts", "exon", "sequence", "seq", "contig", "orf"),
        "mdi:dna",
    ),
    (
        ("abundance", "expression", "tpm", "fpkm", "cpm", "rpkm", "intensity", "copy"),
        "mdi:chart-bar",
    ),
    (("read", "reads", "count", "counts", "num", "number", "total", "n"), "mdi:counter"),
    (
        ("error", "errors", "mismatch", "mismatches", "fail", "failed", "missing"),
        "mdi:alert-outline",
    ),
    (("time", "duration", "runtime", "seconds", "elapsed"), "mdi:clock-outline"),
    (("date", "year", "day", "month"), "mdi:calendar-outline"),
    (("mass", "weight"), "mdi:scale-balance"),
    (("temperature", "temp"), "mdi:thermometer"),
    (
        ("lat", "latitude", "lon", "longitude", "location", "site", "country"),
        "mdi:map-marker-outline",
    ),
)
_AGG_ICON = {
    "nunique": "mdi:shape-outline",
    "count": "mdi:counter",
    "sum": "mdi:sigma",
    "average": "mdi:chart-bell-curve",
    "median": "mdi:chart-bell-curve",
    "min": "mdi:chart-line",
    "max": "mdi:chart-line",
}
_FILTER_DEFAULT_ICON = "mdi:filter-variant"


def words(text: str) -> list[str]:
    """``shannon_entropy`` / ``readsMapped`` / ``GC content (%)`` → lower-case words."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    found = [w.lower() for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]
    if "%" in text:
        found.append("percent")
    return found


def icon_for(column: str | None, aggregation: str | None = None, default: str | None = None) -> str:
    """The icon of a card (or filter) reading ``column``."""
    said = set(words(column or ""))
    for vocabulary, icon in _ICON_RULES:
        if said & set(vocabulary):
            return icon
    return _AGG_ICON.get(aggregation or "", default or "mdi:chart-box-outline")


def hex6(color: str) -> str:
    return SHADE_6.get(color, SHADE_6["gray"])


def hex7(color: str) -> str:
    return SHADE_7.get(color, SHADE_7["gray"])


def section_colors(
    names: Iterable[str], tab_color: str, fixed: dict[str, str] | None = None
) -> dict[str, str]:
    """A colour per section: the tab's first, then hues apart from it.

    ``fixed`` keeps a section's own colour (a table section stays gray).
    """
    fixed = fixed or {}
    cycle = [c for c in SECTION_CYCLE if c != tab_color]
    colors: dict[str, str] = {}
    i = 0
    for name in names:
        if name in colors:
            continue
        if name in fixed:
            colors[name] = fixed[name]
        elif not colors or all(n in fixed for n in colors):
            colors[name] = tab_color
        else:
            colors[name] = cycle[i % len(cycle)]
            i += 1
    return colors


def style_card(component: dict[str, Any], color: str) -> None:
    component.setdefault(
        "icon_name", icon_for(component.get("column_name"), component.get("aggregation"))
    )
    component.setdefault("icon_color", hex6(color))
    component.setdefault("title_color", hex7(color))


def style_filter(component: dict[str, Any], color: str) -> None:
    component.setdefault(
        "icon_name", icon_for(component.get("column_name"), default=_FILTER_DEFAULT_ICON)
    )
    component.setdefault("custom_color", hex6(color))
    component.setdefault("title_size", "md")


def style_document(
    document: dict[str, Any], tab_color: str, card_colors: dict[str, str] | None = None
) -> None:
    """Colour one tab's sections, then its cards and filters by their section.

    ``card_colors``: a card's own colour by tag (the Overview's key metrics
    keep the colour of the stage they come from).
    """
    card_colors = card_colors or {}
    grid = document.get("grid_sections") or []
    fixed = {s["name"]: s["color"] for s in grid if s.get("icon") == "mdi:table"}
    colors = section_colors([s["name"] for s in grid], tab_color, fixed)
    for section in grid:
        section["color"] = colors.get(section["name"], section.get("color") or tab_color)
    for section in document.get("filter_sections") or []:
        if not section.get("persistent"):
            section["color"] = colors.get(section["name"], tab_color)
    filter_colors = {
        s["name"]: s.get("color") or tab_color for s in document.get("filter_sections") or []
    }
    for component in document.get("components") or []:
        section = component.get("section")
        kind = component.get("component_type")
        if kind == "card":
            color = card_colors.get(component.get("tag", ""), colors.get(section, tab_color))
            style_card(component, color)
        elif kind == "interactive":
            style_filter(component, filter_colors.get(section, colors.get(section, tab_color)))
