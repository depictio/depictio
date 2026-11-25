"""Newick parsing and pruning, with no phylogeny library.

A phylogeny DC with ``max_tips`` set is cut down at ingest to the tips its
metadata DC annotates (``process_phylogeny_data_collection``), and
``nf-core/ampliseq/scripts/prune_newick.py`` does the same by hand. Both use the
code below, which covers the Newick QIIME2 and the usual tree builders emit:
nested clades, labels, branch lengths, comments.

Every traversal is iterative and the tree is held in parallel arrays: a
ladderised bacterial tree is deep enough that a recursive walk overflows the
interpreter's stack well before it runs out of memory.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


class Tree:
    """A Newick tree flattened into parallel arrays, indexed by node."""

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

    def tips(self) -> list[str]:
        return [self.name[i] for i, kids in enumerate(self.children) if not kids]


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
            while j < n and text[j] not in ",);[":
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


def prune(tree: Tree, root: int, wanted: set[str], key: Callable[[str], str] | None = None) -> str:
    """Render the subtree spanning the tips in ``wanted``.

    ``key`` maps a tip label to the id matched against ``wanted`` (the label
    itself by default). A node left with a single child carries no topology, so
    it is dropped and its branch length folded into that child's; skipping this
    leaves long chains of degree-two nodes every renderer has to walk through.

    Raises ``ValueError`` when no tip of the tree is wanted.
    """
    key = key or (lambda name: name)
    keep = [False] * len(tree.parent)
    for idx, children in enumerate(tree.children):
        if not children and key(tree.name[idx]) in wanted:
            keep[idx] = True
    # Walk kept tips up to the root. `keep` doubles as the visited set, so each
    # edge is climbed once however many tips share the ancestor.
    for idx in [i for i, k in enumerate(keep) if k]:
        p = tree.parent[idx]
        while p >= 0 and not keep[p]:
            keep[p] = True
            p = tree.parent[p]

    if not keep[root]:
        raise ValueError("none of the requested tips is in the tree")

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


@dataclass(frozen=True)
class PruneResult:
    """What :func:`prune_to_tips` did: the Newick to store and the tip counts."""

    newick: str
    tips_before: int
    tips_after: int

    @property
    def pruned(self) -> bool:
        return self.tips_after < self.tips_before


def prune_to_tips(
    text: str,
    wanted: set[str],
    max_tips: int,
    key: Callable[[str], str] | None = None,
    parsed: tuple[Tree, int] | None = None,
) -> PruneResult:
    """Prune ``text`` to ``wanted`` when it has more than ``max_tips`` tips.

    A tree at or under the threshold comes back unchanged, byte for byte, so a
    small tree, or one pruned before ingest, is stored as it was written.
    ``parsed`` is ``parse_newick(text)`` when the caller already has it.
    """
    tree, root = parsed or parse_newick(text)
    before = count_tips(tree)
    if before <= max_tips:
        return PruneResult(text, before, before)
    newick = prune(tree, root, wanted, key)
    after, _ = parse_newick(newick)
    return PruneResult(newick + "\n", before, count_tips(after))
