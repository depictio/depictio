"""Genome-coordinate kinds as Plotly: a locus view, a copy-number profile, a sashimi
plot, a chord ring of rearrangements, an ideogram.

The live app draws these with GenomeSpy (WebGL), SVG or a canvas. Here each is
the opening view of the tile, from the same rows, as an interactive Plotly
figure. What only the live view can do (fetch a gene annotation track, follow a
brush, zoom with a refetch) is named in the tile's caption.
"""

from __future__ import annotations

import math
import re
from typing import Any

import polars as pl

from ..theme import paper_colorway
from . import NativeRenderer, NothingToDraw, Tile, figure_result, register, require

# chordLayout.ts ASSEMBLY_CHROM_SIZES: the assemblies the live tiles know by name.
ASSEMBLY_CHROM_SIZES: dict[str, dict[str, int]] = {
    "hg38": {
        "chr1": 248956422, "chr2": 242193529, "chr3": 198295559, "chr4": 190214555,
        "chr5": 181538259, "chr6": 170805979, "chr7": 159345973, "chr8": 145138636,
        "chr9": 138394717, "chr10": 133797422, "chr11": 135086622, "chr12": 133275309,
        "chr13": 114364328, "chr14": 107043718, "chr15": 101991189, "chr16": 90338345,
        "chr17": 83257441, "chr18": 80373285, "chr19": 58617616, "chr20": 64444167,
        "chr21": 46709983, "chr22": 50818468, "chrX": 156040895, "chrY": 57227415,
        "chrM": 16569,
    },
    "hg19": {
        "chr1": 249250621, "chr2": 243199373, "chr3": 198022430, "chr4": 191154276,
        "chr5": 180915260, "chr6": 171115067, "chr7": 159138663, "chr8": 146364022,
        "chr9": 141213431, "chr10": 135534747, "chr11": 135006516, "chr12": 133851895,
        "chr13": 115169878, "chr14": 107349540, "chr15": 102531392, "chr16": 90354753,
        "chr17": 81195210, "chr18": 78077248, "chr19": 59128983, "chr20": 63025520,
        "chr21": 48129895, "chr22": 51304566, "chrX": 155270560, "chrY": 59373566,
        "chrM": 16571,
    },
    "mm10": {
        "chr1": 195471971, "chr2": 182113224, "chr3": 160039680, "chr4": 156508116,
        "chr5": 151834684, "chr6": 149736546, "chr7": 145441459, "chr8": 129401213,
        "chr9": 124595110, "chr10": 130694993, "chr11": 122082543, "chr12": 120129022,
        "chr13": 120421639, "chr14": 124902244, "chr15": 104043685, "chr16": 98207768,
        "chr17": 94987271, "chr18": 90702639, "chr19": 61431566, "chrX": 171031299,
        "chrY": 91744698, "chrM": 16299,
    },
}  # fmt: skip

GRAY_LINE = "rgba(33, 37, 41, 0.16)"
FAINT = "#868e96"


def norm_chrom(name: Any) -> str:
    return re.sub(r"^chr", "", str(name).strip(), flags=re.I).lower()


def chrom_key(name: Any) -> tuple[int, str]:
    """``chromOrderKey``: 1..22, X, Y, M, then anything else alphabetically."""
    k = norm_chrom(name)
    if k.isdigit():
        return (int(k), "")
    rank = {"x": 1000, "y": 1001, "m": 1002, "mt": 1002}.get(k, 2000)
    return (rank, k)


def assembly_sizes(assembly: str | None) -> dict[str, int] | None:
    return ASSEMBLY_CHROM_SIZES.get(str(assembly or "").strip().lower()) if assembly else None


def chrom_sizes(
    df: pl.DataFrame, chrom_col: str, end_cols: list[str], assembly: str | None
) -> list[tuple[str, int]]:
    """The chromosomes to lay out and their lengths: the assembly's, else the data's reach."""
    names = list(dict.fromkeys(str(c) for c in df[chrom_col].to_list() if c is not None))
    table = assembly_sizes(assembly)
    if table:
        by_key = {norm_chrom(k): (k, v) for k, v in table.items()}
        used = {norm_chrom(n): n for n in names}
        out = []
        for key, (name, size) in by_key.items():
            if key in ("m", "mt") and key not in used:
                continue
            out.append((used.get(key, name), size))
        for key, name in used.items():
            if key not in by_key:
                out.append((name, _reach(df, chrom_col, name, end_cols)))
        return sorted(out, key=lambda t: chrom_key(t[0]))
    return sorted(
        ((n, _reach(df, chrom_col, n, end_cols)) for n in names), key=lambda t: chrom_key(t[0])
    )


def _reach(df: pl.DataFrame, chrom_col: str, name: str, end_cols: list[str]) -> int:
    sub = df.filter(pl.col(chrom_col).cast(pl.Utf8) == name)
    reach = 0.0
    for col in end_cols:
        if col and col in sub.columns and sub.height:
            v = sub[col].cast(pl.Float64, strict=False).max()
            if v is not None:
                reach = max(reach, float(v))
    return int(reach * 1.02) + 1


_REGION_RE = re.compile(r"^\s*([^:\s]+)\s*(?::\s*([\d,._]+)\s*-\s*([\d,._]+))?\s*$")


def parse_region(text: str | None) -> tuple[str, int | None, int | None] | None:
    """``chr11:1,950,000-2,950,000`` or a bare ``chr8``."""
    if not text:
        return None
    m = _REGION_RE.match(str(text))
    if not m:
        return None
    start = int(re.sub(r"[,._]", "", m.group(2))) if m.group(2) else None
    end = int(re.sub(r"[,._]", "", m.group(3))) if m.group(3) else None
    return m.group(1), start, end


def fmt_bp(pos: float) -> str:
    """``formatBp``: 1.2 Mb, 340 kb, 512 bp."""
    if pos >= 1e6:
        return f"{pos / 1e6:.3g} Mb"
    if pos >= 1e3:
        return f"{pos / 1e3:.3g} kb"
    return f"{int(pos)} bp"


def _scatter(go: Any) -> Any:
    """SVG scatter: a report holds many figures, and a page gets only a handful of
    WebGL contexts before the browser starts dropping the oldest ones' plots."""
    return go.Scatter


def colors_for(values: list[Any]) -> dict[str, str]:
    from .layout import category_colors

    return category_colors(values)


class GenomeAxis:
    """Genome-wide coordinates: chromosomes (or the stretches of them a table
    covers) laid end to end, as a whole-genome view draws them."""

    def __init__(
        self, sizes: list[tuple[str, int]], starts: dict[str, float] | None = None
    ) -> None:
        self.offsets: dict[str, float] = {}
        self.starts = {norm_chrom(k): v for k, v in (starts or {}).items()}
        self.sizes = sizes
        total = 0.0
        for name, size in sizes:
            self.offsets[norm_chrom(name)] = total
            total += size
        self.total = total

    @classmethod
    def covered(
        cls, df: pl.DataFrame, chrom_col: str, start_col: str, end_cols: list[str | None]
    ) -> GenomeAxis:
        """Only the stretch of each chromosome the rows reach, end to end."""
        starts: dict[str, float] = {}
        sizes: list[tuple[str, int]] = []
        for name in sorted(
            {str(c) for c in df[chrom_col].to_list() if c is not None}, key=chrom_key
        ):
            sub = df.filter(pl.col(chrom_col).cast(pl.Utf8) == name)
            lo = float(sub[start_col].cast(pl.Float64).min() or 0)
            hi = max(
                float(sub[c].cast(pl.Float64).max() or lo)
                for c in [start_col, *end_cols]
                if c and c in sub.columns
            )
            pad = max((hi - lo) * 0.03, 500.0)
            starts[name] = max(0.0, lo - pad)
            sizes.append((name, int(hi + pad - starts[name]) + 1))
        return cls(sizes, starts)

    def x(self, chrom: Any, pos: Any) -> float | None:
        key = norm_chrom(chrom)
        off = self.offsets.get(key)
        if off is None or pos is None:
            return None
        return off + float(pos) - self.starts.get(key, 0.0)

    def decorate(self, fig: Any, rows: int = 1) -> None:
        ticks, labels = [], []
        for name, size in self.sizes:
            key = norm_chrom(name)
            off = self.offsets[key]
            ticks.append(off + size / 2)
            label = re.sub(r"^chr", "", name, flags=re.I)
            if key in self.starts:
                lo = self.starts[key]
                label = f"{name}<br>{fmt_bp(lo)}–{fmt_bp(lo + size)}"
            labels.append(label)
            if off:
                fig.add_vline(x=off, line_width=1, line_color=GRAY_LINE)
        fig.update_xaxes(tickvals=ticks, ticktext=labels, range=[0, self.total], showgrid=False)


# ---------------------------------------------------------------------------
# genome_view
# ---------------------------------------------------------------------------


def _genome_view(tile: Tile) -> Any:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    cfg = tile.config
    chr_col, pos_col = cfg.get("chr_col"), cfg.get("pos_col")
    score_col, end_col = cfg.get("score_col"), cfg.get("end_col")
    feature_col, sample_col = cfg.get("feature_col"), cfg.get("sample_col")
    cat_col = cfg.get("category_col")
    hover_cols = [c for c in (cfg.get("hover_cols") or []) if c]
    df = tile.rows(
        [chr_col, pos_col, end_col, score_col, feature_col, sample_col, cat_col, *hover_cols],
        roles={"chrom": chr_col, "pos": pos_col, **({"score": score_col} if score_col else {})},
    )
    df = require(df, chr_col, pos_col)
    region = parse_region(cfg.get("default_region"))
    chroms = list(dict.fromkeys(str(c) for c in df[chr_col].to_list() if c is not None))
    window: tuple[str, float, float] | None = None
    axis: GenomeAxis | None = None
    if region:
        name = next((c for c in chroms if norm_chrom(c) == norm_chrom(region[0])), region[0])
        sub = df.filter(pl.col(chr_col).cast(pl.Utf8) == name)
        lo = region[1] if region[1] is not None else 0
        sizes = assembly_sizes(cfg.get("assembly")) or {}
        reach = next((v for k, v in sizes.items() if norm_chrom(k) == norm_chrom(name)), None)
        hi = (
            region[2]
            if region[2] is not None
            else (reach or _reach(sub, chr_col, name, [pos_col, end_col]))
        )
        window = (name, float(lo), float(hi))
        df = sub.filter(
            (pl.col(pos_col).cast(pl.Float64) <= hi)
            & (pl.col(end_col or pos_col).cast(pl.Float64) >= lo)
        )
    elif len(chroms) == 1:
        name = chroms[0]
        lo = float(df[pos_col].cast(pl.Float64).min() or 0)
        hi = float(df[end_col or pos_col].cast(pl.Float64).max() or lo + 1)
        pad = max((hi - lo) * 0.02, 1.0)
        window = (name, max(0.0, lo - pad), hi + pad)
    else:
        axis = GenomeAxis(chrom_sizes(df, chr_col, [pos_col, end_col], cfg.get("assembly")))
        covered = GenomeAxis.covered(df, chr_col, pos_col, [end_col])
        if covered.total < 0.05 * axis.total:
            # A table over a few loci: the whole genome would draw it as a few
            # hairlines, so the axis runs over the stretches the rows reach.
            axis = covered

    facets: list[str | None] = [None]
    dropped = 0
    if cfg.get("facet_by_sample") and sample_col and sample_col in df.columns:
        names = sorted({str(s) for s in df[sample_col].to_list() if s is not None})
        cap = int(cfg.get("max_facets") or 8)
        facets, dropped = list(names[:cap]), max(0, len(names) - cap)
        facets = facets or [None]
    fig = make_subplots(
        rows=len(facets),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        subplot_titles=[f for f in facets] if facets != [None] else None,
    )
    colors = colors_for(df[cat_col].to_list()) if cat_col and cat_col in df.columns else {}
    primary = paper_colorway()[0]
    mark = str(cfg.get("mark") or "point")
    opacity = float(cfg.get("opacity") or 0.85)
    seen_legend: set[str] = set()
    for r, facet in enumerate(facets, start=1):
        part = df if facet is None else df.filter(pl.col(sample_col).cast(pl.Utf8) == facet)
        groups = (
            [(str(k[0]), g) for k, g in part.group_by(cat_col, maintain_order=True)]
            if colors
            else [(None, part)]
        )
        for cat, g in groups:
            if axis:
                xs = [
                    axis.x(c, p)
                    for c, p in zip(g[chr_col].to_list(), g[pos_col].to_list(), strict=True)
                ]
                ends = (
                    [
                        axis.x(c, p)
                        for c, p in zip(g[chr_col].to_list(), g[end_col].to_list(), strict=True)
                    ]
                    if end_col and end_col in g.columns
                    else xs
                )
            else:
                xs = g[pos_col].cast(pl.Float64).to_list()
                ends = (
                    g[end_col].cast(pl.Float64).to_list()
                    if end_col and end_col in g.columns
                    else xs
                )
            ys = (
                g[score_col].cast(pl.Float64, strict=False).to_list()
                if score_col and score_col in g.columns
                else [1.0] * g.height
            )
            hover = []
            for i, row in enumerate(g.iter_rows(named=True)):
                bits = (
                    [f"<b>{row.get(feature_col)}</b>"]
                    if feature_col and row.get(feature_col) is not None
                    else []
                )
                bits.append(
                    f"{row[chr_col]}:{int(row[pos_col]):,}"
                    if row.get(pos_col) is not None
                    else str(row[chr_col])
                )
                if score_col and ys[i] is not None:
                    bits.append(f"{cfg.get('score_title') or score_col}: {ys[i]:.4g}")
                bits += [
                    f"{c}: {row.get(c)}" for c in hover_cols if c in row and c not in (feature_col,)
                ]
                hover.append("<br>".join(bits))
            color = colors.get(cat, primary) if cat is not None else primary
            name = cat or (cfg.get("score_title") or score_col or "features")
            show = name not in seen_legend and bool(colors)
            seen_legend.add(name)
            if mark == "bar" and ends is not xs:
                mids = [
                    (a + b) / 2 if a is not None and b is not None else a
                    for a, b in zip(xs, ends, strict=True)
                ]
                widths = [
                    max((b - a), 1.0) if a is not None and b is not None else 1.0
                    for a, b in zip(xs, ends, strict=True)
                ]
                trace = go.Bar(
                    x=mids,
                    y=ys,
                    width=widths,
                    marker_color=color,
                    opacity=opacity,
                    name=name,
                    legendgroup=name,
                    showlegend=show,
                    hovertext=hover,
                    hoverinfo="text",
                    marker_line_width=0,
                )
            else:
                trace = _scatter(go)(
                    x=xs,
                    y=ys,
                    mode="markers",
                    name=name,
                    legendgroup=name,
                    showlegend=show,
                    marker={
                        "color": color,
                        "size": int(cfg.get("point_size") or 5),
                        "opacity": opacity,
                    },
                    hovertext=hover,
                    hoverinfo="text",
                )
            fig.add_trace(trace, row=r, col=1)
        if cfg.get("score_threshold") is not None:
            fig.add_hline(
                y=float(cfg["score_threshold"]),
                line_dash="dash",
                line_width=1,
                line_color=FAINT,
                row=r,
                col=1,
            )
    if facets != [None]:
        fig.update_layout(margin={"t": 28})
    fig.update_layout(
        height=max(300, 150 + 150 * len(facets)),
        bargap=0,
        barmode="overlay",
        showlegend=bool(colors) and cfg.get("show_legend", True) is not False,
    )
    fig.update_yaxes(title_text=cfg.get("score_title") or score_col or "", row=len(facets) // 2 + 1)
    if axis:
        axis.decorate(fig)
        where = "the stretches the rows cover" if axis.starts else "the whole genome"
    else:
        assert window is not None
        fig.update_xaxes(range=[window[1], window[2]])
        fig.update_xaxes(title_text=f"{window[0]} (bp)", row=len(facets), col=1)
        where = (
            f"{window[0]}:{int(window[1]):,}-{int(window[2]):,} ({fmt_bp(window[2] - window[1])})"
        )
    sub = f"The opening window, {where}"
    if str(cfg.get("annotation") or "none") != "none":
        sub += f"; the {cfg['annotation']} gene track is drawn live"
    if dropped:
        sub += f"; {dropped} more samples in the live view"
    return figure_result(tile, fig, sub=sub)


register(
    NativeRenderer(
        kind="genome_view",
        output="interactive",
        how="a Plotly figure of the tile's opening window, from its rows",
        render=_genome_view,
    )
)


# ---------------------------------------------------------------------------
# cnv_profile (the GenomeSpy `locus` view)
# ---------------------------------------------------------------------------


def _cnv_profile(tile: Tile) -> Any:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    cfg = tile.config
    s_col, c_col = cfg.get("sample_col"), cfg.get("chrom_col")
    st, en, l2 = cfg.get("start_col"), cfg.get("end_col"), cfg.get("log2_col")
    baf, seg, lab = cfg.get("baf_col"), cfg.get("segment_col"), cfg.get("label_col")
    cn = cfg.get("copy_number_col")
    df = require(
        tile.rows([s_col, c_col, st, en, l2, baf, seg, lab, cn], full_load=True), c_col, st, l2
    )
    samples = sorted({str(s) for s in df[s_col].to_list()}) if s_col and s_col in df.columns else []
    sample = (
        cfg.get("sample") if cfg.get("sample") in samples else (samples[0] if samples else None)
    )
    if sample is not None:
        df = df.filter(pl.col(s_col).cast(pl.Utf8) == sample)
    if cfg.get("chrom"):
        df = df.filter(pl.col(c_col).cast(pl.Utf8) == str(cfg["chrom"]))
    if df.height == 0:
        raise NothingToDraw("no bins for the opening sample")
    # The chromosomes as far as the bins reach: a profile over part of a
    # genome reads as a profile, not as a strip at the left of an empty axis.
    axis = GenomeAxis(chrom_sizes(df, c_col, [en, st], None))
    is_seg = (
        (pl.col(seg).cast(pl.Utf8) == "segment") if seg and seg in df.columns else pl.lit(False)
    )
    bins, segs = df.filter(~is_seg), df.filter(is_seg)
    show_baf = bool(cfg.get("show_baf", True)) and baf and baf in df.columns
    fig = make_subplots(
        rows=2 if show_baf else 1,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.65, 0.35] if show_baf else [1.0],
    )
    gain, loss = float(cfg.get("gain_threshold") or 0.3), float(cfg.get("loss_threshold") or -0.3)
    mids = [
        axis.x(c, (a + b) / 2)
        for c, a, b in zip(
            bins[c_col].to_list(), bins[st].to_list(), bins[en].to_list(), strict=True
        )
    ]
    vals = bins[l2].cast(pl.Float64).to_list()
    colors = [
        "#fa5252"
        if v is not None and v >= gain
        else "#228be6"
        if v is not None and v <= loss
        else "#adb5bd"
        for v in vals
    ]
    size = int(cfg.get("point_size") or 3)
    fig.add_trace(
        _scatter(go)(
            x=mids,
            y=vals,
            mode="markers",
            name="log2 ratio",
            marker={"color": colors, "size": size, "opacity": 0.6},
            hoverinfo="skip",
            showlegend=False,
        ),
        row=1,
        col=1,
    )
    if segs.height:
        xs: list[Any] = []
        ys: list[Any] = []
        text: list[Any] = []
        for row in segs.iter_rows(named=True):
            a, b = axis.x(row[c_col], row[st]), axis.x(row[c_col], row[en])
            label = row.get(lab) or (f"CN {row.get(cn)}" if cn else "")
            xs += [a, b, None]
            ys += [row[l2], row[l2], None]
            text += [
                f"{row[c_col]}:{int(row[st]):,}-{int(row[en]):,}<br>log2 {row[l2]}<br>{label}"
            ] * 2 + [None]
        fig.add_trace(
            _scatter(go)(
                x=xs,
                y=ys,
                mode="lines",
                line={"color": "#212529", "width": 2.5},
                name="segments",
                hovertext=text,
                hoverinfo="text",
                showlegend=False,
            ),
            row=1,
            col=1,
        )
    yr = float(cfg.get("y_range") or 3.0)
    fig.update_yaxes(range=[-yr, yr], title_text="log2 ratio", row=1, col=1)
    if show_baf:
        fig.add_trace(
            _scatter(go)(
                x=mids,
                y=bins[baf].cast(pl.Float64).to_list(),
                mode="markers",
                name="BAF",
                marker={"color": "#868e96", "size": max(2, size - 1), "opacity": 0.45},
                hoverinfo="skip",
                showlegend=False,
            ),
            row=2,
            col=1,
        )
        fig.update_yaxes(range=[0, 1], title_text="BAF", row=2, col=1)
    axis.decorate(fig)
    fig.update_layout(height=420 if show_baf else 320)
    sub = f"{sample}, genome-wide" if sample else "Genome-wide"
    if len(samples) > 1:
        sub += f" ({len(samples)} samples in the live view)"
    return figure_result(tile, fig, sub=sub + "; the locus view's gene track is drawn live")


register(
    NativeRenderer(
        kind="cnv_profile",
        output="interactive",
        how="a Plotly copy-number profile of the opening sample, from its bins and segments",
        render=_cnv_profile,
    )
)


# ---------------------------------------------------------------------------
# sashimi (the GenomeSpy view)
# ---------------------------------------------------------------------------


def _sashimi(tile: Tile) -> Any:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    cfg = tile.config
    chr_col, st, en = cfg.get("chr_col"), cfg.get("start_col"), cfg.get("end_col")
    cnt, s_col, ann = cfg.get("count_col"), cfg.get("sample_col"), cfg.get("annotation_col")
    df = require(tile.rows([chr_col, st, en, cnt, s_col, ann], full_load=True), st, en, cnt)
    df = df.filter(pl.col(cnt).cast(pl.Float64) >= float(cfg.get("min_count") or 1))
    if df.height == 0:
        raise NothingToDraw("no junction above the minimum count")
    samples = (
        sorted({str(s) for s in df[s_col].to_list()}) if s_col and s_col in df.columns else [None]
    )
    # The opening locus: junctions a megabase or more apart are other genes,
    # which the live view reaches by navigating; the busiest locus opens.
    loci: list[list[dict[str, Any]]] = []
    for row in df.sort(st).iter_rows(named=True):
        if loci and float(row[st]) <= max(float(r[en]) for r in loci[-1]) + 1_000_000:
            loci[-1].append(row)
        else:
            loci.append([row])
    locus = max(loci, key=len)
    lo, hi = min(float(r[st]) for r in locus), max(float(r[en]) for r in locus)
    df = df.filter((pl.col(st).cast(pl.Float64) >= lo) & (pl.col(en).cast(pl.Float64) <= hi))
    pad = (hi - lo) * 0.05
    lo, hi = lo - pad, hi + pad
    cov = None
    if cfg.get("show_coverage", True) and cfg.get("coverage_dc_id"):
        cc = [
            cfg.get("coverage_chr_col"),
            cfg.get("coverage_position_col"),
            cfg.get("coverage_end_col"),
            cfg.get("coverage_value_col"),
            cfg.get("coverage_sample_col"),
        ]
        try:
            cov = tile.rows(
                cc,
                dc_id=str(cfg["coverage_dc_id"]),
                wf_id=cfg.get("coverage_wf_id") or tile.wf_id,
                full_load=True,
            )
        except Exception:  # noqa: BLE001 - arcs alone still answer the question
            cov = None
    fig = make_subplots(
        rows=len(samples),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=[s for s in samples] if samples != [None] else None,
    )
    ann_colors = colors_for(df[ann].to_list()) if ann and ann in df.columns else {}
    top_n = int(cfg.get("top_n") or 25)
    seen: set[str] = set()
    for r, sample in enumerate(samples, start=1):
        part = df if sample is None else df.filter(pl.col(s_col).cast(pl.Utf8) == sample)
        part = part.sort(cnt, descending=True).head(top_n)
        peak = 1.0
        if cov is not None and cov.height:
            vcol, pcol, scol = (
                cfg.get("coverage_value_col"),
                cfg.get("coverage_position_col"),
                cfg.get("coverage_sample_col"),
            )
            cpart = (
                cov
                if sample is None or not scol or scol not in cov.columns
                else cov.filter(pl.col(scol).cast(pl.Utf8) == sample)
            )
            cpart = cpart.filter(pl.col(pcol).cast(pl.Float64).is_between(lo, hi)).sort(pcol)
            ys = cpart[vcol].cast(pl.Float64).to_list()
            peak = max([1.0, *[y for y in ys if y is not None]])
            fig.add_trace(
                go.Scatter(
                    x=cpart[pcol].to_list(),
                    y=ys,
                    mode="lines",
                    line={"shape": "hv", "width": 0.8, "color": "#868e96"},
                    fill="tozeroy",
                    fillcolor="rgba(134, 142, 150, 0.25)",
                    name="coverage",
                    showlegend=False,
                    hoverinfo="skip",
                ),
                row=r,
                col=1,
            )
        counts = part[cnt].cast(pl.Float64).to_list()
        cmax = max(counts) if counts else 1.0
        for row, c in zip(part.iter_rows(named=True), counts, strict=True):
            a, b = float(row[st]), float(row[en])
            weight = math.log1p(c) / math.log1p(cmax) if cfg.get("log_width", True) else c / cmax
            h = peak * (0.35 + 0.55 * weight) * float(cfg.get("arc_height") or 1.0)
            xs = [a + (b - a) * t / 24 for t in range(25)]
            ys = [peak * 1.02 + h * 4 * (t / 24) * (1 - t / 24) for t in range(25)]
            cat = str(row.get(ann)) if ann else "junction"
            color = ann_colors.get(cat, paper_colorway()[0])
            width = 1 + float(cfg.get("max_arc_width") or 3) * weight
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    line={"color": color, "width": width},
                    name=cat,
                    legendgroup=cat,
                    showlegend=cat not in seen,
                    hovertext=f"{row.get(chr_col, '')}:{int(a):,}-{int(b):,}<br>{int(c):,} reads<br>{cat}",
                    hoverinfo="text",
                ),
                row=r,
                col=1,
            )
            seen.add(cat)
            fig.add_annotation(
                x=(a + b) / 2,
                y=ys[12],
                text=f"{int(c)}",
                showarrow=False,
                font={"size": 9, "color": color},
                yshift=6,
                row=r,
                col=1,
            )
    chrom = str(df[chr_col][0]) if chr_col and chr_col in df.columns else ""
    fig.update_xaxes(range=[lo, hi])
    fig.update_xaxes(title_text=f"{chrom} (bp)", row=len(samples), col=1)
    fig.update_yaxes(rangemode="tozero")
    fig.update_layout(height=max(320, 140 * len(samples) + 80), margin={"t": 28})
    return figure_result(
        tile,
        fig,
        sub=f"Junctions and coverage over {chrom}:{int(lo):,}-{int(hi):,}, top {top_n} per sample"
        + (f"; {len(loci) - 1} more loci" if len(loci) > 1 else "")
        + "; the gene model is drawn live",
    )


register(
    NativeRenderer(
        kind="sashimi",
        output="interactive",
        how="a Plotly sashimi plot (coverage and junction arcs per sample), from its rows",
        render=_sashimi,
    )
)


# ---------------------------------------------------------------------------
# genome_chord
# ---------------------------------------------------------------------------


def _genome_chord(tile: Tile) -> Any:
    import plotly.graph_objects as go

    cfg = tile.config
    ca, pa, cb, pb = (
        cfg.get("chrom_a_col"),
        cfg.get("pos_a_col"),
        cfg.get("chrom_b_col"),
        cfg.get("pos_b_col"),
    )
    lab, wt, cat = cfg.get("label_col"), cfg.get("weight_col"), cfg.get("category_col")
    df = require(tile.rows([ca, pa, cb, pb, lab, wt, cat, cfg.get("sample_col")]), ca, pa, cb, pb)
    if not cfg.get("intra_chromosomal", True):
        df = df.filter(pl.col(ca).cast(pl.Utf8) != pl.col(cb).cast(pl.Utf8))
    if cfg.get("min_weight") is not None and wt and wt in df.columns:
        df = df.filter(pl.col(wt).cast(pl.Float64) >= float(cfg["min_weight"]))
    if wt and wt in df.columns:
        df = df.sort(wt, descending=True)
    df = df.head(int(cfg.get("max_links") or 500))
    if df.height == 0:
        raise NothingToDraw("no link left to draw")
    stacked = pl.concat(
        [
            df.select(pl.col(ca).alias("c"), pl.col(pa).alias("p")),
            df.select(pl.col(cb).alias("c"), pl.col(pb).alias("p")),
        ]
    )
    sizes = chrom_sizes(
        stacked.with_columns(pl.col("c").cast(pl.Utf8)), "c", ["p"], cfg.get("assembly")
    )
    total = sum(s for _, s in sizes)
    gap = 2 * math.pi * 0.004
    span = 2 * math.pi - gap * len(sizes)
    starts: dict[str, float] = {}
    angle = math.pi / 2
    fig = go.Figure()
    for name, size in sizes:
        starts[norm_chrom(name)] = angle
        sweep = span * size / total
        ts = [angle - sweep * i / 30 for i in range(31)]
        fig.add_trace(
            go.Scatter(
                x=[math.cos(t) for t in ts],
                y=[math.sin(t) for t in ts],
                mode="lines",
                line={"color": "#495057", "width": 7},
                hovertext=f"{name}: {fmt_bp(size)}",
                hoverinfo="text",
                showlegend=False,
            )
        )
        mid = angle - sweep / 2
        fig.add_annotation(
            x=1.12 * math.cos(mid),
            y=1.12 * math.sin(mid),
            text=re.sub(r"^chr", "", name, flags=re.I),
            showarrow=False,
            font={"size": 10, "color": FAINT},
        )
        angle -= sweep + gap

    def at(chrom: Any, pos: Any) -> float | None:
        start = starts.get(norm_chrom(chrom))
        size = next((s for n, s in sizes if norm_chrom(n) == norm_chrom(chrom)), None)
        if start is None or not size or pos is None:
            return None
        return start - span * float(pos) / total

    colour_by = str(cfg.get("colour_by") or "category")
    key = cat if colour_by == "category" and cat and cat in df.columns else None
    colors = colors_for(df[key].to_list()) if key else {}
    weights = df[wt].cast(pl.Float64).to_list() if wt and wt in df.columns else [1.0] * df.height
    wmax = max([w for w in weights if w is not None] + [1e-9])
    seen: set[str] = set()
    for row, w in zip(df.iter_rows(named=True), weights, strict=True):
        a, b = at(row[ca], row[pa]), at(row[cb], row[pb])
        if a is None or b is None:
            continue
        p0, p2 = (0.97 * math.cos(a), 0.97 * math.sin(a)), (0.97 * math.cos(b), 0.97 * math.sin(b))
        sep = abs(math.atan2(math.sin(a - b), math.cos(a - b)))
        k = 0.15 + 0.6 * (1 - sep / math.pi)  # close ends bow less far towards the centre
        mid = (a + b) / 2 if abs(a - b) <= math.pi else (a + b) / 2 + math.pi
        p1 = (k * math.cos(mid), k * math.sin(mid))
        ts = [i / 30 for i in range(31)]
        xs = [(1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0] for t in ts]
        ys = [(1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1] for t in ts]
        group = str(row.get(key)) if key else "links"
        color = colors.get(group, paper_colorway()[0])
        text = f"<b>{row.get(lab) or ''}</b><br>{row[ca]}:{int(row[pa]):,} ↔ {row[cb]}:{int(row[pb]):,}"
        if wt and w is not None:
            text += f"<br>{wt}: {w:g}"
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                line={"color": color, "width": 1 + 4 * ((w or 0) / wmax)},
                opacity=0.75,
                name=group,
                legendgroup=group,
                showlegend=bool(key) and group not in seen,
                hovertext=text,
                hoverinfo="text",
            )
        )
        seen.add(group)
        if cfg.get("show_labels") and row.get(lab) and w is not None and w >= 0.5 * wmax:
            fig.add_annotation(
                x=xs[15],
                y=ys[15],
                text=str(row[lab]),
                showarrow=False,
                font={"size": 9, "color": color},
            )
    fig.update_xaxes(visible=False, range=[-1.25, 1.25], scaleanchor="y")
    fig.update_yaxes(visible=False, range=[-1.25, 1.25])
    fig.update_layout(height=560)
    asm = cfg.get("assembly")
    sub = (
        f"{df.height} links on the {asm} ring"
        if assembly_sizes(asm)
        else f"{df.height} links; chromosomes sized by the data"
    )
    return figure_result(tile, fig, sub=sub)


register(
    NativeRenderer(
        kind="genome_chord",
        output="interactive",
        how="a Plotly chord ring of the links, from its rows",
        render=_genome_chord,
    )
)


# ---------------------------------------------------------------------------
# ideogram
# ---------------------------------------------------------------------------


def _ideogram(tile: Tile) -> Any:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    cfg = tile.config
    c_col, s_col_, e_col = cfg.get("chrom_col"), cfg.get("start_col"), cfg.get("end_col")
    v_col, cat, sample_col = cfg.get("value_col"), cfg.get("category_col"), cfg.get("sample_col")
    len_col, label_col = cfg.get("chrom_length_col"), cfg.get("label_col")
    df = require(
        tile.rows(
            [c_col, s_col_, e_col, v_col, cat, sample_col, len_col, label_col], full_load=True
        ),
        c_col,
        s_col_,
    )
    if cfg.get("chromosomes"):
        keep = {norm_chrom(c) for c in cfg["chromosomes"]}
        df = df.filter(
            pl.col(c_col).map_elements(lambda c: norm_chrom(c) in keep, return_dtype=pl.Boolean)
        )
    samples = (
        sorted({str(s) for s in df[sample_col].to_list()}, key=lambda s: s)
        if sample_col and sample_col in df.columns
        else []
    )
    if not samples:
        shown: list[str | None] = [None]
    elif cfg.get("facet_by_sample"):
        shown = list(samples[: int(cfg.get("max_facets") or 6)])
    else:
        shown = [cfg.get("sample") if cfg.get("sample") in samples else samples[0]]
    mode = str(cfg.get("mode") or "marks")
    if mode == "marks" and df.height > int(cfg.get("max_features") or 20000):
        mode = "density"
    vertical = str(cfg.get("orientation") or "horizontal") == "vertical"
    fig = make_subplots(
        rows=1 if vertical else len(shown),
        cols=len(shown) if vertical else 1,
        subplot_titles=[s for s in shown] if len(shown) > 1 else None,
        horizontal_spacing=0.04,
        vertical_spacing=0.08,
    )
    colors = colors_for(df[cat].to_list()) if cat and cat in df.columns else {}
    seen: set[str] = set()
    max_len = 0
    lanes = 0
    drawn = 0
    for i, sample in enumerate(shown, start=1):
        part = df if sample is None else df.filter(pl.col(sample_col).cast(pl.Utf8) == sample)
        sizes = chrom_sizes(
            part.with_columns(pl.col(c_col).cast(pl.Utf8)),
            c_col,
            [e_col, s_col_],
            cfg.get("assembly"),
        )
        if len_col and len_col in part.columns:
            stated = {
                norm_chrom(c): float(v)
                for c, v in part.select(c_col, len_col).unique(c_col).iter_rows()
                if v is not None
            }
            sizes = [
                (n, int(max(stated.get(norm_chrom(n), 0), s if norm_chrom(n) not in stated else 0)))
                for n, s in sizes
            ]
        sizes = sorted(sizes, key=lambda t: t[1], reverse=True)[
            : int(cfg.get("max_chromosomes") or 60)
        ]
        sizes = sorted(sizes, key=lambda t: chrom_key(t[0]))
        names = [n for n, _ in sizes]
        lanes = max(lanes, len(names))
        index = {norm_chrom(n): k for k, n in enumerate(names)}
        max_len = max([max_len, *(s for _, s in sizes)])
        rc = {"row": 1, "col": i} if vertical else {"row": i, "col": 1}
        # The chromosomes: rounded-looking bars, gray, behind the features.
        bar = {
            "base": [0] * len(sizes),
            "marker": {
                "color": "rgba(33, 37, 41, 0.07)",
                "line": {"color": "rgba(33, 37, 41, 0.25)", "width": 1},
            },
            "hovertext": [f"{n}: {fmt_bp(s)}" for n, s in sizes],
            "hoverinfo": "text",
            "showlegend": False,
            "width": 0.6,
        }
        if vertical:
            fig.add_trace(go.Bar(x=list(range(len(sizes))), y=[s for _, s in sizes], **bar), **rc)
        else:
            fig.add_trace(
                go.Bar(y=list(range(len(sizes))), x=[s for _, s in sizes], orientation="h", **bar),
                **rc,
            )
        rows = [
            r
            for r in part.iter_rows(named=True)
            if norm_chrom(r[c_col]) in index and r.get(s_col_) is not None
        ]
        drawn += len(rows)
        if mode == "density":
            vals = [float(r[v_col]) if v_col and r.get(v_col) is not None else 1.0 for r in rows]
            pos = [index[norm_chrom(r[c_col])] for r in rows]
            st = [float(r[s_col_]) for r in rows]
            ln = [max(float(r.get(e_col) or r[s_col_]) - float(r[s_col_]), 1.0) for r in rows]
            marker = {
                "color": vals,
                "colorscale": cfg.get("colour_scale") or "Viridis",
                "showscale": i == 1,
                "colorbar": {"title": {"text": v_col or "count"}},
                "line": {"width": 0},
            }
            hover = [
                f"{r[c_col]}:{int(r[s_col_]):,}<br>{v_col or 'features'}: {v:g}"
                for r, v in zip(rows, vals, strict=True)
            ]
            if vertical:
                fig.add_trace(
                    go.Bar(
                        x=pos,
                        y=ln,
                        base=st,
                        marker=marker,
                        width=0.6,
                        hovertext=hover,
                        hoverinfo="text",
                        showlegend=False,
                    ),
                    **rc,
                )
            else:
                fig.add_trace(
                    go.Bar(
                        y=pos,
                        x=ln,
                        base=st,
                        orientation="h",
                        marker=marker,
                        width=0.6,
                        hovertext=hover,
                        hoverinfo="text",
                        showlegend=False,
                    ),
                    **rc,
                )
        else:
            groups: dict[str, list[dict[str, Any]]] = {}
            for r in rows:
                groups.setdefault(str(r.get(cat)) if colors else "features", []).append(r)
            for g, rs in groups.items():
                mid = [(float(r[s_col_]) + float(r.get(e_col) or r[s_col_])) / 2 for r in rs]
                at = [index[norm_chrom(r[c_col])] for r in rs]
                hover = [
                    f"<b>{r.get(label_col) or ''}</b><br>{r[c_col]}:{int(r[s_col_]):,}"
                    + (f"<br>{g}" if colors else "")
                    for r in rs
                ]
                color = colors.get(g, paper_colorway()[0])
                marker = {
                    "color": color,
                    "symbol": "line-ew" if vertical else "line-ns",
                    "size": 11,
                    "line": {"width": 1.5, "color": color},
                }
                trace = go.Scatter(
                    x=at if vertical else mid,
                    y=mid if vertical else at,
                    mode="markers",
                    marker=marker,
                    name=g,
                    legendgroup=g,
                    showlegend=bool(colors) and g not in seen,
                    hovertext=hover,
                    hoverinfo="text",
                )
                fig.add_trace(trace, **rc)
                seen.add(g)
        ticks = {
            "tickvals": list(range(len(names))),
            "ticktext": [re.sub(r"^chr", "", n, flags=re.I) for n in names],
            "showgrid": False,
        }
        if vertical:
            fig.update_xaxes(**ticks, **rc)
            fig.update_yaxes(autorange="reversed", showgrid=False, **rc)
        else:
            fig.update_yaxes(autorange="reversed", **ticks, **rc)
            fig.update_xaxes(showgrid=False, **rc)
    per = 18 * lanes + 70
    fig.update_layout(
        barmode="overlay",
        bargap=0,
        height=max(320, 420 if vertical else per * len(shown)),
        margin={"t": 28 if len(shown) > 1 else 8},
    )
    note = f"{'Density' if mode == 'density' else 'Marks'} of {drawn:,} features"
    if not cfg.get("facet_by_sample") and len(samples) > 1:
        note += f" for {shown[0]} ({len(samples)} samples in the live view)"
    elif len(shown) == 1 and shown[0]:
        note += f" for {shown[0]}"
    return figure_result(tile, fig, sub=note)


register(
    NativeRenderer(
        kind="ideogram",
        output="interactive",
        how="a Plotly karyotype of the features, from its rows",
        render=_ideogram,
    )
)
