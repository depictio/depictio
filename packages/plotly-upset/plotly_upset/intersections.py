"""Core set intersection computation engine."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass
class IntersectionResult:
    """Result of intersection computation.

    Attributes
    ----------
    patterns:
        Each pattern is a tuple of 0/1 values indicating set membership.
    sizes:
        Count of rows matching each pattern (exclusive intersection).
    degrees:
        Number of sets participating in each pattern (sum of bits).
    row_indices:
        Mapping from pattern to the array of row indices matching it.
    set_names:
        Names of the sets (column names).
    """

    patterns: list[tuple[int, ...]]
    sizes: NDArray[np.intp]
    degrees: NDArray[np.intp]
    row_indices: dict[tuple[int, ...], NDArray[np.intp]]
    set_names: list[str]


def compute_intersections(
    binary_matrix: NDArray[np.int_],
    set_names: list[str],
) -> IntersectionResult:
    """Compute all exclusive set intersections.

    For each binary pattern, finds rows where every column matches
    the pattern exactly (1 = must be member, 0 = must NOT be member).

    For large numbers of sets (>15), uses observed-pattern grouping
    instead of enumerating all 2^n combinations.
    """
    n_sets = binary_matrix.shape[1]

    if n_sets > 15:
        return _compute_observed(binary_matrix, set_names)

    n_patterns = 2**n_sets
    patterns: list[tuple[int, ...]] = []
    sizes_list: list[int] = []
    row_indices: dict[tuple[int, ...], NDArray[np.intp]] = {}

    for i in range(n_patterns):
        pattern = tuple(int(b) for b in format(i, f"0{n_sets}b"))
        mask = np.all(binary_matrix == np.array(pattern), axis=1)
        idx = np.where(mask)[0]
        patterns.append(pattern)
        sizes_list.append(len(idx))
        row_indices[pattern] = idx

    sizes = np.array(sizes_list, dtype=np.intp)
    degrees = np.array([sum(p) for p in patterns], dtype=np.intp)

    return IntersectionResult(
        patterns=patterns,
        sizes=sizes,
        degrees=degrees,
        row_indices=row_indices,
        set_names=set_names,
    )


def _compute_observed(
    binary_matrix: NDArray[np.int_],
    set_names: list[str],
) -> IntersectionResult:
    """Optimized computation for large set counts — only considers observed patterns."""
    import pandas as pd

    df = pd.DataFrame(binary_matrix, columns=set_names)
    grouped = df.groupby(set_names, sort=False)

    patterns: list[tuple[int, ...]] = []
    sizes_list: list[int] = []
    row_indices: dict[tuple[int, ...], NDArray[np.intp]] = {}

    for pattern_vals, group in grouped:
        if not isinstance(pattern_vals, tuple):
            pattern_vals = (pattern_vals,)
        pattern = tuple(int(v) for v in pattern_vals)
        patterns.append(pattern)
        sizes_list.append(len(group))
        row_indices[pattern] = np.array(group.index, dtype=np.intp)

    sizes = np.array(sizes_list, dtype=np.intp)
    degrees = np.array([sum(p) for p in patterns], dtype=np.intp)

    return IntersectionResult(
        patterns=patterns,
        sizes=sizes,
        degrees=degrees,
        row_indices=row_indices,
        set_names=set_names,
    )


def filter_intersections(
    result: IntersectionResult,
    *,
    exclude_empty: bool = True,
    min_size: int = 0,
    max_size: int | None = None,
    min_degree: int = 0,
    max_degree: int | None = None,
) -> IntersectionResult:
    """Filter intersections by size and degree constraints."""
    keep = np.ones(len(result.patterns), dtype=bool)

    if exclude_empty:
        keep &= result.sizes > 0

    keep &= result.sizes >= min_size
    if max_size is not None:
        keep &= result.sizes <= max_size

    keep &= result.degrees >= min_degree
    if max_degree is not None:
        keep &= result.degrees <= max_degree

    indices = np.where(keep)[0]

    patterns = [result.patterns[i] for i in indices]
    sizes = result.sizes[indices]
    degrees = result.degrees[indices]
    row_indices = {result.patterns[i]: result.row_indices[result.patterns[i]] for i in indices}

    return IntersectionResult(
        patterns=patterns,
        sizes=sizes,
        degrees=degrees,
        row_indices=row_indices,
        set_names=result.set_names,
    )


def sort_intersections(
    result: IntersectionResult,
    *,
    sort_by: str = "cardinality",
    sort_order: str = "descending",
) -> IntersectionResult:
    """Sort intersections.

    Parameters
    ----------
    sort_by:
        ``"cardinality"`` (by intersection size),
        ``"degree"`` (by number of sets in intersection),
        ``"degree-cardinality"`` (primary sort by degree, secondary by
        cardinality within each degree group),
        or ``"input"`` (keep original order).
    sort_order:
        ``"descending"`` or ``"ascending"``.
    """
    if sort_by == "input":
        return result

    if sort_order == "descending":
        sign = -1
    elif sort_order == "ascending":
        sign = 1
    else:
        raise ValueError(f"Unknown sort_order: {sort_order!r}. Use 'descending' or 'ascending'.")

    if sort_by == "cardinality":
        order = np.argsort(sign * result.sizes)
    elif sort_by == "degree":
        order = np.argsort(sign * result.degrees)
    elif sort_by == "degree-cardinality":
        # Compound sort: primary by degree, secondary by cardinality
        # np.lexsort sorts by last key first, so (sizes, degrees) means
        # primary=degrees, secondary=sizes
        order = np.lexsort((sign * result.sizes, sign * result.degrees))
    else:
        raise ValueError(
            f"Unknown sort_by: {sort_by!r}. Use 'cardinality', 'degree', 'degree-cardinality', or 'input'."
        )

    patterns = [result.patterns[i] for i in order]
    sizes = result.sizes[order]
    degrees = result.degrees[order]
    row_indices = {result.patterns[i]: result.row_indices[result.patterns[i]] for i in order}

    return IntersectionResult(
        patterns=patterns,
        sizes=sizes,
        degrees=degrees,
        row_indices=row_indices,
        set_names=result.set_names,
    )


def compute_set_sizes(
    binary_matrix: NDArray[np.int_],
    set_names: list[str],
) -> dict[str, int]:
    """Count total members per set (column sums)."""
    sums = binary_matrix.sum(axis=0)
    return dict(zip(set_names, sums.tolist()))
