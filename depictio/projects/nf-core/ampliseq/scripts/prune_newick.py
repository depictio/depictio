#!/usr/bin/env python3
"""Cut an ampliseq tree.nwk down to the ASVs worth drawing.

A full ampliseq run classifies every ASV it sees, and on a large cohort that is
two orders of magnitude more tips than a tree renders usefully: 127,845 on the
TREC Advanced Mobile Lab run against 2,683 in the bundled reference dataset. The
7.8 MB Newick alone stalls the browser before Phylocanvas draws anything.

The kept set comes from ``tree_metadata_canonical.top_taxa`` — the same ranking
the tip-metadata recipe applies to itself — so the pruned tree and the metadata
DC hold exactly the same taxa. Point the ingest at the result with
``--var TREE_FILE=<output>``; the pipeline's own tree.nwk is never written to.

Usage:
    python depictio/projects/nf-core/ampliseq/scripts/prune_newick.py \
        --data-root /path/to/ampliseq/results \
        --out /path/to/ampliseq/results/qiime2/phylogenetic_tree/tree.pruned.nwk

No phylogeny library is needed (or installed): the parser below is the whole of
Newick that QIIME2 emits — nested clades, labels, branch lengths, comments.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_RECIPE = _HERE.parent / "recipes" / "tree_metadata_canonical.py"

# Relative to --data-root; both are ampliseq's own fixed output layout.
_TREE_REL = "qiime2/phylogenetic_tree/tree.nwk"
_ASV_REL = "qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv"


def _load_recipe():
    """Import the recipe module by path — ``recipes/`` is not a package."""
    spec = importlib.util.spec_from_file_location("tree_metadata_canonical", _RECIPE)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable in-tree
        raise RuntimeError(f"cannot load {_RECIPE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Tree:
    """A Newick forest flattened into parallel arrays.

    Arrays rather than objects, and every traversal below is iterative: a
    ladderised bacterial tree is deep enough that a recursive walk overflows
    the interpreter's stack well before it runs out of memory.
    """

    __slots__ = ("parent", "name", "length", "children")

    def __init__(self) -> None:
        self.parent: list[int] = []
        self.name: list[str] = []
        self.length: list[float] = []
        self.children: list[list[int]] = []

    def add(self, parent: int) -> int:
        idx = len(self.parent)
        self.parent.append(parent)
        self.name.append("")
        self.length.append(0.0)
        self.children.append([])
        if parent >= 0:
            self.children[parent].append(idx)
        return idx


def parse_newick(text: str) -> tuple[Tree, int]:
    """Parse one Newick string; returns the tree and its root index."""
    tree = Tree()
    root = tree.add(-1)
    cur = root
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "(":
            cur = tree.add(cur)
            i += 1
        elif c == ",":
            cur = tree.add(tree.parent[cur])
            i += 1
        elif c == ")":
            cur = tree.parent[cur]
            i += 1
        elif c == ";":
            break
        elif c == ":":
            j = i + 1
            while j < n and text[j] not in ",);":
                j += 1
            try:
                tree.length[cur] = float(text[i + 1 : j].strip())
            except ValueError:
                tree.length[cur] = 0.0
            i = j
        elif c == "[":  # comment / NHX annotation
            j = text.find("]", i)
            i = n if j < 0 else j + 1
        elif c in " \t\r\n":
            i += 1
        else:
            j = i
            while j < n and text[j] not in "(),:;[":
                j += 1
            tree.name[cur] = text[i:j].strip().strip("'\"")
            i = j
    return tree, root


def _fmt(x: float) -> str:
    """Newick branch length, short but lossless enough for QIIME2's precision."""
    return f"{x:.10g}"


def prune(tree: Tree, root: int, wanted: set[str]) -> str:
    """Render the subtree spanning `wanted`, collapsing what is left over.

    A node with a single surviving child carries no topology, so it is dropped
    and its branch length folded into that child's. Skipping this leaves long
    chains of degree-two nodes that every renderer has to walk through.
    """
    keep = [False] * len(tree.parent)
    for idx, children in enumerate(tree.children):
        if not children and tree.name[idx] in wanted:
            keep[idx] = True
    # Walk kept tips up to the root. `keep` doubles as the visited set, so each
    # edge is climbed once no matter how many tips share the ancestor.
    for idx in [i for i, k in enumerate(keep) if k]:
        p = tree.parent[idx]
        while p >= 0 and not keep[p]:
            keep[p] = True
            p = tree.parent[p]

    if not keep[root]:
        raise SystemExit("no requested tip found in the tree — wrong tree or wrong ids?")

    rendered: dict[int, tuple[str, float]] = {}
    stack: list[tuple[int, bool]] = [(root, False)]
    while stack:
        node, expanded = stack.pop()
        kids = [c for c in tree.children[node] if keep[c]]
        if not expanded:
            stack.append((node, True))
            stack.extend((c, False) for c in kids)
            continue
        if not kids:
            rendered[node] = (tree.name[node], tree.length[node])
        elif len(kids) == 1:
            text, edge = rendered.pop(kids[0])
            rendered[node] = (text, edge + tree.length[node])
        else:
            body = ",".join(f"{t}:{_fmt(e)}" for t, e in (rendered.pop(c) for c in kids))
            rendered[node] = (f"({body}){tree.name[node]}", tree.length[node])
    return rendered[root][0] + ";"


def count_tips(tree: Tree) -> int:
    return sum(1 for c in tree.children if not c)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-root", type=Path, required=True, help="ampliseq results directory")
    ap.add_argument("--tree", type=Path, help=f"Newick to prune (default: <data-root>/{_TREE_REL})")
    ap.add_argument("--abundance", type=Path, help=f"ASV table (default: <data-root>/{_ASV_REL})")
    ap.add_argument("--out", type=Path, required=True, help="where to write the pruned Newick")
    ap.add_argument(
        "--max-tips",
        type=int,
        default=None,
        help="tips to keep (default: the recipe's own MAX_TIPS, so the two agree)",
    )
    args = ap.parse_args(argv)

    import polars as pl

    recipe = _load_recipe()
    max_tips = args.max_tips if args.max_tips is not None else recipe.MAX_TIPS
    if max_tips is None:
        print("MAX_TIPS is None and --max-tips was not given: nothing to prune", file=sys.stderr)
        return 2

    tree_path = args.tree or args.data_root / _TREE_REL
    asv_path = args.abundance or args.data_root / _ASV_REL
    for path in (tree_path, asv_path):
        if not path.exists():
            print(f"not found: {path}", file=sys.stderr)
            return 2

    # Text-only, like the recipe reads it: a sample column can stay all-zero
    # for tens of thousands of ASVs before a scientific-notation abundance
    # appears, and top_taxa casts what it needs anyway.
    asv = pl.read_csv(asv_path, separator="\t", infer_schema_length=0)
    wanted = set(recipe.top_taxa(asv, max_tips))

    tree, root = parse_newick(tree_path.read_text())
    before = count_tips(tree)
    newick = prune(tree, root, wanted)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(newick + "\n")

    after, _ = parse_newick(newick)
    print(
        f"{tree_path}: {before} tips ({tree_path.stat().st_size / 1e6:.1f} MB)\n"
        f"{args.out}: {count_tips(after)} tips ({args.out.stat().st_size / 1e6:.1f} MB)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
