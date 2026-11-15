"""The kinds that are layout, not plotting: a record card, a ranked table, an allele grid.

Static HTML with inline styles, so a report keeps them whatever its theme; the
class names (``dpx-*``) are hooks the report's theme can restyle by.
"""

from __future__ import annotations

import re
from typing import Any

import polars as pl

from ..theme import GLASS_HUES, MANTINE_SHADES, resolve_primary
from . import NativeRenderer, NothingToDraw, Tile, esc, html_result, register, require

INK, DIMMED, FAINT, HAIR = "#212529", "#495057", "#868e96", "rgba(33,37,41,0.11)"
WELL = "rgba(33,37,41,0.06)"


def _rgba(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{a})"


def category_colors(values: list[Any], primary: str | None = None) -> dict[str, str]:
    """A stable colour per value: Paper's colorway, in the values' sorted order."""
    first, _ = resolve_primary(primary)
    hues = [first, *(MANTINE_SHADES[h][0] for h in GLASS_HUES if MANTINE_SHADES[h][0] != first)]
    keys = sorted({str(v) for v in values if v is not None}, key=_natural)
    return {k: hues[i % len(hues)] for i, k in enumerate(keys)}


def _natural(text: str) -> list[Any]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(text))]


def fmt(value: Any, decimals: int | None = None) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if decimals is not None:
            return f"{value:,.{decimals}f}"
        if value.is_integer() and abs(value) < 1e15:
            return f"{int(value):,}"
        return f"{value:,.4g}" if abs(value) < 1e6 else f"{value:,.0f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def badge(text: Any, color: str) -> str:
    return (
        f'<span class="dpx-badge" style="display:inline-block;padding:1px 9px;border-radius:999px;'
        f"font-size:11.5px;font-weight:600;line-height:18px;white-space:nowrap;"
        f'background:{_rgba(color, 0.12)};color:{color}">{esc(text)}</span>'
    )


# ---------------------------------------------------------------------------
# record_card
# ---------------------------------------------------------------------------

_SELECTION_SOURCES = ("scatter_selection", "table_selection", "jbrowse_selection")


def _record_selection(tile: Tile) -> dict[str, Any] | None:
    """``readRecordSelection``: the pick the card follows, if the state holds one."""
    cfg = tile.config
    linked = cfg.get("linked_component")
    source = str(cfg.get("selection_source") or "any")
    honoured = set(_SELECTION_SOURCES) if (linked or source == "any") else {source}
    found = []
    for f in tile.filters:
        if f.get("source") not in honoured:
            continue
        if linked and f.get("index") != linked:
            continue
        values = f.get("value")
        if not isinstance(values, list) or not values:
            continue
        meta = f.get("metadata") or {}
        found.append(
            {
                "column": f.get("column_name")
                or meta.get("selection_column")
                or meta.get("column_name"),
                "values": [str(v) for v in values],
                "own": bool(tile.dc_id) and str(meta.get("dc_id") or "") == tile.dc_id,
            }
        )
    if not found:
        return None
    return next((s for s in found if s["own"]), found[0])


def _description_group(description: str | None) -> str | None:
    """``descriptionGroup``: ``"Location: start of the gene"`` groups under Location."""
    if not description:
        return None
    at = description.find(":")
    if at <= 0 or at > 32 or not description[at + 1 :].strip():
        return None
    return description[:at].strip() or None


def _record_sections(
    tile: Tile, fields: list[str], descriptions: dict[str, str]
) -> list[tuple[str, list[str]]]:
    """``buildRecordSections``: the author's sections, else the columns grouped by
    their descriptions' ``Group:`` prefix, else one "Fields" section."""
    cfg = tile.config
    if isinstance(cfg.get("sections"), dict) and cfg["sections"]:
        return [(str(k), [str(c) for c in v]) for k, v in cfg["sections"].items()]
    groups: dict[str, list[str]] = {}
    for col in fields:
        groups.setdefault(_description_group(descriptions.get(col)) or "Fields", []).append(col)
    return list(groups.items())


def _record_card(tile: Tile) -> Any:
    cfg = tile.config
    id_col = str(cfg.get("id_col") or "id")
    title_col = cfg.get("title_col")
    labels = cfg.get("labels") or {}
    links = cfg.get("link_templates") or {}
    max_fields = int(cfg.get("max_fields") or 40)
    descriptions = {
        str(s.get("name")): str(s.get("description") or "") for s in tile.specs() if s.get("name")
    }
    if isinstance(cfg.get("sections"), dict) and cfg["sections"]:
        fields = list(dict.fromkeys(c for cols in cfg["sections"].values() for c in cols))
    else:
        fields = [c for c in descriptions if c]
    required = [id_col, title_col, *links, *fields]

    selection = _record_selection(tile)
    extra: list[dict[str, Any]] = []
    origin = "picked"
    if selection is None:
        target = cfg.get("default_record")
        by = cfg.get("default_record_by")
        if not target and by:
            best = tile.rows([id_col, by], roles={"id": id_col}, limit_rows=500_000)
            if best.height and by in best.columns:
                best = best.drop_nulls(by).sort(
                    by, descending=not cfg.get("default_record_ascending")
                )
                target = best[id_col][0] if best.height else None
        if target is None or target == "":
            return _record_empty(tile, required, fields, labels)
        origin = "default"
        extra = [
            {
                "index": f"{tile.component.index}::default",
                "column_name": id_col,
                "interactive_component_type": "MultiSelect",
                "value": [target],
                "metadata": {"dc_id": tile.dc_id, "column_name": id_col},
            }
        ]
    df = tile.rows(required, roles={"id": id_col}, limit_rows=200, extra_filters=extra)
    if selection and selection["own"] and selection["column"] in df.columns:
        df = df.filter(pl.col(selection["column"]).cast(pl.Utf8).is_in(selection["values"]))
    if origin == "default" and id_col in df.columns:
        df = df.filter(pl.col(id_col).cast(pl.Utf8) == str(extra[0]["value"][0]))
    if df.height == 0:
        return _record_empty(
            tile, required, fields, labels, note="The picked record is not in view."
        )
    record = df.row(0, named=True)
    heading = record.get(title_col) if title_col else None
    heading = heading if heading not in (None, "") else record.get(id_col)
    shown = 0
    blocks = []
    heading_cols = {id_col, title_col}
    available = [c for c in df.columns if c not in heading_cols or cfg.get("sections")]
    for name, cols in _record_sections(tile, available, descriptions):
        rows = []
        for col in cols:
            if col not in record or shown >= max_fields:
                continue
            shown += 1
            label = labels.get(col) or col
            value = record[col]
            if col in links and value not in (None, ""):
                url = str(links[col]).replace("{value}", str(value))
                cell = f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(fmt(value))}</a>'
            else:
                cell = esc(fmt(value))
            tip = descriptions.get(col)
            rows.append(
                f'<div style="display:contents"><div title="{esc(tip)}" style="color:{FAINT};'
                f'font-size:12px;padding:4px 0">{esc(label)}</div>'
                f'<div style="font-size:13px;padding:4px 0;color:{INK};'
                f'font-variant-numeric:tabular-nums;word-break:break-word">{cell}</div></div>'
            )
        if rows:
            blocks.append(
                f'<div style="margin:0 0 12px"><div style="font-size:11px;font-weight:600;'
                f"letter-spacing:.04em;text-transform:uppercase;color:{FAINT};margin:0 0 4px;"
                f'border-bottom:1px solid {HAIR};padding-bottom:4px">{esc(name)}</div>'
                '<div style="display:grid;grid-template-columns:minmax(8rem,max-content) 1fr;'
                f'column-gap:16px">{"".join(rows)}</div></div>'
            )
    echo = (
        "the default record"
        if origin == "default"
        else f"picked on {esc(selection['column']) if selection else 'another tile'}"
    )
    more = f" · {df.height} records match; the first is shown" if df.height > 1 else ""
    inner = (
        f'<div style="font-size:20px;font-weight:700;letter-spacing:-.01em;color:{INK};'
        f'margin:0 0 2px">{esc(fmt(heading))}</div>'
        f'<div style="font-size:12px;color:{FAINT};margin:0 0 12px">{echo}{more}</div>'
        + "".join(blocks)
    )
    return html_result(tile, inner, sub="One record, as the card shows it")


def _record_empty(
    tile: Tile,
    required: list[Any],
    fields: list[str],
    labels: dict[str, str],
    note: str | None = None,
) -> Any:
    """No record picked: the live card waits for a pick. A report has no picking, so
    it shows the records the card chooses from instead, and says so."""
    cfg = tile.config
    source = cfg.get("linked_component") or "a selecting tile"
    id_col = str(cfg.get("id_col") or "id")
    limit = 25
    df = tile.rows(required, roles={"id": id_col}, limit_rows=200)
    shown = [c for c in dict.fromkeys([cfg.get("title_col") or id_col, *fields]) if c in df.columns]
    lead = (
        f"{esc(note) + ' ' if note else ''}No record was picked when this was exported; in the "
        f"live dashboard the card shows the row picked in <b>{esc(source)}</b>."
    )
    if df.height == 0 or not shown:
        inner = (
            f'<div style="border:1px dashed {HAIR};border-radius:12px;padding:14px 16px;'
            f'color:{DIMMED};font-size:13px">{lead} No row is in view under the exported '
            "filters.</div>"
        )
        return html_result(tile, inner, sub="Waiting for a pick")
    head = "".join(
        f'<th style="text-align:left;font-size:11px;font-weight:600;color:{FAINT};'
        f'padding:4px 8px;border-bottom:1px solid {HAIR};white-space:nowrap">'
        f"{esc(labels.get(c) or c)}</th>"
        for c in shown
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td style="padding:4px 8px;border-bottom:1px solid {HAIR};font-size:12.5px;'
            f'font-variant-numeric:tabular-nums">{esc(fmt(row.get(c)))}</td>'
            for c in shown
        )
        + "</tr>"
        for row in df.head(limit).iter_rows(named=True)
    )
    more = f"; the first {limit} of {df.height}" if df.height > limit else ""
    inner = (
        f'<div style="font-size:12.5px;color:{DIMMED};margin:0 0 8px">{lead} The records it '
        f"picks from{more}:</div>"
        '<div style="overflow-x:auto;max-height:420px"><table class="dpx-plain" '
        f'style="border-collapse:collapse;width:100%"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )
    return html_result(tile, inner, sub="Waiting for a pick: the records in view")


register(
    NativeRenderer(
        kind="record_card",
        output="static",
        how="an HTML card of the record, from the row the export state picks",
        render=_record_card,
    )
)


# ---------------------------------------------------------------------------
# ranked_table
# ---------------------------------------------------------------------------

_MEDALS = ("#e3b341", "#adb5bd", "#cd7f32")


def _ranked_table(tile: Tile) -> Any:
    cfg = tile.config
    title_col = cfg.get("title_col")
    score_col = cfg.get("score_col")
    subtitle_col = cfg.get("subtitle_col")
    rank_col = cfg.get("rank_col")
    columns = [c for c in (cfg.get("columns") or []) if isinstance(c, dict) and c.get("column")]
    labels = cfg.get("labels") or {}
    popover = [c for c in (cfg.get("popover_columns") or []) if c]
    grid = [c for c in (cfg.get("popover_grid_columns") or []) if c]
    wanted = [
        title_col,
        score_col,
        subtitle_col,
        rank_col,
        *(c["column"] for c in columns),
        *popover,
        *grid,
    ]
    df = require(tile.rows(wanted, full_load=True), title_col)
    if rank_col and rank_col in df.columns:
        df = df.sort(rank_col, nulls_last=True)
    elif score_col and score_col in df.columns:
        df = df.sort(score_col, descending=bool(cfg.get("descending", True)), nulls_last=True)
    top = int(cfg.get("top_n") or 50)
    total = df.height
    df = df.head(top)
    palettes = {
        c["column"]: category_colors(df[c["column"]].to_list())
        for c in columns
        if c.get("display") == "badge" and c["column"] in df.columns
    }
    bounds: dict[str, tuple[float, float]] = {}
    for c in columns:
        col = c["column"]
        if c.get("display") == "bar" and col in df.columns:
            vals = [v for v in df[col].to_list() if isinstance(v, (int, float))]
            lo = c.get("min") if c.get("min") is not None else min([0.0, *vals])
            hi = c.get("max") if c.get("max") is not None else max([1.0, *vals])
            bounds[col] = (float(lo), float(hi) if hi > lo else float(lo) + 1)
    head_cells = "".join(
        f'<th style="text-align:left;font-size:11px;font-weight:600;color:{FAINT};'
        f'padding:6px 10px;border-bottom:1px solid {HAIR}">{esc(c.get("label") or labels.get(c["column"]) or c["column"])}</th>'
        for c in columns
    )
    body = []
    for i, row in enumerate(df.iter_rows(named=True)):
        rank = row.get(rank_col) if rank_col else i + 1
        medal_color = _MEDALS[i] if cfg.get("medals", True) and i < 3 else None
        medal = (
            '<span style="display:inline-flex;align-items:center;justify-content:center;'
            "width:24px;height:24px;border-radius:50%;font-size:11.5px;font-weight:700;"
            + (
                f'background:{medal_color};color:#fff">'
                if medal_color
                else f'background:{WELL};color:{DIMMED}">'
            )
            + f"{esc(fmt(rank))}</span>"
        )
        details = []
        if popover:
            details.append(
                " · ".join(
                    f"{esc(labels.get(c) or c)} {esc(fmt(row.get(c)))}" for c in popover if c in row
                )
            )
        if grid:
            details.append(
                " ".join(
                    f'<span style="background:{WELL};border-radius:6px;padding:0 6px">'
                    f"{esc(labels.get(c) or c)} <b>{esc(fmt(row.get(c)))}</b></span>"
                    for c in grid
                    if c in row
                )
            )
        sub = (
            f'<div style="font-size:12px;color:{FAINT}">{esc(fmt(row.get(subtitle_col)))}</div>'
            if subtitle_col
            else ""
        )
        extra = "".join(
            f'<div style="font-size:11.5px;color:{FAINT};margin-top:2px">{d}</div>'
            for d in details
            if d
        )
        cells = []
        for c in columns:
            col, display = c["column"], c.get("display") or "text"
            value = row.get(col)
            if display == "badge" and value not in (None, ""):
                inner = badge(value, palettes.get(col, {}).get(str(value), FAINT))
            elif display == "bar" and isinstance(value, (int, float)):
                lo, hi = bounds[col]
                pct = max(0.0, min(1.0, (float(value) - lo) / (hi - lo))) * 100
                primary, _ = resolve_primary(None)
                inner = (
                    '<div style="display:flex;align-items:center;gap:8px;min-width:120px">'
                    f'<div style="flex:1;height:6px;border-radius:3px;background:{WELL}">'
                    f'<div style="width:{pct:.1f}%;height:6px;border-radius:3px;'
                    f'background:{primary}"></div></div>'
                    f'<span style="font-variant-numeric:tabular-nums;font-size:12px">'
                    f"{esc(fmt(value, c.get('decimals')))}</span></div>"
                )
            else:
                inner = esc(fmt(value, c.get("decimals")))
            cells.append(
                f'<td style="padding:8px 10px;border-bottom:1px solid {HAIR}">{inner}</td>'
            )
        body.append(
            "<tr>"
            f'<td style="padding:8px 10px;border-bottom:1px solid {HAIR};width:34px">{medal}</td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid {HAIR}">'
            f'<div style="font-weight:650;color:{INK}">{esc(fmt(row.get(title_col)))}</div>'
            f"{sub}{extra}</td>" + "".join(cells) + "</tr>"
        )
    note = f"Top {df.height} of {total}" if total > df.height else f"{total} ranked"
    if cfg.get("family_dc_id"):
        note += "; each row's family opens in the live dashboard"
    inner = (
        '<table class="dpx-plain" style="width:100%;border-collapse:collapse;font-size:13px">'
        f'<thead><tr><th style="border-bottom:1px solid {HAIR}"></th>'
        f'<th style="text-align:left;font-size:11px;font-weight:600;color:{FAINT};'
        f'padding:6px 10px;border-bottom:1px solid {HAIR}">{esc(labels.get(title_col) or title_col)}</th>'
        f"{head_cells}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )
    return html_result(tile, inner, sub=note)


register(
    NativeRenderer(
        kind="ranked_table",
        output="static",
        how="an HTML table of the ranked rows, with the tile's medals, badges and bars",
        render=_ranked_table,
    )
)


# ---------------------------------------------------------------------------
# allele_grid
# ---------------------------------------------------------------------------


def _trim_allele(allele: Any, resolution: int | None) -> str:
    """``A*02:01:01:02`` at a resolution of 2 fields is ``A*02:01``."""
    text = "" if allele is None else str(allele)
    if not resolution or "*" not in text:
        return text
    gene, _, fields = text.partition("*")
    return f"{gene}*{':'.join(fields.split(':')[: int(resolution)])}"


def _allele_grid(tile: Tile) -> Any:
    cfg = tile.config
    sample_col = cfg.get("sample_id_col") or "sample_id"
    locus_col = cfg.get("locus_col") or "locus"
    allele_col = cfg.get("allele_col") or "allele"
    hap_col = cfg.get("haplotype_col")
    value_col = cfg.get("value_col")
    reads_col = cfg.get("reads_col")
    side = [s for s in (cfg.get("side_bars") or []) if s in ("value", "reads")]
    df = require(
        tile.rows(
            [
                sample_col,
                locus_col,
                allele_col,
                hap_col,
                value_col,
                reads_col,
                cfg.get("category_col"),
            ],
            full_load=True,
        ),
        sample_col,
        locus_col,
        allele_col,
    )
    resolution = cfg.get("resolution")
    df = df.with_columns(
        pl.col(allele_col).map_elements(lambda a: _trim_allele(a, resolution), return_dtype=pl.Utf8)
    )
    loci = cfg.get("locus_order") or list(dict.fromkeys(df[locus_col].cast(pl.Utf8).to_list()))
    loci = [str(x) for x in loci][: int(cfg.get("max_loci") or 24)]
    samples = list(dict.fromkeys(df[sample_col].cast(pl.Utf8).to_list()))
    if cfg.get("sample_order", "alphabetical") == "alphabetical":
        samples = sorted(samples, key=_natural)
    total = len(samples)
    samples = samples[: int(cfg.get("max_samples") or 200)]
    colors = {
        locus: category_colors(
            df.filter(pl.col(locus_col).cast(pl.Utf8) == locus)[allele_col].to_list()
        )
        for locus in loci
    }
    cells: dict[tuple[str, str], list[str]] = {}
    per_sample: dict[str, dict[str, float]] = {}
    for row in df.iter_rows(named=True):
        s, locus = str(row[sample_col]), str(row[locus_col])
        cells.setdefault((s, locus), []).append(
            (
                int(row[hap_col]) if hap_col and isinstance(row.get(hap_col), (int, float)) else 0,
                row[allele_col],
            )
        )
        agg = per_sample.setdefault(s, {})
        for key, col in (("value", value_col), ("reads", reads_col)):
            if col and isinstance(row.get(col), (int, float)):
                agg[key] = max(agg.get(key, float("-inf")), float(row[col]))
    maxima = {
        k: max([v.get(k, 0.0) for v in per_sample.values()] + [1e-9]) for k in ("value", "reads")
    }
    side_label = {
        "value": cfg.get("value_label") or value_col,
        "reads": cfg.get("reads_label") or reads_col,
    }
    head = "".join(
        f'<th style="font-size:11px;font-weight:600;color:{FAINT};padding:4px 6px;text-align:left">{esc(locus)}</th>'
        for locus in loci
    ) + "".join(
        f'<th style="font-size:11px;font-weight:600;color:{FAINT};padding:4px 6px;text-align:left">{esc(side_label[k])}</th>'
        for k in side
    )
    rows = []
    for s in samples:
        tds = []
        for locus in loci:
            alleles = [a for _, a in sorted(cells.get((s, locus), []), key=lambda t: t[0])]
            chips = "".join(
                f'<div style="background:{_rgba(colors[locus].get(str(a), FAINT), 0.16)};'
                f"border-inline-start:3px solid {colors[locus].get(str(a), FAINT)};"
                f'border-radius:4px;padding:0 5px;margin:1px 0;white-space:nowrap">'
                f"{esc(a) if cfg.get('show_labels', True) else '&nbsp;'}</div>"
                for a in alleles[:2]
            )
            tds.append(
                f'<td style="padding:2px 4px;font-size:11.5px;vertical-align:top">{chips or "—"}</td>'
            )
        for k in side:
            v = per_sample.get(s, {}).get(k)
            pct = 0 if v is None else max(0.0, min(1.0, v / maxima[k])) * 100
            tds.append(
                '<td style="padding:2px 6px;min-width:90px"><div style="display:flex;gap:6px;'
                f'align-items:center"><div style="flex:1;height:6px;border-radius:3px;background:{WELL}">'
                f'<div style="width:{pct:.1f}%;height:6px;border-radius:3px;background:{FAINT}"></div></div>'
                f'<span style="font-size:11px;color:{DIMMED}">{esc(fmt(v))}</span></div></td>'
            )
        rows.append(
            f'<tr style="border-bottom:1px solid {HAIR}"><td style="padding:2px 8px 2px 0;'
            f'font-size:12px;font-weight:600;white-space:nowrap">{esc(s)}</td>{"".join(tds)}</tr>'
        )
    if not rows:
        raise NothingToDraw("no sample in view")
    inner = (
        '<div style="overflow-x:auto"><table class="dpx-plain" style="border-collapse:collapse">'
        f"<thead><tr><th></th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )
    note = f"{len(samples)} of {total} samples" if total > len(samples) else f"{total} samples"
    return html_result(tile, inner, sub=f"{note} × {len(loci)} loci, both haplotypes per cell")


register(
    NativeRenderer(
        kind="allele_grid",
        output="static",
        how="an HTML grid of samples by loci, both haplotypes per cell",
        render=_allele_grid,
    )
)
