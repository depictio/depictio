"""
Hi-C contact map data loading module.

Supports:
- .cool files (single-resolution cooler format, HDF5-based)
- .mcool files (multi-resolution cooler format, HDF5-based)
- Synthetic demo data generation for prototyping

Cool/mcool files are read directly via h5py without requiring the cooler library.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import h5py
import numpy as np
from numpy.typing import NDArray
from scipy import sparse


@dataclass
class HiCData:
    """Container for Hi-C contact map data."""

    matrix: NDArray[np.float64]
    chrom: str
    resolution: int
    start: int
    end: int
    normalization: str = "raw"
    genome_chroms: list[str] = field(default_factory=list)
    available_resolutions: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Cool / mcool reading (HDF5-based, no cooler dependency)
# ---------------------------------------------------------------------------


def list_mcool_resolutions(path: str) -> list[int]:
    """Return available resolutions in an .mcool file."""
    with h5py.File(path, "r") as f:
        if "resolutions" in f:
            return sorted(int(r) for r in f["resolutions"].keys())
        raise ValueError(f"No 'resolutions' group found in {path}")


def list_cool_chroms(path: str, resolution: int | None = None) -> list[str]:
    """Return chromosome names from a .cool or .mcool file."""
    with h5py.File(path, "r") as f:
        grp = _get_cool_group(f, resolution)
        names = grp["chroms/name"][:]
        return [n.decode() if isinstance(n, bytes) else n for n in names]


def load_cool_matrix(
    path: str,
    chrom: str,
    resolution: int | None = None,
    normalization: str = "raw",
) -> HiCData:
    """
    Load a single-chromosome contact matrix from a .cool or .mcool file.

    Parameters
    ----------
    path : str
        Path to the .cool or .mcool file.
    chrom : str
        Chromosome name (e.g. "chr1").
    resolution : int | None
        Resolution (bin size). Required for .mcool files.
    normalization : str
        Normalization to apply. "raw" returns raw counts.
        Other values (e.g. "KR", "VC", "ICE") are applied from
        the file's weight/bias vectors if available.
    """
    with h5py.File(path, "r") as f:
        grp = _get_cool_group(f, resolution)
        actual_res = _get_resolution(grp, resolution)

        # Chromosome extents
        chrom_names = [n.decode() if isinstance(n, bytes) else n for n in grp["chroms/name"][:]]
        chrom_lengths = grp["chroms/length"][:]
        chrom_idx = chrom_names.index(chrom)
        chrom_length = int(chrom_lengths[chrom_idx])

        # Bin range for this chromosome
        bin_chroms = grp["bins/chrom"][:]
        mask = bin_chroms == chrom_idx
        bin_indices = np.where(mask)[0]
        lo, hi = int(bin_indices[0]), int(bin_indices[-1]) + 1
        n_bins = hi - lo

        # Pixel data (COO sparse format)
        bin1 = grp["pixels/bin1_id"][:]
        bin2 = grp["pixels/bin2_id"][:]
        counts = grp["pixels/count"][:].astype(np.float64)

        # Filter to intra-chromosomal
        pixel_mask = (bin1 >= lo) & (bin1 < hi) & (bin2 >= lo) & (bin2 < hi)
        b1 = bin1[pixel_mask] - lo
        b2 = bin2[pixel_mask] - lo
        vals = counts[pixel_mask]

        # Apply normalization weights if available
        if normalization != "raw":
            weight_key = "bins/weight"
            if weight_key in grp:
                weights = grp[weight_key][lo:hi]
                w1 = weights[b1]
                w2 = weights[b2]
                valid = np.isfinite(w1) & np.isfinite(w2)
                vals[valid] *= w1[valid] * w2[valid]
                vals[~valid] = 0.0

        # Build symmetric dense matrix
        mat = sparse.coo_matrix((vals, (b1, b2)), shape=(n_bins, n_bins))
        mat = mat.toarray()
        mat = mat + mat.T - np.diag(mat.diagonal())

        # Available resolutions
        resolutions = []
        if path.endswith(".mcool"):
            try:
                resolutions = list_mcool_resolutions(path)
            except ValueError:
                pass

        return HiCData(
            matrix=mat,
            chrom=chrom,
            resolution=actual_res,
            start=0,
            end=chrom_length,
            normalization=normalization,
            genome_chroms=chrom_names,
            available_resolutions=resolutions,
        )


def _get_cool_group(f: h5py.File, resolution: int | None) -> h5py.Group:
    """Navigate to the correct HDF5 group for the given resolution."""
    if "resolutions" in f:
        # mcool format
        if resolution is None:
            resolutions = sorted(int(r) for r in f["resolutions"].keys())
            resolution = resolutions[0]
        return f[f"resolutions/{resolution}"]
    # Single .cool file — root group
    return f


def _get_resolution(grp: h5py.Group, resolution: int | None) -> int:
    """Determine the bin size from the cool group."""
    if resolution is not None:
        return resolution
    # Infer from bin start positions
    starts = grp["bins/start"][:10]
    if len(starts) > 1:
        return int(starts[1] - starts[0])
    return 1


# ---------------------------------------------------------------------------
# Synthetic demo data
# ---------------------------------------------------------------------------


def generate_synthetic_hic(
    n_bins: int = 500,
    resolution: int = 50_000,
    chrom: str = "chr1",
    decay_rate: float = 0.3,
    n_tads: int = 8,
    n_loops: int = 5,
    noise_level: float = 0.02,
    seed: int = 42,
) -> HiCData:
    """
    Generate a realistic synthetic Hi-C contact map.

    Features:
    - Distance-dependent decay (polymer physics)
    - TAD-like block structures
    - Loop/peak enrichments
    - Poisson-like noise
    """
    rng = np.random.default_rng(seed)

    # 1) Distance-dependent decay: P(s) ~ s^(-decay_rate) — vectorized
    idx = np.arange(n_bins)
    row, col = np.meshgrid(idx, idx, indexing="ij")
    dist_mat = np.abs(row - col).astype(np.float64)
    # Avoid division by zero on diagonal
    with np.errstate(divide="ignore"):
        mat = np.where(dist_mat == 0, 1.0, dist_mat ** (-decay_rate))
    mat *= 500.0

    # 2) TAD structures: enriched blocks along diagonal — vectorized
    tad_boundaries = sorted(rng.choice(range(20, n_bins - 20), size=n_tads, replace=False))
    tad_boundaries = [0, *tad_boundaries, n_bins]

    for k in range(len(tad_boundaries) - 1):
        tad_start = tad_boundaries[k]
        tad_end = tad_boundaries[k + 1]
        tad_size = tad_end - tad_start
        enrichment = rng.uniform(1.5, 3.0)
        tad_idx = np.arange(tad_start, tad_end)
        tr, tc = np.meshgrid(tad_idx, tad_idx, indexing="ij")
        tad_dist = np.abs(tr - tc).astype(np.float64)
        # Only upper triangle (including diagonal)
        upper = tr <= tc
        boost = np.where(
            upper & (tad_dist < tad_size),
            enrichment * np.exp(-tad_dist / (tad_size * 0.5)) * 50,
            0.0,
        )
        # Symmetrize
        boost = boost + boost.T - np.diag(boost.diagonal())
        mat[tad_start:tad_end, tad_start:tad_end] += boost

    # 3) Loop enrichments (off-diagonal peaks)
    for _ in range(n_loops):
        tad_idx_k = rng.integers(0, len(tad_boundaries) - 1)
        t_start = tad_boundaries[tad_idx_k]
        t_end = tad_boundaries[tad_idx_k + 1]
        if t_end - t_start < 10:
            continue
        li = rng.integers(t_start + 5, t_end - 5)
        lj = rng.integers(li + 5, min(li + 50, t_end))
        strength = rng.uniform(100, 500)
        di, dj = np.meshgrid(np.arange(-2, 3), np.arange(-2, 3), indexing="ij")
        ni = li + di
        nj = lj + dj
        valid = (ni >= 0) & (ni < n_bins) & (nj >= 0) & (nj < n_bins)
        g = strength * np.exp(-(di**2 + dj**2) / 2.0)
        mat[ni[valid], nj[valid]] += g[valid]
        mat[nj[valid], ni[valid]] += g[valid]

    # 4) Add Poisson-like noise
    mat = np.maximum(mat, 0)
    mat += rng.exponential(scale=noise_level * mat.mean(), size=mat.shape)
    mat = (mat + mat.T) / 2.0  # Ensure symmetry

    chrom_length = n_bins * resolution
    return HiCData(
        matrix=mat,
        chrom=chrom,
        resolution=resolution,
        start=0,
        end=chrom_length,
        normalization="synthetic",
        genome_chroms=[f"chr{i}" for i in range(1, 23)] + ["chrX"],
        available_resolutions=[10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000],
    )
