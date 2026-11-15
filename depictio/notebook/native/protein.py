"""Protein kinds: an alignment, a sequence track, secondary structure, domain lanes,
a profile HMM logo, a PAE matrix and a 3D structure.

Plotly for the tracks and matrices (hover and zoom), SVG for the logo (letters
scaled to their bits, which is drawing rather than plotting), py3Dmol for the
structure (rotate and zoom), with 3Dmol.js inlined once per document.
"""

from __future__ import annotations

import json
import math
from importlib import resources
from typing import Any

import polars as pl

from ..theme import paper_colorway
from . import (
    HTML_MIME,
    NativeRenderer,
    NativeResult,
    NothingToDraw,
    Tile,
    esc,
    figure_result,
    head_html,
    html_result,
    register,
    require,
)

# residueColours.ts: Clustal X classes and colours.
CLUSTAL = {
    "hydrophobic": (128, 160, 240),
    "positive": (240, 21, 5),
    "negative": (192, 72, 192),
    "polar": (21, 192, 21),
    "cysteine": (240, 128, 128),
    "glycine": (240, 144, 72),
    "proline": (192, 192, 0),
    "aromatic": (21, 164, 164),
}
CLUSTAL_CLASS = {
    **dict.fromkeys("AILMFWV", "hydrophobic"),
    **dict.fromkeys("KR", "positive"),
    **dict.fromkeys("ED", "negative"),
    **dict.fromkeys("NQST", "polar"),
    "C": "cysteine",
    "G": "glycine",
    "P": "proline",
    **dict.fromkeys("HY", "aromatic"),
}
# PLDDT_BANDS: AlphaFold's four confidence bands.
PLDDT_BANDS = (
    (90.0, (0, 83, 214), "Very high (> 90)"),
    (70.0, (101, 203, 243), "Confident (70–90)"),
    (50.0, (255, 219, 19), "Low (50–70)"),
    (-math.inf, (255, 125, 69), "Very low (< 50)"),
)
# SECONDARY_STRUCTURE_COLOURS, coil drawn as a gray line.
SS_COLOURS = {
    "helix": (255, 0, 128),
    "strand": (255, 200, 0),
    "turn": (96, 128, 255),
    "coil": (173, 181, 189),
}
SS_LABEL = {"helix": "Helix", "strand": "Strand", "turn": "Turn", "coil": "Coil"}


def rgb(c: tuple[int, int, int], a: float = 1.0) -> str:
    return f"rgba({c[0]},{c[1]},{c[2]},{a})" if a < 1 else f"rgb({c[0]},{c[1]},{c[2]})"


def residue_colour(letter: str) -> str | None:
    cls = CLUSTAL_CLASS.get(str(letter).upper())
    return rgb(CLUSTAL[cls]) if cls else None


def plddt_band(value: float, fractional: bool = False) -> tuple[tuple[int, int, int], str]:
    v = value * 100 if fractional else value
    for floor, colour, label in PLDDT_BANDS:
        if v > floor:
            return colour, label
    return PLDDT_BANDS[-1][1], PLDDT_BANDS[-1][2]


def ss_state(code: Any) -> str:
    """A DSSP / 3-state code as a state: H G I helix, E B strand, T S turn, else coil."""
    c = str(code or "").strip().upper()[:1]
    if c in ("H", "G", "I"):
        return "helix"
    if c in ("E", "B"):
        return "strand"
    if c in ("T", "S"):
        return "turn"
    return "coil"


def _entity(tile: Tile, df: pl.DataFrame, col: str | None) -> tuple[pl.DataFrame, str | None, int]:
    """The entity a protein tile opens on: the one the state's filters leave, else the first."""
    if not col or col not in df.columns or df.height == 0:
        return df, None, 1
    names = list(dict.fromkeys(str(v) for v in df[col].to_list() if v is not None))
    if not names:
        return df, None, 1
    return df.filter(pl.col(col).cast(pl.Utf8) == names[0]), names[0], len(names)


def _entity_note(entity: str | None, n: int) -> str:
    if not entity:
        return ""
    return f"{entity}" + (f" (1 of {n}; pick another in the live dashboard)" if n > 1 else "")


# ---------------------------------------------------------------------------
# msa
# ---------------------------------------------------------------------------


def _msa(tile: Tile) -> Any:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    cfg = tile.config
    id_col, seq_col = cfg.get("seq_id_col"), cfg.get("sequence_col")
    rank_col, ident_col, msa_col = (
        cfg.get("rank_col"),
        cfg.get("identity_col"),
        cfg.get("msa_id_col"),
    )
    df = require(
        tile.rows([msa_col, id_col, seq_col, rank_col, ident_col], full_load=True), seq_col
    )
    df, msa, n_msa = _entity(tile, df, msa_col)
    sort_by = str(cfg.get("sort_by") or "rank")
    key = rank_col if sort_by == "rank" else ident_col if sort_by == "identity" else None
    if key and key in df.columns:
        df = df.sort(key, descending=(sort_by == "identity"), nulls_last=True)
    total = df.height
    df = df.head(int(cfg.get("max_rows") or 150))
    seqs = [str(s or "") for s in df[seq_col].to_list()]
    names = [str(n) for n in (df[id_col].to_list() if id_col in df.columns else range(len(seqs)))]
    width = max(len(s) for s in seqs)
    classes = list(CLUSTAL)
    z, text = [], []
    for s in seqs:
        z.append(
            [
                classes.index(CLUSTAL_CLASS[c.upper()]) if c.upper() in CLUSTAL_CLASS else None
                for c in s.ljust(width, "-")
            ]
        )
        text.append(list(s.ljust(width, "-")))
    n = len(classes)
    scale = []
    for i, cls in enumerate(classes):
        scale += [[i / n, rgb(CLUSTAL[cls])], [(i + 1) / n, rgb(CLUSTAL[cls])]]
    # Conservation: the consensus residue's share of the non-gap residues per column.
    cons, frac = [], []
    for j in range(width):
        col = [s[j].upper() for s in seqs if j < len(s) and s[j] not in "-."]
        if not col:
            cons.append("-")
            frac.append(0.0)
            continue
        best = max(set(col), key=col.count)
        cons.append(best)
        frac.append(col.count(best) / len(col))
    rows = 2 if cfg.get("show_conservation", True) else 1
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.12, 0.88] if rows == 2 else [1.0],
        vertical_spacing=0.02,
    )
    if rows == 2:
        fig.add_trace(
            go.Bar(
                x=list(range(1, width + 1)),
                y=frac,
                marker_color=[residue_colour(c) or "#adb5bd" for c in cons],
                hovertext=[
                    f"column {j + 1}: {c} in {f:.0%}"
                    for j, (c, f) in enumerate(zip(cons, frac, strict=True))
                ],
                hoverinfo="text",
                showlegend=False,
            ),
            row=1,
            col=1,
        )
        fig.update_yaxes(range=[0, 1], showticklabels=False, showgrid=False, row=1, col=1)
    dense = width * len(seqs) <= 12000
    fig.add_trace(
        go.Heatmap(
            z=z,
            x=list(range(1, width + 1)),
            y=names,
            colorscale=scale,
            zmin=0,
            zmax=n,
            showscale=False,
            text=text,
            texttemplate="%{text}" if dense else None,
            textfont={"size": 8, "color": "#212529"},
            xgap=0,
            ygap=1,
            hovertemplate="%{y} · column %{x}: %{text}<extra></extra>",
        ),
        row=rows,
        col=1,
    )
    fig.update_yaxes(autorange="reversed", showgrid=False, row=rows, col=1)
    fig.update_xaxes(showgrid=False, title_text="Alignment column", row=rows, col=1)
    fig.update_layout(height=min(900, 120 + 14 * len(seqs)), bargap=0)
    sub = f"{len(seqs)} of {total} sequences" if total > len(seqs) else f"{total} sequences"
    sub += f" × {width} columns, Clustal colours"
    if msa:
        sub = f"{_entity_note(msa, n_msa)} · " + sub
    return figure_result(tile, fig, sub=sub)


register(
    NativeRenderer(
        kind="msa",
        output="interactive",
        how="a Plotly heatmap of the alignment in Clustal colours, with its conservation",
        render=_msa,
    )
)


# ---------------------------------------------------------------------------
# sequence_track
# ---------------------------------------------------------------------------


def _sequence_track(tile: Tile) -> Any:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    cfg = tile.config
    ent, pos, res = cfg.get("entity_col"), cfg.get("position_col"), cfg.get("residue_col")
    val, cat = cfg.get("value_col"), cfg.get("category_col")
    df = require(
        tile.rows([ent, pos, res, val, cat], viz_kind="sequence_track", full_load=True), pos
    )
    df, entity, n_ent = _entity(tile, df, ent)
    df = df.sort(pos)
    positions = df[pos].cast(pl.Int64).to_list()
    residues = (
        [str(r) for r in df[res].to_list()] if res and res in df.columns else [""] * df.height
    )
    lanes: list[str] = []
    if val and val in df.columns:
        lanes.append("value")
    if cat and cat in df.columns:
        lanes.append("category")
    domains = variants = None
    if cfg.get("domains_dc_id"):
        dcols = [
            ent,
            cfg.get("domain_start_col"),
            cfg.get("domain_end_col"),
            cfg.get("domain_label_col"),
            "source",
        ]
        try:
            domains = tile.rows(
                dcols,
                dc_id=str(cfg["domains_dc_id"]),
                wf_id=cfg.get("domains_wf_id"),
                full_load=True,
            )
            if entity and ent in domains.columns:
                domains = domains.filter(pl.col(ent).cast(pl.Utf8) == entity)
            lanes.append("domains")
        except Exception:  # noqa: BLE001 - a lane that cannot be read costs that lane
            domains = None
    if cfg.get("variants_dc_id"):
        vcols = [
            ent,
            cfg.get("variant_position_col"),
            cfg.get("variant_label_col"),
            cfg.get("variant_category_col"),
        ]
        try:
            variants = tile.rows(
                vcols,
                dc_id=str(cfg["variants_dc_id"]),
                wf_id=cfg.get("variants_wf_id"),
                full_load=True,
            )
            if entity and ent in variants.columns:
                variants = variants.filter(pl.col(ent).cast(pl.Utf8) == entity)
            lanes.append("variants")
        except Exception:  # noqa: BLE001
            variants = None
    if not lanes:
        raise NothingToDraw("no track bound")
    heights = {"value": 0.45, "category": 0.12, "domains": 0.18, "variants": 0.25}
    fig = make_subplots(
        rows=len(lanes),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[heights[x] for x in lanes],
    )
    for r, lane in enumerate(lanes, start=1):
        if lane == "value":
            vals = df[val].cast(pl.Float64).to_list()
            frac = all(v is None or v <= 1 for v in vals)
            plddt = (
                "plddt" in str(val).lower() or "plddt" in str(cfg.get("value_label") or "").lower()
            )
            colours = [
                rgb(plddt_band(v, frac)[0]) if plddt and v is not None else paper_colorway()[0]
                for v in vals
            ]
            fig.add_trace(
                go.Bar(
                    x=positions,
                    y=vals,
                    marker_color=colours,
                    marker_line_width=0,
                    hovertext=[
                        f"{r_}{p} · {cfg.get('value_label') or val} {v}"
                        for r_, p, v in zip(residues, positions, vals, strict=True)
                    ],
                    hoverinfo="text",
                    showlegend=False,
                ),
                row=r,
                col=1,
            )
            fig.update_yaxes(title_text=cfg.get("value_label") or val, row=r, col=1)
        elif lane == "category":
            states = [ss_state(c) for c in df[cat].to_list()]
            for state in ("helix", "strand", "turn", "coil"):
                xs = [p for p, s in zip(positions, states, strict=True) if s == state]
                if xs:
                    fig.add_trace(
                        go.Bar(
                            x=xs,
                            y=[1] * len(xs),
                            marker_color=rgb(SS_COLOURS[state]),
                            marker_line_width=0,
                            name=SS_LABEL[state],
                            hovertext=[f"{p}: {SS_LABEL[state]}" for p in xs],
                            hoverinfo="text",
                        ),
                        row=r,
                        col=1,
                    )
            fig.update_yaxes(showticklabels=False, showgrid=False, title_text=cat, row=r, col=1)
        elif lane == "domains" and domains is not None:
            s_, e_, l_ = (
                cfg.get("domain_start_col"),
                cfg.get("domain_end_col"),
                cfg.get("domain_label_col"),
            )
            colours = (
                {
                    k: c
                    for k, c in zip(
                        sorted({str(x) for x in domains[l_].to_list()}), paper_colorway()[1:] * 4
                    )
                }
                if l_ in domains.columns
                else {}
            )
            for row in domains.iter_rows(named=True):
                a, b = float(row[s_]), float(row[e_])
                c = colours.get(str(row.get(l_)), paper_colorway()[1])
                fig.add_trace(
                    go.Bar(
                        x=[(a + b) / 2],
                        y=[1],
                        width=[b - a + 1],
                        marker_color=c,
                        opacity=0.8,
                        text=[row.get(l_)],
                        textposition="inside",
                        insidetextanchor="middle",
                        hovertext=f"{row.get(l_)}: {int(a)}–{int(b)}",
                        hoverinfo="text",
                        showlegend=False,
                    ),
                    row=r,
                    col=1,
                )
            fig.update_yaxes(
                showticklabels=False, showgrid=False, title_text="Domains", row=r, col=1
            )
        elif lane == "variants" and variants is not None:
            vp, vl, vc = (
                cfg.get("variant_position_col"),
                cfg.get("variant_label_col"),
                cfg.get("variant_category_col"),
            )
            from .layout import category_colors

            colours = category_colors(variants[vc].to_list()) if vc in variants.columns else {}
            for row in variants.iter_rows(named=True):
                c = colours.get(str(row.get(vc)), paper_colorway()[0])
                fig.add_trace(
                    go.Scatter(
                        x=[row[vp], row[vp]],
                        y=[0, 1],
                        mode="lines+markers",
                        line={"color": c, "width": 1.5},
                        marker={"size": [0, 9], "color": c},
                        hovertext=f"{row.get(vl)} ({row.get(vc)})",
                        hoverinfo="text",
                        showlegend=False,
                    ),
                    row=r,
                    col=1,
                )
            fig.update_yaxes(
                showticklabels=False,
                showgrid=False,
                range=[0, 1.3],
                title_text="Variants",
                row=r,
                col=1,
            )
    fig.update_xaxes(range=[min(positions) - 0.5, max(positions) + 0.5])
    fig.update_xaxes(title_text="Residue", row=len(lanes), col=1)
    fig.update_layout(barmode="overlay", bargap=0, height=180 + 70 * len(lanes))
    return figure_result(
        tile, fig, sub=f"{_entity_note(entity, n_ent)} · {len(positions)} residues".strip(" ·")
    )


register(
    NativeRenderer(
        kind="sequence_track",
        output="interactive",
        how="Plotly tracks along the sequence: confidence, structure, domains, variants",
        render=_sequence_track,
    )
)


# ---------------------------------------------------------------------------
# secondary_structure
# ---------------------------------------------------------------------------


def _secondary_structure(tile: Tile) -> Any:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    cfg = tile.config
    ent, pos, state = cfg.get("entity_col"), cfg.get("position_col"), cfg.get("state_col")
    src = cfg.get("source_col")
    probs = [cfg.get("p_helix_col"), cfg.get("p_strand_col"), cfg.get("p_coil_col")]
    df = require(
        tile.rows(
            [ent, pos, state, src, *probs, cfg.get("confidence_col"), cfg.get("residue_col")],
            full_load=True,
        ),
        pos,
        state,
    )
    df, entity, n_ent = _entity(tile, df, ent)
    sources = (
        list(dict.fromkeys(str(s) for s in df[src].to_list()))
        if src and src in df.columns
        else ["states"]
    )
    ref = cfg.get("reference_source") if cfg.get("reference_source") in sources else sources[0]
    has_probs = cfg.get("show_probabilities", True) and all(p and p in df.columns for p in probs)
    lanes = (
        len(sources)
        + (1 if has_probs else 0)
        + (1 if cfg.get("show_agreement", True) and len(sources) > 1 else 0)
    )
    fig = make_subplots(
        rows=lanes,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[
            (0.4 if has_probs and i == 0 else 0.6 / max(1, lanes - 1)) for i in range(lanes)
        ],
    )
    r = 1
    by_source = {
        s: (
            df
            if src is None or src not in df.columns
            else df.filter(pl.col(src).cast(pl.Utf8) == s)
        ).sort(pos)
        for s in sources
    }
    if has_probs:
        part = by_source[ref]
        x = part[pos].to_list()
        for col, name, state_key in zip(
            probs, ("Helix", "Strand", "Coil"), ("helix", "strand", "coil"), strict=True
        ):
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=part[col].cast(pl.Float64).to_list(),
                    mode="lines",
                    stackgroup="p",
                    line={"width": 0, "shape": "hv"},
                    fillcolor=rgb(SS_COLOURS[state_key], 0.75),
                    name=f"P({name})",
                    hovertemplate=f"%{{x}}: P({name}) %{{y:.2f}}<extra></extra>",
                ),
                row=r,
                col=1,
            )
        fig.update_yaxes(range=[0, 1], title_text=f"{ref} prob.", row=r, col=1)
        r += 1
    seen: set[str] = set()
    composition = []
    for s in sources:
        part = by_source[s]
        states = [ss_state(c) for c in part[state].to_list()]
        xs_all = part[pos].to_list()
        counts = {k: states.count(k) for k in ("helix", "strand", "turn", "coil")}
        composition.append(
            f"{s}: "
            + ", ".join(
                f"{SS_LABEL[k].lower()} {v / max(1, len(states)):.0%}"
                for k, v in counts.items()
                if v
            )
        )
        for k in ("helix", "strand", "turn", "coil"):
            xs = [x for x, st in zip(xs_all, states, strict=True) if st == k]
            if not xs:
                continue
            fig.add_trace(
                go.Bar(
                    x=xs,
                    y=[1 if k != "coil" else 0.3] * len(xs),
                    base=[0 if k != "coil" else 0.35] * len(xs),
                    marker_color=rgb(SS_COLOURS[k]),
                    marker_line_width=0,
                    name=SS_LABEL[k],
                    legendgroup=k,
                    showlegend=k not in seen,
                    hovertext=[f"{s} · {x}: {SS_LABEL[k]}" for x in xs],
                    hoverinfo="text",
                ),
                row=r,
                col=1,
            )
            seen.add(k)
        fig.update_yaxes(showticklabels=False, showgrid=False, title_text=s, row=r, col=1)
        r += 1
    if r <= lanes:
        a, b = (by_source[sources[0]], by_source[sources[1]])
        sa = dict(zip(a[pos].to_list(), (ss_state(c) for c in a[state].to_list()), strict=True))
        sb = dict(zip(b[pos].to_list(), (ss_state(c) for c in b[state].to_list()), strict=True))
        xs = sorted(set(sa) & set(sb))
        agree = [sa[x] == sb[x] for x in xs]
        fig.add_trace(
            go.Bar(
                x=xs,
                y=[1] * len(xs),
                marker_color=["#ced4da" if g else "#fa5252" for g in agree],
                marker_line_width=0,
                hovertext=[
                    f"{x}: {'agree' if g else f'{sa[x]} vs {sb[x]}'}"
                    for x, g in zip(xs, agree, strict=True)
                ],
                hoverinfo="text",
                showlegend=False,
            ),
            row=r,
            col=1,
        )
        fig.update_yaxes(showticklabels=False, showgrid=False, title_text="Agreement", row=r, col=1)
        composition.append(f"agreement {sum(agree) / max(1, len(agree)):.0%}")
    fig.update_xaxes(title_text="Residue", row=lanes, col=1)
    fig.update_layout(barmode="overlay", bargap=0, height=170 + 80 * lanes)
    sub = "; ".join(x for x in [_entity_note(entity, n_ent), *composition] if x)
    return figure_result(tile, fig, sub=sub)


register(
    NativeRenderer(
        kind="secondary_structure",
        output="interactive",
        how="Plotly state strips per source, the reference's probabilities and their agreement",
        render=_secondary_structure,
    )
)


# ---------------------------------------------------------------------------
# domain_architecture
# ---------------------------------------------------------------------------


def _domain_architecture(tile: Tile) -> Any:
    import plotly.graph_objects as go

    from .layout import category_colors

    cfg = tile.config
    ent, st, en, lab = (
        cfg.get("entity_col"),
        cfg.get("start_col"),
        cfg.get("end_col"),
        cfg.get("label_col"),
    )
    plen, ev, srcc = cfg.get("protein_length_col"), cfg.get("evalue_col"), cfg.get("source_col")
    df = require(
        tile.rows([ent, st, en, lab, plen, ev, srcc, cfg.get("description_col")], full_load=True),
        ent,
        st,
        en,
    )
    if cfg.get("evalue_threshold") is not None and ev in df.columns:
        df = df.filter(pl.col(ev).cast(pl.Float64) <= float(cfg["evalue_threshold"]))
    if cfg.get("sources") and srcc in df.columns:
        df = df.filter(pl.col(srcc).cast(pl.Utf8).is_in([str(s) for s in cfg["sources"]]))
    if df.height == 0:
        raise NothingToDraw("no domain under the thresholds")
    df = df.sort([ent, st])
    colour_key = lab if str(cfg.get("color_by") or "label") == "label" else (srcc or lab)
    colours = category_colors(df[colour_key].to_list()) if colour_key in df.columns else {}
    proteins: list[tuple[str, float, list[dict[str, Any]]]] = []
    from .layout import _natural

    for (name,), g in sorted(
        df.group_by(ent, maintain_order=True), key=lambda kv: _natural(str(kv[0][0]))
    ):
        rows = list(g.iter_rows(named=True))
        length = max(
            [float(r[plen]) for r in rows if plen and r.get(plen) is not None]
            + [max(float(r[en]) for r in rows)]
        )
        proteins.append((str(name), length, rows))
    view = str(cfg.get("view") or "proteins")
    lanes: list[tuple[str, float, list[dict[str, Any]]]]
    if view == "architectures":
        arch: dict[str, list[tuple[str, float, list[dict[str, Any]]]]] = {}
        for p in proteins:
            arch.setdefault(" – ".join(str(r.get(lab)) for r in p[2]), []).append(p)
        ranked = sorted(arch.items(), key=lambda kv: -len(kv[1]))[
            : int(cfg.get("max_architectures") or 15)
        ]
        lanes = [(f"{key} ({len(ps)})", ps[0][1], ps[0][2]) for key, ps in ranked]
        sub = f"{len(arch)} architectures across {len(proteins)} proteins; each lane is its first protein"
    else:
        lanes = proteins[: min(int(cfg.get("max_proteins") or 2000), 60)]
        sub = (
            f"{len(lanes)} of {len(proteins)} proteins"
            if len(proteins) > len(lanes)
            else f"{len(proteins)} proteins"
        )
    fig = go.Figure()
    seen: set[str] = set()
    for y, (name, length, rows) in enumerate(lanes):
        # The backbone as a thin bar, so the domains (bars too) sit on top of it.
        fig.add_trace(
            go.Bar(
                x=[length],
                base=[1],
                y=[y],
                orientation="h",
                width=0.1,
                marker={"color": "#adb5bd", "line": {"width": 0}},
                hovertext=f"{name}: {int(length)} aa",
                hoverinfo="text",
                showlegend=False,
            )
        )
        for r in rows:
            key = str(r.get(colour_key))
            c = colours.get(key, paper_colorway()[0])
            a, b = float(r[st]), float(r[en])
            extra = f"<br>E-value {r[ev]:.2g}" if ev and isinstance(r.get(ev), (int, float)) else ""
            fig.add_trace(
                go.Bar(
                    x=[b - a + 1],
                    base=[a],
                    y=[y],
                    orientation="h",
                    width=0.55,
                    marker={"color": c, "line": {"width": 0}},
                    text=[r.get(lab)],
                    textposition="inside",
                    insidetextanchor="middle",
                    textfont={"color": "#fff", "size": 10},
                    name=key,
                    legendgroup=key,
                    showlegend=key not in seen,
                    hovertext=f"<b>{r.get(lab)}</b> {int(a)}–{int(b)}{extra}",
                    hoverinfo="text",
                )
            )
            seen.add(key)
    fig.update_yaxes(
        tickvals=list(range(len(lanes))),
        ticktext=[n for n, _, _ in lanes],
        autorange="reversed",
        showgrid=False,
    )
    fig.update_xaxes(title_text="Residue", rangemode="tozero")
    fig.update_layout(
        barmode="overlay", height=max(220, 110 + 34 * len(lanes)), showlegend=len(colours) <= 20
    )
    return figure_result(tile, fig, sub=sub)


register(
    NativeRenderer(
        kind="domain_architecture",
        output="interactive",
        how="Plotly domain lanes per protein (or per architecture)",
        render=_domain_architecture,
    )
)


# ---------------------------------------------------------------------------
# hmm_logo (SVG)
# ---------------------------------------------------------------------------


def _background() -> dict[str, float]:
    try:
        from depictio.recipes.lib.hmm import BACKGROUND_AMINO

        return dict(BACKGROUND_AMINO)
    except Exception:  # noqa: BLE001 - the same table, kept here for a lean install
        return {
            "A": 0.0787945,
            "C": 0.01516,
            "D": 0.0535222,
            "E": 0.0668298,
            "F": 0.0397062,
            "G": 0.0695071,
            "H": 0.0229198,
            "I": 0.0590092,
            "K": 0.0594422,
            "L": 0.0963728,
            "M": 0.0237718,
            "N": 0.0414386,
            "P": 0.0482904,
            "Q": 0.0395639,
            "R": 0.0540978,
            "S": 0.0683364,
            "T": 0.0540687,
            "V": 0.0673417,
            "W": 0.0114135,
            "Y": 0.0304133,
        }


def column_heights(emissions: dict[str, float], mode: str) -> tuple[dict[str, float], float]:
    """``logo/heights.ts`` (HMMER's hmmlogo): letter heights and the stack height."""
    letters = list(emissions)
    nucleic = all(x.upper() in "ACGTU" for x in letters)
    bg_table = _background()
    bg = {a: (0.25 if nucleic else bg_table.get(a.upper(), 0.0)) for a in letters}
    p = {a: max(0.0, float(v or 0.0)) for a, v in emissions.items()}
    if mode == "probability":
        return p, sum(p.values())
    lo = {a: math.log2(p[a] / bg[a]) for a in letters if p[a] > 0 and bg[a] > 0}
    re_k = sum(p[a] * lo[a] for a in lo)
    if mode == "relent_all":
        return {a: re_k * p[a] for a in letters}, re_k
    above = sum(p[a] for a in lo if lo[a] > 0)
    return {
        a: (re_k * p[a] / above if a in lo and lo[a] > 0 and above > 0 else 0.0) for a in letters
    }, re_k


def _hmm_logo(tile: Tile) -> Any:
    cfg = tile.config
    model_col, state_col = cfg.get("model_col"), cfg.get("state_col")
    letter_col, emis_col = cfg.get("letter_col"), cfg.get("emission_col")
    ins, occ, cons = cfg.get("insert_prob_col"), cfg.get("occupancy_col"), cfg.get("consensus_col")
    df = require(
        tile.rows(
            [
                cfg.get("entity_col"),
                model_col,
                state_col,
                letter_col,
                emis_col,
                ins,
                occ,
                cons,
                cfg.get("insert_length_col"),
            ],
            full_load=True,
        ),
        state_col,
        letter_col,
        emis_col,
    )
    mode = str(cfg.get("height_mode") or "relent_abovebg")
    models = (
        list(dict.fromkeys(str(m) for m in df[model_col].to_list()))
        if model_col and model_col in df.columns
        else [""]
    )
    blocks = []
    col_w, height = 16, 120
    for model in models[:4]:
        part = df if not model else df.filter(pl.col(model_col).cast(pl.Utf8) == model)
        states = sorted({int(s) for s in part[state_col].to_list() if s is not None})
        by_state: dict[int, dict[str, float]] = {}
        meta: dict[int, dict[str, Any]] = {}
        for row in part.iter_rows(named=True):
            k = int(row[state_col])
            by_state.setdefault(k, {})[str(row[letter_col])] = float(row[emis_col] or 0.0)
            meta.setdefault(k, row)
        cols = {k: column_heights(by_state[k], mode) for k in states}
        top = max([info for _, info in cols.values()] + [1.0])
        unit = height / (4.32 if mode != "probability" and top <= 4.32 else top)
        w = len(states) * col_w
        parts = []
        for i, k in enumerate(states):
            heights, info = cols[k]
            y = height
            for letter, h in sorted(heights.items(), key=lambda kv: kv[1]):
                px = h * unit
                if px < 0.6:
                    continue
                colour = residue_colour(letter) or "#495057"
                # textLength fills the column; the vertical scale makes a capital's
                # height (0.72 em in a bold sans) equal to the letter's bits.
                parts.append(
                    f'<text x="0" y="0" font-size="20" font-weight="700" font-family="Arial,Helvetica,sans-serif" '
                    f'fill="{colour}" textLength="{col_w - 1}" lengthAdjust="spacingAndGlyphs" '
                    f'transform="translate({i * col_w + 0.5:.1f},{y:.2f}) scale(1,{px / 14.4:.4f})">'
                    f"<title>state {k}: {esc(letter)} {heights[letter]:.2f} bits</title>{esc(letter)}</text>"
                )
                y -= px
            if (i + 1) % 10 == 0 or i == 0:
                parts.append(
                    f'<text x="{i * col_w + col_w / 2:.1f}" y="{height + 12}" font-size="9" fill="#868e96" text-anchor="middle">{k}</text>'
                )
        rows_y = height + 18
        extra = []
        if cfg.get("show_indel_rows", True):
            for label, col in (("insert", ins), ("occupancy", occ)):
                if not col or col not in part.columns:
                    continue
                cells = []
                for i, k in enumerate(states):
                    v = meta[k].get(col)
                    a = max(0.05, min(1.0, float(v))) if isinstance(v, (int, float)) else 0.0
                    cells.append(
                        f'<rect x="{i * col_w}" y="{rows_y}" width="{col_w - 1}" height="8" fill="rgba(73,80,87,{a:.2f})"><title>state {k}: {label} {v}</title></rect>'
                    )
                extra.append(
                    f'<text x="-4" y="{rows_y + 7}" font-size="9" fill="#868e96" text-anchor="end">{label}</text>'
                    + "".join(cells)
                )
                rows_y += 11
        if cfg.get("show_consensus", True) and cons and cons in part.columns:
            letters = "".join(
                f'<text x="{i * col_w + col_w / 2:.1f}" y="{rows_y + 9}" font-size="10" font-family="Menlo,monospace" fill="#495057" text-anchor="middle">{esc(meta[k].get(cons) or "")}</text>'
                for i, k in enumerate(states)
            )
            extra.append(
                f'<text x="-4" y="{rows_y + 9}" font-size="9" fill="#868e96" text-anchor="end">consensus</text>'
                + letters
            )
            rows_y += 14
        total_h = rows_y + 4
        axis = (
            f'<line x1="-2" y1="0" x2="-2" y2="{height}" stroke="rgba(33,37,41,.16)"/>'
            f'<text x="-6" y="{height}" font-size="9" fill="#868e96" text-anchor="end">0</text>'
            f'<text x="-6" y="{height - 1 * unit + 3:.1f}" font-size="9" fill="#868e96" text-anchor="end">1</text>'
            f'<text x="-6" y="10" font-size="9" fill="#868e96" text-anchor="end">{"bits" if mode != "probability" else "p"}</text>'
        )
        svg = (
            f'<svg class="dpx-native" xmlns="http://www.w3.org/2000/svg" viewBox="-60 -4 {w + 64} {total_h + 4}" '
            f'width="100%" style="max-width:{w + 64}px;height:auto;display:block" role="img" aria-label="{esc(model)} logo">'
            f"{axis}{''.join(parts)}{''.join(extra)}</svg>"
        )
        label = (
            f'<div style="font-size:12px;font-weight:600;color:#495057;margin:6px 0 2px">{esc(model)} · {len(states)} match states</div>'
            if model
            else ""
        )
        blocks.append(f'<div style="overflow-x:auto">{label}{svg}</div>')
    if not blocks:
        raise NothingToDraw("no profile rows")
    mode_label = {
        "relent_abovebg": "above background, bits",
        "relent_all": "relative entropy, bits",
        "probability": "probability",
    }.get(mode, mode)
    sub = f"{len(models)} model{'s' if len(models) != 1 else ''}; letter heights {mode_label}"
    return html_result(tile, "".join(blocks), sub=sub)


register(
    NativeRenderer(
        kind="hmm_logo",
        output="static",
        how="an SVG logo, letters scaled to their bits (HMMER's hmmlogo)",
        render=_hmm_logo,
    )
)


# ---------------------------------------------------------------------------
# pae_matrix
# ---------------------------------------------------------------------------


def parse_pae(text: str) -> list[list[float]]:
    """``paeParse.ts``: AlphaFold JSON, or a whitespace / comma / tab matrix."""
    body = text.lstrip("﻿").strip()
    if not body:
        raise ValueError("empty PAE input")
    if body[0] in "[{":
        data = json.loads(body)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            data = data[0]
        if isinstance(data, dict):
            for key in ("predicted_aligned_error", "pae"):
                if key in data:
                    return [[float(v) for v in row] for row in data[key]]
            if "residue1" in data and "distance" in data:
                n = int(max(data["residue1"]))
                m = [[0.0] * n for _ in range(n)]
                for i, j, d in zip(
                    data["residue1"], data["residue2"], data["distance"], strict=False
                ):
                    m[int(i) - 1][int(j) - 1] = float(d)
                return m
        return [[float(v) for v in row] for row in data]
    rows = []
    for line in body.splitlines():
        cells = [c for c in line.replace(",", " ").split() if c]
        if not cells:
            continue
        try:
            rows.append([float(c) for c in cells])
        except ValueError:
            continue  # a header line
    return rows


def _pick_file(files: list[dict[str, Any]], entity: str | None) -> dict[str, Any] | None:
    if not files:
        return None
    if entity:
        for f in files:
            if str(f.get("sample")) == entity:
                return f
    return files[0]


def _pae_matrix(tile: Tile) -> Any:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    cfg = tile.config
    ent, pos, val = cfg.get("entity_col"), cfg.get("position_col"), cfg.get("value_col")
    df = tile.rows([ent, pos, val, cfg.get("chain_col")], full_load=True)
    df, entity, n_ent = _entity(tile, df, ent)
    if not cfg.get("pae_dc_id"):
        raise NothingToDraw("no PAE collection bound")
    entry = _pick_file(tile.indexed_files(str(cfg["pae_dc_id"])), entity)
    if entry is None:
        raise NothingToDraw("no PAE file for this entity")
    matrix = parse_pae(tile.object_text(str(entry["url"])))
    n = len(matrix)
    vmax = float(cfg.get("max_pae") or max(31.75, max(max(r) for r in matrix)))
    show_plddt = bool(cfg.get("show_plddt", True)) and val and val in df.columns and df.height > 0
    fig = make_subplots(
        rows=2 if show_plddt else 1,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.08, 0.92] if show_plddt else [1.0],
        vertical_spacing=0.02,
    )
    if show_plddt:
        part = df.sort(pos)
        vals = part[val].cast(pl.Float64).to_list()
        frac = all(v is None or v <= 1 for v in vals)
        fig.add_trace(
            go.Bar(
                x=part[pos].to_list(),
                y=[1] * len(vals),
                marker_color=[
                    rgb(plddt_band(v, frac)[0]) if v is not None else "#dee2e6" for v in vals
                ],
                marker_line_width=0,
                hovertext=[
                    f"{p}: pLDDT {v}" for p, v in zip(part[pos].to_list(), vals, strict=True)
                ],
                hoverinfo="text",
                showlegend=False,
            ),
            row=1,
            col=1,
        )
        fig.update_yaxes(showticklabels=False, showgrid=False, row=1, col=1)
    fig.add_trace(
        go.Heatmap(
            z=matrix,
            x=list(range(1, n + 1)),
            y=list(range(1, n + 1)),
            zmin=0,
            zmax=vmax,
            colorscale=[
                [0, "#0b4d1c"],
                [0.25, "#2d8a46"],
                [0.5, "#7fc47f"],
                [0.75, "#cfe9c6"],
                [1, "#ffffff"],
            ],
            colorbar={"title": {"text": "Expected position error (Å)"}, "thickness": 12},
            hovertemplate="scored %{x} · aligned %{y}: %{z:.1f} Å<extra></extra>",
        ),
        row=2 if show_plddt else 1,
        col=1,
    )
    r = 2 if show_plddt else 1
    fig.update_xaxes(constrain="domain", row=r, col=1)
    fig.update_yaxes(
        autorange="reversed",
        constrain="domain",
        title_text="Aligned residue",
        scaleanchor=f"x{r if r > 1 else ''}",
        showgrid=False,
        row=r,
        col=1,
    )
    fig.update_xaxes(title_text="Scored residue", showgrid=False, row=r, col=1)
    fig.update_layout(height=600)
    return figure_result(
        tile, fig, sub=f"{_entity_note(entity, n_ent)} · {n} × {n} residues".strip(" ·")
    )


register(
    NativeRenderer(
        kind="pae_matrix",
        output="interactive",
        how="a Plotly heatmap of the PAE file, with the pLDDT strip",
        render=_pae_matrix,
    )
)


# ---------------------------------------------------------------------------
# molecule_3d
# ---------------------------------------------------------------------------

_3DMOL = {"emitted": False}


def _has_py3dmol() -> bool:
    try:
        import py3Dmol  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def three_dmol_library() -> str:
    """3Dmol.js, inline, once per document: py3Dmol would fetch it from a CDN.

    Loaded with any AMD loader on the page put aside (Jupyter's require.js
    would otherwise take the bundle as a module), and the promise py3Dmol's
    cells wait on resolved, so none of them asks the network for it.
    """
    if _3DMOL["emitted"]:
        return ""
    source = (resources.files("depictio.notebook") / "assets" / "js" / "3Dmol-min.js").read_text()
    _3DMOL["emitted"] = True
    source = source.replace("</script", "<\\/script")
    return (
        "<script>window.__dpxDefine=window.define;window.define=undefined;</script>"
        f"<script>{source}</script>"
        "<script>window.define=window.__dpxDefine;"
        "if(window.$3Dmol){window.$3Dmolpromise=Promise.resolve();}</script>"
    )


def parse_ca(text: str, fmt: str) -> list[dict[str, Any]]:
    """CA atoms of a PDB or mmCIF: chain, residue number, name, B-factor (pLDDT), xyz."""
    out = []
    if fmt in ("cif", "mmcif"):
        header: list[str] = []
        for line in text.splitlines():
            if line.startswith("_atom_site."):
                header.append(line.split(".", 1)[1].strip())
            elif line.startswith(("ATOM", "HETATM")) and header:
                cells = line.split()
                row = dict(zip(header, cells, strict=False))
                if row.get("label_atom_id") == "CA":
                    out.append(
                        {
                            "chain": row.get("auth_asym_id") or row.get("label_asym_id"),
                            "resi": int(row.get("auth_seq_id") or row.get("label_seq_id") or 0),
                            "resn": row.get("label_comp_id"),
                            "b": float(row.get("B_iso_or_equiv") or 0),
                            "x": float(row["Cartn_x"]),
                            "y": float(row["Cartn_y"]),
                            "z": float(row["Cartn_z"]),
                        }
                    )
        return out
    for line in text.splitlines():
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            try:
                out.append(
                    {
                        "chain": line[21].strip(),
                        "resi": int(line[22:26]),
                        "resn": line[17:20].strip(),
                        "b": float(line[60:66] or 0),
                        "x": float(line[30:38]),
                        "y": float(line[38:46]),
                        "z": float(line[46:54]),
                    }
                )
            except ValueError:
                continue
        elif line.startswith("ENDMDL"):
            break
    return out


def _molecule_3d(tile: Tile) -> Any:
    cfg = tile.config
    ent, pos = cfg.get("entity_col"), cfg.get("position_col")
    label_col, cat_col = cfg.get("label_col"), cfg.get("category_col")
    df = tile.rows(
        [
            ent,
            pos,
            cfg.get("chain_col"),
            cfg.get("value_col"),
            cat_col,
            label_col,
            cfg.get("ref_aa_col"),
            cfg.get("alt_aa_col"),
        ],
        full_load=True,
    )
    df, entity, n_ent = _entity(tile, df, ent)
    if str(cfg.get("structure_source") or "file") != "file" or not cfg.get("structure_dc_id"):
        raise NothingToDraw("the structure is resolved from AlphaFold DB by the live view")
    entry = _pick_file(tile.indexed_files(str(cfg["structure_dc_id"])), entity)
    if entry is None:
        raise NothingToDraw("no structure file for this entity")
    name = str(entry.get("name") or "model.pdb").lower()
    fmt = "cif" if name.endswith((".cif", ".mmcif", ".cif.gz")) else "pdb"
    text = tile.object_text(str(entry["url"]))
    ca = parse_ca(text, fmt)
    if not ca:
        raise NothingToDraw("the structure file holds no residue")
    plddt = str(cfg.get("color_mode") or "plddt") == "plddt"
    frac = all(a["b"] <= 1 for a in ca)
    variants = []
    if cfg.get("show_variants") and pos and pos in df.columns:
        variants = sorted({int(v) for v in df[pos].to_list() if v is not None})
    sub = f"{_entity_note(entity, n_ent)} · {len(ca)} residues".strip(" ·")
    sub += ", coloured by pLDDT" if plddt else ""
    if variants:
        sub += f", {len(variants)} variant sites"
    if _has_py3dmol():
        import py3Dmol

        view = py3Dmol.view(width="100%", height=460)
        view.addModel(text, fmt)
        view.setStyle({"cartoon": {"color": "#adb5bd"}})
        if plddt:
            for floor, colour, _ in PLDDT_BANDS:
                resi = [a["resi"] for a in ca if plddt_band(a["b"], frac)[0] == colour]
                if resi:
                    view.setStyle({"resi": resi}, {"cartoon": {"color": "#%02x%02x%02x" % colour}})
        else:
            view.setStyle({"cartoon": {"color": "spectrum"}})
        if variants:
            view.addStyle(
                {"resi": variants}, {"stick": {"colorscheme": "redCarbon", "radius": 0.25}}
            )
            view.addStyle(
                {"resi": variants, "atom": "CA"}, {"sphere": {"color": "#e64980", "radius": 0.9}}
            )
        view.setBackgroundColor("white", 0)
        view.zoomTo()
        inner = three_dmol_library() + view._make_html()
        legend = (
            "".join(
                f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:10px">'
                f'<span style="width:10px;height:10px;border-radius:2px;background:{rgb(c)}"></span>{esc(lbl)}</span>'
                for _, c, lbl in PLDDT_BANDS
            )
            if plddt
            else ""
        )
        html = (
            f'<div class="dpx-tile dpx-native" data-dpx-native="molecule_3d">{head_html(tile, sub + "; drag to rotate, scroll to zoom")}'
            f'<div style="position:relative;width:100%;height:460px">{inner}</div>'
            f'<div style="font-size:11px;color:#868e96;margin-top:6px">{legend}</div></div>'
        )
        return NativeResult(bundle={HTML_MIME: html, "text/plain": f"{tile.title} (3D structure)"})
    # Without py3Dmol: the backbone as a Plotly 3D trace, still rotatable.
    import plotly.graph_objects as go

    colours = [rgb(plddt_band(a["b"], frac)[0]) if plddt else paper_colorway()[0] for a in ca]
    fig = go.Figure(
        go.Scatter3d(
            x=[a["x"] for a in ca],
            y=[a["y"] for a in ca],
            z=[a["z"] for a in ca],
            mode="lines+markers",
            line={"color": colours, "width": 6},
            marker={"size": 2.5, "color": colours},
            hovertext=[f"{a['resn']}{a['resi']} · pLDDT {a['b']:.0f}" for a in ca],
            hoverinfo="text",
        )
    )
    fig.update_layout(
        height=460,
        scene={
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
            "zaxis": {"visible": False},
            "aspectmode": "data",
        },
    )
    return figure_result(tile, fig, sub=sub + "; the CA backbone (py3Dmol draws the cartoon)")


register(
    NativeRenderer(
        kind="molecule_3d",
        output="interactive",
        how="py3Dmol (3Dmol.js inlined): the structure file, rotatable, coloured as the tile colours it",
        render=_molecule_3d,
    )
)
