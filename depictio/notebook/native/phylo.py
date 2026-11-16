"""The phylogeny collapsed to one tip per lineage: the summary view, as Plotly.

A port of ``phylo/rankSummary.ts``: each of the top ``top_n`` values of
``collapse_rank`` is placed at its core clade (the largest clade whose
classified tips all carry it), the tree induced over those clades is drawn as
a cladogram, each lineage with a dot sized by its share and, when an abundance
table is bound, a strip of dots giving the same share within each value of the
split column (a site). The full tree view is a Plotly figure in the live app
already and reaches the document as one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import NativeRenderer, NothingToDraw, Tile, figure_result, register


@dataclass
class Node:
    id: int
    name: str | None = None
    children: list[Node] = field(default_factory=list)


def parse_newick(text: str) -> Node:
    """A Newick string as nodes (iterative: amplicon trees run thousands of tips deep)."""
    s = text.strip().rstrip(";")
    counter = [0]

    def new(name: str | None = None) -> Node:
        counter[0] += 1
        return Node(counter[0], name)

    root = new()
    stack = [root]
    cur = root
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "(":
            child = new()
            cur.children.append(child)
            stack.append(child)
            cur = child
            i += 1
        elif ch == ",":
            stack.pop()
            parent = stack[-1]
            child = new()
            parent.children.append(child)
            stack.append(child)
            cur = child
            i += 1
        elif ch == ")":
            stack.pop()
            cur = stack[-1]
            i += 1
        else:
            j = i
            if ch == "'":
                j = s.index("'", i + 1) + 1
            while j < n and s[j] not in "(),;":
                j += 1
            token = s[i:j]
            label = token.split(":", 1)[0].strip().strip("'")
            if label:
                cur.name = label
            i = j
    return root


def _postorder(root: Node) -> list[Node]:
    out, stack = [], [(root, False)]
    while stack:
        node, done = stack.pop()
        if done:
            out.append(node)
            continue
        stack.append((node, True))
        stack.extend((c, False) for c in reversed(node.children))
    return out


def rank_value(v: Any) -> str | None:
    text = "" if v is None else str(v).strip()
    return (
        None
        if text.lower() in ("", "nan", "none", "null", "na", "unassigned", "unclassified")
        else text
    )


def core_clades(root: Node, group_of: dict[str, str]) -> dict[str, tuple[int, int]]:
    """``coreClades``: per lineage, the largest node pure for it, and how many tips it holds."""
    mixed = object()
    value: dict[int, Any] = {}
    count: dict[int, int] = {}
    best: dict[str, tuple[int, int]] = {}
    for node in _postorder(root):
        if not node.children:
            v: Any = group_of.get(node.name or "")
            c = 0 if v is None else 1
        else:
            v, c = None, 0
            for ch in node.children:
                cv = value[ch.id]
                if cv is None:
                    continue
                v = mixed if (cv is mixed or (v is not None and v != cv)) else cv
                c += count[ch.id]
        value[node.id], count[node.id] = v, c
        if v is not None and v is not mixed:
            prev = best.get(v)
            if prev is None or c >= prev[1]:
                best[v] = (node.id, c)
    return best


def induced(root: Node, leaf_for: dict[int, str]) -> Node | None:
    """``inducedOverClades``: one leaf per clade, single-child nodes folded away."""
    built: dict[int, Node | None] = {}
    counter = [0]
    for node in _postorder(root):
        counter[0] += 1
        if node.id in leaf_for:
            built[node.id] = Node(counter[0], leaf_for[node.id])
            continue
        kids = [built[c.id] for c in node.children if built.get(c.id) is not None]
        if not kids:
            built[node.id] = None
        elif len(kids) == 1:
            built[node.id] = kids[0]
        else:
            built[node.id] = Node(counter[0], None, kids)  # type: ignore[arg-type]
    return built[root.id]


def _leaves(node: Node) -> list[Node]:
    return [n for n in _postorder(node) if not n.children]


def ladderize(root: Node) -> None:
    sizes: dict[int, int] = {}
    for n in _postorder(root):
        sizes[n.id] = 1 if not n.children else sum(sizes[c.id] for c in n.children)
        n.children.sort(key=lambda c: sizes[c.id])


def cladogram(root: Node) -> tuple[dict[int, tuple[float, float]], int, list[Node]]:
    """Every leaf in one column, a node one level left of its deepest child."""
    height: dict[int, int] = {}
    for n in _postorder(root):
        height[n.id] = 0 if not n.children else 1 + max(height[c.id] for c in n.children)
    depth = height[root.id]
    order: list[Node] = []
    stack = [root]
    while stack:
        n = stack.pop()
        if not n.children:
            order.append(n)
        stack.extend(reversed(n.children))
    pts: dict[int, tuple[float, float]] = {
        leaf.id: (float(depth), float(i)) for i, leaf in enumerate(order)
    }
    for n in _postorder(root):
        if n.children:
            ys = [pts[c.id][1] for c in n.children]
            pts[n.id] = (float(depth - height[n.id]), (min(ys) + max(ys)) / 2)
    return pts, depth, order


def format_share(share: float) -> str:
    if share <= 0:
        return "0%"
    pct = share * 100
    if pct < 0.1:
        return "<0.1%"
    return f"{pct:.1f}%" if pct < 9.95 else f"{round(pct)}%"


def _phylo_summary(tile: Tile) -> Any:
    import plotly.graph_objects as go

    from .layout import category_colors

    cfg = tile.config
    rank = str(cfg.get("collapse_rank"))
    taxon_col, color_col = cfg.get("taxon_col") or "taxon", cfg.get("color_col")
    meta_dc = cfg.get("metadata_dc_id")
    tree_dc = cfg.get("tree_dc_id") or tile.dc_id
    if not meta_dc or not tree_dc:
        raise NothingToDraw("no tree or tip metadata bound")
    meta = tile.rows(
        [taxon_col, rank, color_col],
        dc_id=str(meta_dc),
        wf_id=cfg.get("metadata_wf_id"),
        full_load=True,
    )
    if meta.height == 0 or rank not in meta.columns:
        raise NothingToDraw("no tip metadata under the exported filters")
    group_of: dict[str, str] = {}
    colour_of: dict[str, str] = {}
    for row in meta.iter_rows(named=True):
        tip = str(row.get(taxon_col))
        g = rank_value(row.get(rank))
        if g is not None:
            group_of[tip] = g
        cv = rank_value(row.get(color_col)) if color_col else None
        if cv is not None:
            colour_of[tip] = cv
    root = parse_newick(tile.newick(str(tree_dc)))
    tips = [
        leaf
        for leaf in _leaves(root)
        if (leaf.name or "") in group_of or (leaf.name or "") in colour_of
    ]
    # The tips that survive the filters: a pruned tree, as the live view draws it.
    keep = {leaf.name for leaf in tips}
    leaf_names = [leaf.name for leaf in _leaves(root)]
    total_tips = sum(1 for name in leaf_names if name in keep)
    tip_count: dict[str, int] = {}
    votes: dict[str, dict[str, int]] = {}
    for name in leaf_names:
        g = group_of.get(name or "")
        if g is None or name not in keep:
            continue
        tip_count[g] = tip_count.get(g, 0) + 1
        cv = colour_of.get(name or "")
        if cv is not None:
            votes.setdefault(g, {})[cv] = votes.setdefault(g, {}).get(cv, 0) + 1
    if not tip_count:
        raise NothingToDraw("no tip of the tree carries a lineage")
    share: dict[str, float] = {}
    split: dict[str, dict[str, float]] | None = None
    split_values: list[str] = []
    if (
        cfg.get("size_by", "abundance") == "abundance"
        and cfg.get("abundance_dc_id")
        and cfg.get("abundance_col")
    ):
        a_val, a_s, a_split = (
            cfg.get("abundance_col"),
            cfg.get("abundance_sample_col"),
            cfg.get("abundance_split_col") if cfg.get("show_split", True) else None,
        )
        ab = tile.rows(
            [rank, a_val, a_s, a_split],
            dc_id=str(cfg["abundance_dc_id"]),
            wf_id=cfg.get("abundance_wf_id"),
            full_load=True,
        )
        sums: dict[str, float] = {}
        per: dict[str, dict[str, float]] = {}
        samples: set[str] = set()
        by_split: dict[str, set[str]] = {}
        total = 0.0
        for row in ab.iter_rows(named=True):
            try:
                v = float(row.get(a_val))
            except (TypeError, ValueError):
                continue
            if not v > 0:
                continue
            total += v
            smp = rank_value(row.get(a_s)) if a_s else None
            if smp is not None:
                samples.add(smp)
            sv = rank_value(row.get(a_split)) if a_split else None
            if sv is not None and smp is not None:
                by_split.setdefault(sv, set()).add(smp)
            g = rank_value(row.get(rank))
            if g is None:
                continue
            sums[g] = sums.get(g, 0.0) + v
            if sv is not None:
                per.setdefault(g, {})[sv] = per.setdefault(g, {}).get(sv, 0.0) + v
        denom = len(samples) if samples else total
        share = {g: v / denom for g, v in sums.items()} if denom else {}
        if a_split and samples:
            split_values = sorted(by_split)
            split = {g: {s: v / len(by_split[s]) for s, v in d.items()} for g, d in per.items()}

    def share_of(g: str) -> float:
        return share.get(g, 0.0) if share else tip_count.get(g, 0) / max(1, total_tips)

    placeable = [g for g in tip_count if not share or share_of(g) > 0]
    placeable.sort(key=lambda g: (-share_of(g), -tip_count[g], g))
    top = placeable[: max(1, int(cfg.get("top_n") or 8))]
    cores = core_clades(root, {k: v for k, v in group_of.items() if k in keep})
    leaf_for = {cores[g][0]: g for g in top if g in cores}
    summary = induced(root, leaf_for)
    if summary is None:
        raise NothingToDraw("no lineage could be placed on the tree")
    if cfg.get("ladderize", True):
        ladderize(summary)
    pts, depth, order = cladogram(summary)
    groups = [leaf.name or "" for leaf in order]

    def majority(g: str) -> str | None:
        v = votes.get(g)
        return sorted(v.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if v else None

    colour_values = [majority(g) or g for g in groups]
    # Coloured by the tip column when the tips carry one (a Kingdom), else by
    # the lineage itself: the dashboard's colours for whichever it is.
    colour_column = color_col if any(majority(g) for g in groups) else rank
    palette = category_colors(colour_values, pinned=tile.pinned_colors(colour_column))
    fig = go.Figure()
    xs: list[Any] = []
    ys: list[Any] = []
    stack = [summary]
    while stack:
        n = stack.pop()
        x0, y0 = pts[n.id]
        for c in n.children:
            x1, y1 = pts[c.id]
            xs += [x0, x0, x1, None]
            ys += [y0, y1, y1, None]
            stack.append(c)
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines",
            line={"color": "#adb5bd", "width": 1.5},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    shares = [share_of(g) for g in groups]
    smax = max(shares + [1e-9])
    size = [8 + 22 * (s / smax) ** 0.5 for s in shares]
    colours = [palette.get(v, "#868e96") for v in colour_values]
    hover = [
        f"<b>{g}</b><br>{format_share(s)} of the {'reads' if share else 'tips'}<br>"
        f"{tip_count[g]:,} tips, {cores[g][1]:,} in its core clade"
        for g, s in zip(groups, shares, strict=True)
    ]
    fig.add_trace(
        go.Scatter(
            x=[depth] * len(groups),
            y=list(range(len(groups))),
            mode="markers",
            marker={"size": size, "color": colours, "line": {"width": 0}},
            hovertext=hover,
            hoverinfo="text",
            showlegend=False,
        )
    )
    label_x = depth + 0.35
    for i, (g, s) in enumerate(zip(groups, shares, strict=True)):
        fig.add_annotation(
            x=label_x,
            y=i,
            text=f"<b>{g}</b>  <span style='color:#868e96'>{format_share(s)}</span>",
            showarrow=False,
            xanchor="left",
            font={"size": 12},
        )
    strip_x0 = depth + 3.2
    if split and split_values:
        for j, sv in enumerate(split_values):
            vals = [split.get(g, {}).get(sv, 0.0) for g in groups]
            vmax = max(vals + [1e-9])
            x = strip_x0 + j * 0.9
            fig.add_trace(
                go.Scatter(
                    x=[x] * len(groups),
                    y=list(range(len(groups))),
                    mode="markers",
                    marker={
                        "size": [4 + 16 * (v / vmax) ** 0.5 if v > 0 else 0 for v in vals],
                        "color": colours,
                        "opacity": 0.85,
                    },
                    hovertext=[
                        f"{g} · {sv}: {format_share(v)}" for g, v in zip(groups, vals, strict=True)
                    ],
                    hoverinfo="text",
                    showlegend=False,
                )
            )
            fig.add_annotation(
                x=x,
                y=-0.9,
                text=sv,
                showarrow=False,
                textangle=-35,
                font={"size": 10, "color": "#868e96"},
                yanchor="bottom",
            )
    right = strip_x0 + 0.9 * max(1, len(split_values))
    fig.update_xaxes(visible=False, range=[-0.3, right])
    fig.update_yaxes(visible=False, autorange="reversed", range=[len(groups) - 0.4, -1.8])
    fig.update_layout(height=max(260, 70 + 34 * len(groups)), hovermode="closest")
    others = len(placeable) - len(top)
    sub = f"Top {len(groups)} {rank} by {'share of reads' if share else 'share of tips'}"
    if others > 0:
        sub += f"; {others} more"
    sub += "; the full tree is a view of the same tile in the live dashboard"
    return figure_result(tile, fig, sub=sub)


register(
    NativeRenderer(
        kind="phylo_summary",
        output="interactive",
        how="a Plotly cladogram of the lineages at the collapse rank, sized by their share",
        render=_phylo_summary,
    )
)
