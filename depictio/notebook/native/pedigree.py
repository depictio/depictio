"""Pedigrees as SVG: the standard drawing, from the individuals' rows.

Squares are males, circles females, diamonds a sex not recorded; a filled
symbol is affected, a gray one of unknown status, a slash marks the deceased.
Generations are read off the parent links (a founder who married into the
family sits beside their partner), couples are joined, and siblings hang from
one line under their parents.
"""

from __future__ import annotations

from typing import Any

from . import NativeRenderer, NothingToDraw, Tile, esc, html_result, register, require

INK, FAINT, LINE = "#212529", "#868e96", "#495057"
_MISSING = {"", "0", "none", "nan", "na", "."}


def _id(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return None if text.lower() in _MISSING else text


def _code(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        text = str(value or "").strip().lower()
        return {"male": 1, "m": 1, "female": 2, "f": 2, "affected": 2, "unaffected": 1}.get(text, 0)


def layout_family(
    people: list[dict[str, Any]],
) -> tuple[dict[str, tuple[int, int]], dict[str, int]]:
    """Each individual's (generation, slot), and the generations' widths."""
    ids = {p["id"] for p in people}
    by_id = {p["id"]: p for p in people}
    gen: dict[str, int] = {}

    def depth(i: str, seen: frozenset[str] = frozenset()) -> int:
        if i in gen:
            return gen[i]
        p = by_id[i]
        parents = [x for x in (p["father"], p["mother"]) if x in ids and x not in seen]
        gen[i] = 0 if not parents else 1 + max(depth(x, seen | {i}) for x in parents)
        return gen[i]

    for p in people:
        depth(p["id"])
    spouses: dict[str, list[str]] = {}
    for p in people:
        f, m = p["father"], p["mother"]
        if f in ids and m in ids:
            spouses.setdefault(f, []).append(m)
            spouses.setdefault(m, []).append(f)
    # A founder sits on their partner's generation, not above the family.
    for _ in range(3):
        for i, partners in spouses.items():
            if by_id[i]["father"] not in ids and by_id[i]["mother"] not in ids:
                gen[i] = max(gen[i], *(gen[s] for s in partners))
    order: dict[int, list[str]] = {}
    placed: set[str] = set()

    def place(g: int, i: str) -> None:
        if i in placed:
            return
        order.setdefault(g, []).append(i)
        placed.add(i)
        for s in dict.fromkeys(spouses.get(i, [])):
            if gen.get(s) == g and s not in placed:
                order[g].append(s)
                placed.add(s)

    for g in sorted(set(gen.values())):
        if g == 0:
            for p in people:
                if gen[p["id"]] == 0:
                    place(0, p["id"])
            continue
        prev = order.get(g - 1, [])
        kids = [
            p for p in people if gen[p["id"]] == g and (p["father"] in ids or p["mother"] in ids)
        ]

        def rank(p: dict[str, Any], prev: list[str] = prev) -> float:
            slots = [prev.index(x) for x in (p["father"], p["mother"]) if x in prev]
            return sum(slots) / len(slots) if slots else len(prev)

        for p in sorted(kids, key=rank):
            place(g, p["id"])
        for p in people:
            if gen[p["id"]] == g:
                place(g, p["id"])
    slots = {i: (g, idx) for g, members in order.items() for idx, i in enumerate(members)}
    return slots, {g: len(m) for g, m in order.items()}


def _symbol(x: float, y: float, sex: int, status: int, deceased: bool, r: float = 13) -> str:
    fill = INK if status == 2 else ("#ced4da" if status == 0 else "#ffffff")
    stroke = f'stroke="{INK}" stroke-width="1.5"'
    if sex == 1:
        shape = f'<rect x="{x - r}" y="{y - r}" width="{2 * r}" height="{2 * r}" fill="{fill}" {stroke}/>'
    elif sex == 2:
        shape = f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" {stroke}/>'
    else:
        shape = f'<path d="M{x} {y - r * 1.25} L{x + r * 1.25} {y} L{x} {y + r * 1.25} L{x - r * 1.25} {y} Z" fill="{fill}" {stroke}/>'
    if deceased:
        shape += f'<line x1="{x - r * 1.5}" y1="{y + r * 1.5}" x2="{x + r * 1.5}" y2="{y - r * 1.5}" stroke="{INK}" stroke-width="1.5"/>'
    return shape


def _pedigree(tile: Tile) -> Any:
    cfg = tile.config
    ind, fa, mo = cfg.get("individual_col"), cfg.get("father_col"), cfg.get("mother_col")
    sex_c, st_c, fam_c = cfg.get("sex_col"), cfg.get("status_col"), cfg.get("family_col")
    lab_c, dec_c = cfg.get("label_col"), cfg.get("deceased_col")
    df = require(
        tile.rows([fam_c, ind, fa, mo, sex_c, st_c, lab_c, dec_c, "note"], full_load=True), ind
    )
    df = df.head(int(cfg.get("max_individuals") or 300))
    families: dict[str, list[dict[str, Any]]] = {}
    for row in df.iter_rows(named=True):
        i = _id(row.get(ind))
        if not i:
            continue
        families.setdefault(str(row.get(fam_c) or "family"), []).append(
            {
                "id": i,
                "father": _id(row.get(fa)),
                "mother": _id(row.get(mo)),
                "sex": _code(row.get(sex_c)),
                "status": _code(row.get(st_c)),
                "deceased": _code(row.get(dec_c)) == 1 or str(row.get(dec_c)).lower() == "true",
                "label": row.get(lab_c) if lab_c else None,
                "note": row.get("note"),
            }
        )
    if not families:
        raise NothingToDraw("no individual in view")
    total = len(families)
    names = list(families)[: int(cfg.get("max_families") or 12)]
    dx, dy, pad = 64, 92, 26
    blocks = []
    for name in names:
        people = families[name]
        slots, widths = layout_family(people)
        width = max(widths.values()) * dx + 2 * pad
        height = (max(widths) + 1) * dy + 30
        xy = {}
        for i, (g, k) in slots.items():
            offset = (max(widths.values()) - widths[g]) * dx / 2
            xy[i] = (pad + offset + k * dx + dx / 2, 30 + g * dy + 14)
        lines = []
        sibships: dict[tuple[str | None, str | None], list[str]] = {}
        ids = {p["id"] for p in people}
        for p in people:
            f, m = (
                (p["father"] if p["father"] in ids else None),
                (p["mother"] if p["mother"] in ids else None),
            )
            if f or m:
                sibships.setdefault((f, m), []).append(p["id"])
        for (f, m), kids in sibships.items():
            parents = [xy[x] for x in (f, m) if x]
            if len(parents) == 2:
                (x1, y1), (x2, y2) = parents
                lines.append(
                    f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{LINE}" stroke-width="1.5"/>'
                )
            top_x = sum(x for x, _ in parents) / len(parents)
            top_y = parents[0][1]
            kid_xy = [xy[k] for k in kids]
            bar_y = min(y for _, y in kid_xy) - 34
            lines.append(
                f'<line x1="{top_x}" y1="{top_y}" x2="{top_x}" y2="{bar_y}" stroke="{LINE}" stroke-width="1.5"/>'
            )
            xs = [x for x, _ in kid_xy] + [top_x]
            lines.append(
                f'<line x1="{min(xs)}" y1="{bar_y}" x2="{max(xs)}" y2="{bar_y}" stroke="{LINE}" stroke-width="1.5"/>'
            )
            for x, y in kid_xy:
                lines.append(
                    f'<line x1="{x}" y1="{bar_y}" x2="{x}" y2="{y - 14}" stroke="{LINE}" stroke-width="1.5"/>'
                )
        marks = []
        for p in people:
            x, y = xy[p["id"]]
            tip = f"{p['id']}" + (f" · {p['note']}" if p.get("note") else "")
            label = p["label"] if p["label"] not in (None, "") else p["id"]
            text = (
                f'<text x="{x}" y="{y + 30}" font-size="10.5" fill="{FAINT}" text-anchor="middle">{esc(label)}</text>'
                if cfg.get("show_labels", True)
                else ""
            )
            marks.append(
                f"<g><title>{esc(tip)}</title>{_symbol(x, y, p['sex'], p['status'], p['deceased'])}{text}</g>"
            )
        svg = (
            f'<svg class="dpx-native" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}" style="max-width:100%;height:auto" role="img" '
            f'aria-label="Pedigree {esc(name)}">{"".join(lines)}{"".join(marks)}</svg>'
        )
        blocks.append(
            f'<div style="display:inline-block;vertical-align:top;margin:0 18px 12px 0">'
            f'<div style="font-size:12px;font-weight:600;color:{LINE}">{esc(name)}</div>{svg}</div>'
        )
    legend = (
        f'<div style="font-size:11px;color:{FAINT};margin-top:4px">■ male · ● female · ◆ sex not '
        "recorded · filled: affected · gray: status unknown · slash: deceased</div>"
    )
    sub = f"{len(names)} of {total} families" if total > len(names) else f"{total} families"
    return html_result(
        tile, '<div style="overflow-x:auto">' + "".join(blocks) + "</div>" + legend, sub=sub
    )


register(
    NativeRenderer(
        kind="pedigree",
        output="static",
        how="an SVG pedigree per family, from the parent links",
        render=_pedigree,
    )
)
