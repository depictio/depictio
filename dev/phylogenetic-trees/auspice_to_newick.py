#!/usr/bin/env python3
"""Convert an Auspice JSON v2 tree to Newick format.

Auspice JSON v2 is the tree format used by Nextstrain/Nextclade.
This script extracts the tree topology and branch lengths and writes
a standard Newick string.

Usage:
    python auspice_to_newick.py input.auspice.json output.nwk

Only uses stdlib (json, sys) — no external dependencies.
"""

from __future__ import annotations

import json
import sys


def _node_to_newick(node: dict) -> str:
    """Recursively convert an Auspice JSON tree node to Newick format."""
    name = node.get("name", "")
    # Branch length: prefer div (divergence), fall back to branch_attrs
    branch_length = None
    branch_attrs = node.get("branch_attrs", {})
    if "length" in branch_attrs:
        branch_length = branch_attrs["length"]
    elif "div" in node:
        # div is cumulative divergence from root; we'd need parent div
        # to compute branch length. For simplicity, use it as-is for leaves.
        pass

    children = node.get("children", [])
    if children:
        child_strs = [_node_to_newick(c) for c in children]
        subtree = f"({','.join(child_strs)}){name}"
    else:
        subtree = name

    if branch_length is not None:
        return f"{subtree}:{branch_length}"
    return subtree


def _node_to_newick_with_div(node: dict, parent_div: float = 0.0) -> str:
    """Convert using divergence values to compute branch lengths."""
    name = node.get("name", "")
    node_div = node.get("node_attrs", {}).get("div", parent_div)
    branch_length = max(0.0, node_div - parent_div)

    children = node.get("children", [])
    if children:
        child_strs = [_node_to_newick_with_div(c, node_div) for c in children]
        subtree = f"({','.join(child_strs)}){name}"
    else:
        subtree = name

    return f"{subtree}:{branch_length:.6f}"


def auspice_to_newick(auspice_path: str, newick_path: str) -> None:
    """Read an Auspice JSON v2 file and write the tree as Newick."""
    with open(auspice_path) as f:
        data = json.load(f)

    tree = data.get("tree")
    if tree is None:
        print(f"Error: no 'tree' key found in {auspice_path}", file=sys.stderr)
        sys.exit(1)

    # Check if divergence values are available (preferred for branch lengths)
    has_div = "node_attrs" in tree and "div" in tree.get("node_attrs", {})
    if has_div:
        newick = _node_to_newick_with_div(tree) + ";"
    else:
        newick = _node_to_newick(tree) + ";"

    with open(newick_path, "w") as f:
        f.write(newick + "\n")

    # Count leaves for summary
    def count_leaves(n: dict) -> int:
        children = n.get("children", [])
        if not children:
            return 1
        return sum(count_leaves(c) for c in children)

    n_leaves = count_leaves(tree)
    print(f"  Converted {n_leaves} leaves from Auspice JSON to Newick")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.auspice.json> <output.nwk>", file=sys.stderr)
        sys.exit(1)
    auspice_to_newick(sys.argv[1], sys.argv[2])
