"""Per-family Newick trees laid out as rectangular tree segments.

Consumes the raw ``cmaple_tree_raw`` text scan (one file line per row, the file
in ``source_path``), one ``<step>/<sample>/<family>.treefile`` per family. A
phylogeny collection serves a single tree file, and a family run writes one
tree per family, so each tree is drawn from a table instead: the rectangular
(cladogram with branch lengths) layout of every tree, as line segments a code
figure joins with gaps.

Layout: tips take y = 0, 1, 2 ... in Newick order, an internal node sits at the
mean y of its children, x is the summed branch length from the root. Every
node contributes a horizontal segment from its parent's x to its own x at its
own y, and every internal node a vertical segment spanning its children.
Families are stacked (each tree starts one row below the previous one), so the
unfiltered table draws a forest and a family filter draws one tree.

Rows come in ``draw_order``; each segment is two point rows followed by a
separator row with null x / y, so a single line trace sorted by ``draw_order``
breaks between segments. ``is_tip`` is true only on the point row at a tip,
where ``node`` holds the member id.

Output schema:
    family : Utf8          family id (the file name without .treefile)
    sample : Utf8          sample the family was built from
    draw_order : Int64     row order of the drawing, global
    x : Float64            distance from the root (substitutions per site); null on separators
    y : Float64            vertical slot; null on separators
    node : Utf8            node label (member id at tips, support or empty inside)
    is_tip : Boolean       true on the point row that ends at a tip
    n_tips : Int64         tips of the family tree
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.protein_families import family_id, sample_from_path, texts_by_file

RAW_DC_TAG = "cmaple_tree_raw"
SOURCES: list[RecipeSource] = [RecipeSource(ref="trees", dc_ref=RAW_DC_TAG)]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "family": pl.Utf8,
    "sample": pl.Utf8,
    "draw_order": pl.Int64,
    "x": pl.Float64,
    "y": pl.Float64,
    "node": pl.Utf8,
    "is_tip": pl.Boolean,
    "n_tips": pl.Int64,
}

_TOKEN = re.compile(r"'(?:[^']|'')*'|[(),:;]|[^(),:;]+")


class _Node:
    __slots__ = ("children", "label", "length", "x", "y")

    def __init__(self) -> None:
        self.children: list[_Node] = []
        self.label = ""
        self.length = 0.0
        self.x = 0.0
        self.y = 0.0


def parse_newick(text: str) -> _Node | None:
    """Parse one Newick tree (labels, quoted labels, branch lengths, support)."""
    text = text.strip()
    if not text:
        return None
    root = _Node()
    stack: list[_Node] = []
    current = root
    expect_length = False
    for token in _TOKEN.findall(text):
        token_s = token.strip()
        if not token_s:
            continue
        if token_s == "(":
            child = _Node()
            current.children.append(child)
            stack.append(current)
            current = child
        elif token_s == ",":
            parent = stack[-1] if stack else root
            child = _Node()
            parent.children.append(child)
            current = child
        elif token_s == ")":
            current = stack.pop() if stack else root
        elif token_s == ":":
            expect_length = True
            continue
        elif token_s == ";":
            break
        elif expect_length:
            try:
                current.length = float(token_s)
            except ValueError:
                current.length = 0.0
        else:
            label = token_s
            if label.startswith("'") and label.endswith("'"):
                label = label[1:-1].replace("''", "'")
            current.label = label
        expect_length = False
    return root


def _layout(root: _Node, y_offset: float) -> list[_Node]:
    """Assign x (depth by branch length) and y (tip slots), return tips in order."""
    tips: list[_Node] = []
    stack: list[tuple[_Node, float, bool]] = [(root, 0.0, False)]
    while stack:
        node, x, visited = stack.pop()
        if not visited:
            node.x = x
            stack.append((node, x, True))
            for child in reversed(node.children):
                stack.append((child, x + max(child.length, 0.0), False))
        elif not node.children:
            node.y = y_offset + len(tips)
            tips.append(node)
        else:
            node.y = sum(c.y for c in node.children) / len(node.children)
    return tips


def _segments(root: _Node) -> list[tuple[float, float, float, float, str, bool]]:
    """``(x0, y0, x1, y1, node_label, ends_at_tip)`` for every edge and every fork."""
    out: list[tuple[float, float, float, float, str, bool]] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.children:
            ys = [c.y for c in node.children]
            out.append((node.x, min(ys), node.x, max(ys), node.label, False))
            for child in node.children:
                out.append((node.x, child.y, child.x, child.y, child.label, not child.children))
                stack.append(child)
    return out


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Two point rows and one separator row per tree segment, families stacked."""
    rows: list[dict] = []
    order = 0
    y_offset = 0.0
    seen: set[str] = set()
    for path, text in texts_by_file(sources["trees"]).items():
        family = family_id(path)
        root = parse_newick(text)
        if root is None or family in seen:
            continue
        seen.add(family)
        sample = sample_from_path(path)
        tips = _layout(root, y_offset)
        n_tips = len(tips)
        for x0, y0, x1, y1, label, ends_at_tip in _segments(root):
            base = {"family": family, "sample": sample, "n_tips": n_tips}
            rows.append(
                {**base, "draw_order": order, "x": x0, "y": y0, "node": "", "is_tip": False}
            )
            rows.append(
                {
                    **base,
                    "draw_order": order + 1,
                    "x": x1,
                    "y": y1,
                    "node": label,
                    "is_tip": ends_at_tip,
                }
            )
            rows.append(
                {**base, "draw_order": order + 2, "x": None, "y": None, "node": "", "is_tip": False}
            )
            order += 3
        y_offset += n_tips + 1
    if not rows:
        return pl.DataFrame(schema=EXPECTED_SCHEMA)
    return (
        pl.DataFrame(rows, schema_overrides={"x": pl.Float64, "y": pl.Float64})
        .select(list(EXPECTED_SCHEMA))
        .cast(EXPECTED_SCHEMA)  # type: ignore[arg-type]
    )
