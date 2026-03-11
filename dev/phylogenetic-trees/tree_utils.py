"""
Phylogenetic Tree Utilities.

Provides functions to parse Newick trees and compute node positions
for different layout types (rectangular, circular, radial, diagonal).
Uses Biopython's Bio.Phylo for tree parsing and traversal.

Coordinate computation approach:
- Rectangular: x = cumulative branch length, y = leaf order
- Circular: polar transform of rectangular coordinates
- Radial: equal-angle algorithm (unrooted)
- Diagonal: same as rectangular but with diagonal branch lines
"""

from __future__ import annotations

import math
from io import StringIO
from typing import Any

import pandas as pd
from Bio import Phylo
from Bio.Phylo.BaseTree import Clade, Tree


def parse_newick(newick_str: str) -> Tree:
    """Parse a Newick format string into a Biopython Tree object."""
    handle = StringIO(newick_str)
    tree = Phylo.read(handle, "newick")
    return tree


def parse_newick_file(filepath: str) -> Tree:
    """Parse a Newick file into a Biopython Tree object."""
    tree = Phylo.read(filepath, "newick")
    return tree


def get_leaf_names(tree: Tree) -> list[str]:
    """Return list of terminal node (leaf) names."""
    return [clade.name or f"leaf_{i}" for i, clade in enumerate(tree.get_terminals())]


def _assign_leaf_y_positions(tree: Tree) -> dict[Clade, float]:
    """Assign y-positions to leaves (evenly spaced) and internal nodes (midpoint)."""
    y_pos: dict[Clade, float] = {}
    terminals = tree.get_terminals()
    for i, leaf in enumerate(terminals):
        y_pos[leaf] = i

    # Internal nodes: y = midpoint of children's y range
    def _assign_internal(clade: Clade) -> float:
        if clade in y_pos:
            return y_pos[clade]
        child_ys = [_assign_internal(child) for child in clade.clades]
        y_pos[clade] = (min(child_ys) + max(child_ys)) / 2
        return y_pos[clade]

    _assign_internal(tree.root)
    return y_pos


def _assign_x_positions(tree: Tree) -> dict[Clade, float]:
    """Assign x-positions based on cumulative branch length from root."""
    x_pos: dict[Clade, float] = {}

    def _assign(clade: Clade, current_x: float) -> None:
        x_pos[clade] = current_x
        for child in clade.clades:
            branch_len = child.branch_length if child.branch_length else 0.0
            _assign(child, current_x + branch_len)

    _assign(tree.root, 0.0)
    return x_pos


def compute_rectangular_coords(tree: Tree) -> dict[str, Any]:
    """Compute rectangular (phylogram) layout coordinates.

    Returns:
        Dict with keys:
        - nodes: list of {name, x, y, is_leaf, branch_length}
        - edges: list of {x0, y0, x1, y1} for right-angle connections
    """
    x_pos = _assign_x_positions(tree)
    y_pos = _assign_leaf_y_positions(tree)

    nodes = []
    edges = []

    for clade in tree.find_clades(order="level"):
        name = clade.name or ""
        is_leaf = clade.is_terminal()
        nodes.append(
            {
                "name": name,
                "x": x_pos[clade],
                "y": y_pos[clade],
                "is_leaf": is_leaf,
                "branch_length": clade.branch_length or 0.0,
            }
        )

        # Right-angle edges: horizontal then vertical
        for child in clade.clades:
            # Horizontal line from parent to child's x at parent's y
            edges.append(
                {
                    "x0": x_pos[clade],
                    "y0": y_pos[clade],
                    "x1": x_pos[child],
                    "y1": y_pos[clade],
                }
            )
            # Vertical line from parent's y to child's y at child's x
            edges.append(
                {
                    "x0": x_pos[child],
                    "y0": y_pos[clade],
                    "x1": x_pos[child],
                    "y1": y_pos[child],
                }
            )

    return {"nodes": nodes, "edges": edges}


def compute_diagonal_coords(tree: Tree) -> dict[str, Any]:
    """Compute diagonal (cladogram-style) layout coordinates.

    Like rectangular, but branches go directly from parent to child
    (diagonal lines instead of right angles).
    """
    x_pos = _assign_x_positions(tree)
    y_pos = _assign_leaf_y_positions(tree)

    nodes = []
    edges = []

    for clade in tree.find_clades(order="level"):
        name = clade.name or ""
        is_leaf = clade.is_terminal()
        nodes.append(
            {
                "name": name,
                "x": x_pos[clade],
                "y": y_pos[clade],
                "is_leaf": is_leaf,
                "branch_length": clade.branch_length or 0.0,
            }
        )

        for child in clade.clades:
            edges.append(
                {
                    "x0": x_pos[clade],
                    "y0": y_pos[clade],
                    "x1": x_pos[child],
                    "y1": y_pos[child],
                }
            )

    return {"nodes": nodes, "edges": edges}


def compute_circular_coords(tree: Tree) -> dict[str, Any]:
    """Compute circular (radial phylogram) layout coordinates.

    Maps rectangular layout to polar coordinates:
    - r = x (branch distance from root)
    - theta = 2*pi * (y - y_min) / (y_max - y_min + gap)

    Returns same structure as compute_rectangular_coords but in Cartesian
    coordinates derived from the polar transform.
    """
    x_pos = _assign_x_positions(tree)
    y_pos = _assign_leaf_y_positions(tree)

    terminals = tree.get_terminals()
    n_leaves = len(terminals)
    y_min = min(y_pos.values())
    y_max = max(y_pos.values())
    y_range = y_max - y_min

    # Gap between first and last leaf in angular space
    gap = y_range / n_leaves if n_leaves > 1 else 1.0

    def to_polar(x: float, y: float) -> tuple[float, float]:
        """Convert rectangular (x, y) to Cartesian via polar transform."""
        r = x
        theta = 2 * math.pi * (y - y_min) / (y_range + gap) if y_range > 0 else 0
        return r * math.cos(theta), r * math.sin(theta)

    def theta_of(y: float) -> float:
        return 2 * math.pi * (y - y_min) / (y_range + gap) if y_range > 0 else 0

    nodes = []
    edges = []

    for clade in tree.find_clades(order="level"):
        cx, cy = to_polar(x_pos[clade], y_pos[clade])
        name = clade.name or ""
        is_leaf = clade.is_terminal()
        nodes.append(
            {
                "name": name,
                "x": cx,
                "y": cy,
                "is_leaf": is_leaf,
                "branch_length": clade.branch_length or 0.0,
            }
        )

        for child in clade.clades:
            # Arc from parent's angle to child's angle at parent's radius
            parent_theta = theta_of(y_pos[clade])
            child_theta = theta_of(y_pos[child])
            parent_r = x_pos[clade]
            child_r = x_pos[child]

            # Create arc points
            n_arc_points = max(10, int(abs(child_theta - parent_theta) * 20))
            arc_x = []
            arc_y = []
            for i in range(n_arc_points + 1):
                t = i / n_arc_points
                angle = parent_theta + t * (child_theta - parent_theta)
                arc_x.append(parent_r * math.cos(angle))
                arc_y.append(parent_r * math.sin(angle))

            # Radial line from arc endpoint to child
            child_cx, child_cy = to_polar(child_r, y_pos[child])
            arc_endpoint_x = parent_r * math.cos(child_theta)
            arc_endpoint_y = parent_r * math.sin(child_theta)

            edges.append(
                {
                    "arc_x": arc_x,
                    "arc_y": arc_y,
                    "radial_x": [arc_endpoint_x, child_cx],
                    "radial_y": [arc_endpoint_y, child_cy],
                }
            )

    return {"nodes": nodes, "edges": edges}


def compute_radial_coords(tree: Tree) -> dict[str, Any]:
    """Compute radial (equal-angle, unrooted) layout coordinates.

    Uses equal-angle algorithm: each subtree gets angular space
    proportional to its number of leaves.
    """
    # Assign angular spans
    node_angles: dict[Clade, float] = {}
    node_radii: dict[Clade, float] = {}

    def count_leaves(clade: Clade) -> int:
        if clade.is_terminal():
            return 1
        return sum(count_leaves(c) for c in clade.clades)

    def assign_angles(clade: Clade, start_angle: float, end_angle: float, depth: float) -> None:
        mid_angle = (start_angle + end_angle) / 2
        node_angles[clade] = mid_angle
        node_radii[clade] = depth

        if not clade.is_terminal():
            n_total = count_leaves(clade)
            current_start = start_angle
            for child in clade.clades:
                n_child = count_leaves(child)
                child_span = (end_angle - start_angle) * n_child / n_total
                child_depth = depth + (child.branch_length or 0.01)
                assign_angles(child, current_start, current_start + child_span, child_depth)
                current_start += child_span

    assign_angles(tree.root, 0, 2 * math.pi, 0)

    nodes = []
    edges = []

    for clade in tree.find_clades(order="level"):
        r = node_radii[clade]
        theta = node_angles[clade]
        cx = r * math.cos(theta)
        cy = r * math.sin(theta)

        name = clade.name or ""
        is_leaf = clade.is_terminal()
        nodes.append(
            {
                "name": name,
                "x": cx,
                "y": cy,
                "is_leaf": is_leaf,
                "branch_length": clade.branch_length or 0.0,
            }
        )

        for child in clade.clades:
            child_r = node_radii[child]
            child_theta = node_angles[child]
            child_cx = child_r * math.cos(child_theta)
            child_cy = child_r * math.sin(child_theta)
            edges.append(
                {
                    "x0": cx,
                    "y0": cy,
                    "x1": child_cx,
                    "y1": child_cy,
                }
            )

    return {"nodes": nodes, "edges": edges}


def load_metadata(filepath: str) -> pd.DataFrame:
    """Load metadata CSV file."""
    return pd.read_csv(filepath)


def merge_metadata_to_nodes(
    nodes: list[dict], metadata_df: pd.DataFrame, taxon_column: str = "taxon"
) -> list[dict]:
    """Merge metadata into node dicts based on name matching."""
    meta_dict = metadata_df.set_index(taxon_column).to_dict("index")
    for node in nodes:
        name = node.get("name", "")
        if name in meta_dict:
            node["metadata"] = meta_dict[name]
        else:
            node["metadata"] = {}
    return nodes
