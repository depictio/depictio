"""Read the AnnData table of a SpatialData store as one Polars frame.

A ``table`` DC with ``format: spatialdata`` registers each ``*.zarr`` store as
one File. At ingest the table element (``tables/<name>``, an AnnData group,
zarr v2 or v3) becomes one row per observation with, in this order:

1. ``sample``: the store's sample name (``bioimage_sample_name``).
2. ``obs_id`` (the obs index), only when the table's ``instance_key`` is not
   already an obs column; then the obs columns in their ``column-order``.
3. ``x`` / ``y`` (Float64) when coordinates are available: ``obsm/spatial``
   or the centroids of the annotated region geometries (``shapes/<name>``),
   in the image's level-0 pixels when ``image`` is set.
4. One column per requested gene, from ``X`` or ``layers/<layer>``.

The File hash of such a store is :func:`spatialdata_table_fingerprint`: it
covers the table subtree, the region elements and the image metadata, so
editing the table re-extracts it while touching an unrelated element does not.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
from typing import Any

import numpy as np
import polars as pl

from depictio.cli.cli.utils import spatial_transforms as st
from depictio.cli.cli_logging import logger
from depictio.models.models.data_collections_types.bioimage import bioimage_sample_name
from depictio.models.models.data_collections_types.table import SpatialDataTableSource

_METADATA_FILES = (".zattrs", ".zgroup", ".zarray", "zarr.json")
# Element groups a table region may live in; only shapes carry readable geometry.
_ELEMENT_GROUPS = ("shapes", "points", "labels", "images")


def _source(source: SpatialDataTableSource | dict) -> SpatialDataTableSource:
    if isinstance(source, SpatialDataTableSource):
        return source
    return SpatialDataTableSource.model_validate(source)


def _open_group(path: str):
    import zarr

    return zarr.open_group(path, mode="r", use_consolidated=False)


def _is_array(node: Any) -> bool:
    import zarr

    return isinstance(node, zarr.Array)


def _attrs(node: Any) -> dict:
    return dict(node.attrs)


# ---------------------------------------------------------------------------
# AnnData column encodings
# ---------------------------------------------------------------------------


def _is_text(values: np.ndarray) -> bool:
    return values.dtype.kind in "UOST"


def _text_list(values: np.ndarray) -> list[str | None]:
    out: list[str | None] = []
    for v in values.tolist():
        if v is None:
            out.append(None)
        elif isinstance(v, bytes):
            out.append(v.decode("utf-8"))
        else:
            out.append(str(v))
    return out


def _series(name: str, values: np.ndarray, mask: np.ndarray | None = None) -> pl.Series:
    series = (
        pl.Series(name, _text_list(values), dtype=pl.Utf8)
        if _is_text(values)
        else pl.Series(name, values)
    )
    if mask is not None:
        frame = pl.DataFrame({"v": series, "m": pl.Series(np.asarray(mask, dtype=bool))})
        series = frame.select(
            pl.when(pl.col("m")).then(None).otherwise(pl.col("v")).alias(name)
        ).to_series()
    return series


def _read_column(node: Any, name: str, where: str) -> pl.Series | None:
    """One AnnData dataframe column as a Series, or None (with a warning) when unsupported."""
    encoding = _attrs(node).get("encoding-type")
    if _is_array(node):
        if encoding not in (None, "array", "string-array"):
            logger.warning(f"Skipping {where}: unsupported encoding {encoding!r}")
            return None
        values = np.asarray(node[:])
        if values.ndim != 1:
            logger.warning(f"Skipping {where}: {values.ndim}-D array, expected 1-D")
            return None
        return _series(name, values)
    if encoding == "categorical":
        codes = np.asarray(node["codes"][:]).astype(np.int64)
        categories = _text_list(np.asarray(node["categories"][:]))
        lookup = np.array([*categories, None], dtype=object)
        return pl.Series(
            name, lookup[np.where(codes < 0, len(categories), codes)].tolist(), dtype=pl.Utf8
        )
    if encoding in ("nullable-integer", "nullable-boolean", "nullable-string-array"):
        return _series(name, np.asarray(node["values"][:]), np.asarray(node["mask"][:]))
    logger.warning(f"Skipping {where}: unsupported encoding {encoding!r}")
    return None


def _dataframe_index(group: Any, where: str) -> pl.Series:
    index_name = _attrs(group).get("_index", "_index")
    if index_name not in group:
        raise ValueError(f"{where} has no index column {index_name!r}")
    index = _read_column(group[index_name], "obs_id", f"{where}/{index_name}")
    if index is None:
        raise ValueError(f"{where} index {index_name!r} has an unsupported encoding")
    return index.cast(pl.Utf8)


def _read_scalar_or_list(node: Any) -> Any:
    return np.asarray(node[()]).tolist()


def _table_region_attrs(table: Any) -> tuple[list[str], str | None, str | None]:
    """The regions a table annotates, its ``region_key`` and ``instance_key``.

    SpatialData writes them on the table group; older stores keep them under
    ``uns/spatialdata_attrs``.
    """
    attrs = _attrs(table)
    region = attrs.get("region")
    region_key = attrs.get("region_key")
    instance_key = attrs.get("instance_key")
    if region is None and "uns" in table and "spatialdata_attrs" in table["uns"]:
        uns = table["uns"]["spatialdata_attrs"]
        if "region" in uns:
            region = _read_scalar_or_list(uns["region"])
        if "region_key" in uns:
            region_key = _read_scalar_or_list(uns["region_key"])
        if "instance_key" in uns:
            instance_key = _read_scalar_or_list(uns["instance_key"])
    regions = [region] if isinstance(region, str) else [str(r) for r in (region or [])]
    return regions, region_key, instance_key


# Non-zeros read per block when pulling genes out of a CSR matrix.
_CSR_BLOCK_NNZ = 10_000_000

# ---------------------------------------------------------------------------
# X / layers
# ---------------------------------------------------------------------------


def _gene_columns(table: Any, source: SpatialDataTableSource, n_obs: int) -> list[pl.Series]:
    if not source.genes:
        return []
    var_names = _dataframe_index(table["var"], "var").to_list()
    positions = {name: i for i, name in enumerate(var_names)}
    missing = [g for g in source.genes if g not in positions]
    if missing:
        raise ValueError(f"genes not found in the table's var names: {', '.join(missing)}")
    if source.layer:
        if "layers" not in table or source.layer not in table["layers"]:
            raise ValueError(f"layer {source.layer!r} not found under {source.table}/layers")
        matrix = table["layers"][source.layer]
        where = f"{source.table}/layers/{source.layer}"
    else:
        if "X" not in table:
            raise ValueError(f"{source.table} has no X matrix")
        matrix = table["X"]
        where = f"{source.table}/X"
    idxs = [positions[g] for g in source.genes]

    if _is_array(matrix):
        if len(matrix.shape) != 2 or matrix.shape[0] != n_obs:
            raise ValueError(f"{where} has shape {matrix.shape}, expected ({n_obs}, n_vars)")
        block = np.asarray(matrix.oindex[:, idxs], dtype=np.float64)
        return _float_columns(source.genes, block)

    encoding = _attrs(matrix).get("encoding-type")
    shape = tuple(_attrs(matrix).get("shape") or ())
    if encoding not in ("csr_matrix", "csc_matrix"):
        raise ValueError(f"{where} has unsupported encoding {encoding!r}")
    if len(shape) != 2 or shape[0] != n_obs:
        raise ValueError(f"{where} has shape {shape}, expected ({n_obs}, n_vars)")
    indptr = np.asarray(matrix["indptr"][:]).astype(np.int64)
    out = np.zeros((n_obs, len(idxs)), dtype=np.float64)
    if encoding == "csc_matrix":
        # One contiguous slice per requested gene.
        for k, j in enumerate(idxs):
            start, end = int(indptr[j]), int(indptr[j + 1])
            rows = np.asarray(matrix["indices"][start:end]).astype(np.int64)
            np.add.at(out[:, k], rows, np.asarray(matrix["data"][start:end]))
        return _float_columns(source.genes, out)
    # CSR: the requested genes are scattered over every row, so walk the
    # non-zeros in fixed-size blocks; peak memory follows the block, not nnz.
    lookup = np.full(int(shape[1]), -1, dtype=np.int64)
    lookup[idxs] = np.arange(len(idxs))
    nnz = int(indptr[-1])
    for start in range(0, nnz, _CSR_BLOCK_NNZ):
        end = min(start + _CSR_BLOCK_NNZ, nnz)
        cols = lookup[np.asarray(matrix["indices"][start:end])]
        hit = np.nonzero(cols >= 0)[0]
        if hit.size == 0:
            continue
        rows = np.searchsorted(indptr, hit + start, side="right") - 1
        values = np.asarray(matrix["data"][start:end])[hit]
        np.add.at(out, (rows, cols[hit]), values)
    return _float_columns(source.genes, out)


def _float_columns(genes: list[str], block: np.ndarray) -> list[pl.Series]:
    """Gene columns as Float64, whatever X's dtype: stores of one DC may differ
    (raw int counts in one, normalised floats in another), and mixed dtypes
    would be aligned to text across Files."""
    return [pl.Series(g, block[:, k], dtype=pl.Float64) for k, g in enumerate(genes)]


# ---------------------------------------------------------------------------
# Geometry (minimal WKB) and element transforms
# ---------------------------------------------------------------------------


class _WKBReader:
    def __init__(self, buf: bytes):
        self.buf = buf
        self.pos = 0

    def _unpack(self, fmt: str) -> tuple:
        size = struct.calcsize(fmt)
        if self.pos + size > len(self.buf):
            raise ValueError("truncated WKB geometry")
        out = struct.unpack_from(fmt, self.buf, self.pos)
        self.pos += size
        return out

    def geometry(self) -> tuple[int, list]:
        """``(base type, parts)``: points for 1/4, polygons (lists of rings) for 3/6."""
        (order,) = self._unpack("B")
        e = "<" if order == 1 else ">"
        (raw_type,) = self._unpack(e + "I")
        has_z = bool(raw_type & 0x80000000)
        has_m = bool(raw_type & 0x40000000)
        if raw_type & 0x20000000:  # EWKB SRID
            self._unpack(e + "I")
        base = raw_type & 0x0FFFFFFF
        iso_dims, base = divmod(base, 1000)
        has_z = has_z or iso_dims in (1, 3)
        has_m = has_m or iso_dims in (2, 3)
        dims = 2 + int(has_z) + int(has_m)

        def ring() -> np.ndarray:
            (n,) = self._unpack(e + "I")
            coords = self._unpack(e + "d" * (n * dims))
            return np.asarray(coords, dtype=np.float64).reshape(n, dims)[:, :2]

        if base == 1:
            return 1, [self._unpack(e + "d" * dims)[:2]]
        if base == 3:
            (n_rings,) = self._unpack(e + "I")
            return 3, [[ring() for _ in range(n_rings)]]
        if base in (4, 6):
            (n,) = self._unpack(e + "I")
            parts: list = []
            for _ in range(n):
                sub_type, sub_parts = self.geometry()
                if sub_type != base - 3:
                    raise ValueError(f"WKB multi-geometry {base} holds a type {sub_type}")
                parts.extend(sub_parts)
            return base, parts
        raise ValueError(f"WKB geometry type {base} is not supported (Point / Polygon only)")


def _ring_moments(ring: np.ndarray) -> tuple[float, float, float]:
    """``(|area|, |area| * cx, |area| * cy)`` of a closed or open ring (shoelace)."""
    x, y = ring[:, 0], ring[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y1 - x1 * y
    area = cross.sum() / 2.0
    if area == 0:
        return 0.0, 0.0, 0.0
    cx = ((x + x1) * cross).sum() / (6.0 * area)
    cy = ((y + y1) * cross).sum() / (6.0 * area)
    return abs(area), abs(area) * cx, abs(area) * cy


def wkb_centroid(buf: bytes) -> tuple[float, float]:
    """Point coordinates, or the area-weighted centroid of a (Multi)Polygon.

    Holes are subtracted. A degenerate (zero-area) polygon falls back to the
    mean of its exterior vertices; an empty geometry gives NaN.
    """
    kind, parts = _WKBReader(bytes(buf)).geometry()
    if kind in (1, 4):
        pts = np.asarray(parts, dtype=np.float64)
        if pts.size == 0:
            return float("nan"), float("nan")
        return float(pts[:, 0].mean()), float(pts[:, 1].mean())
    area = mx = my = 0.0
    vertices: list[np.ndarray] = []
    for rings in parts:
        if not rings:
            continue
        vertices.append(rings[0])
        for k, ring in enumerate(rings):
            a, ax, ay = _ring_moments(ring)
            sign = 1.0 if k == 0 else -1.0
            area += sign * a
            mx += sign * ax
            my += sign * ay
    if area > 0:
        return mx / area, my / area
    if not vertices:
        return float("nan"), float("nan")
    pts = np.concatenate(vertices)
    return float(pts[:, 0].mean()), float(pts[:, 1].mean())


def _read_shapes(element_dir: str) -> dict[str, tuple[float, float]]:
    """Instance id (as text) -> (x, y) of a shapes element's geometries."""
    import pyarrow.parquet as pq

    path = os.path.join(element_dir, "shapes.parquet")
    if not os.path.exists(path):
        raise ValueError(f"{element_dir} has no shapes.parquet")
    table = pq.read_table(path)
    meta = table.schema.metadata or {}
    geo = json.loads(meta.get(b"geo", b"{}") or b"{}")
    geometry_col = geo.get("primary_column", "geometry")
    if geometry_col not in table.column_names:
        raise ValueError(f"{path} has no geometry column {geometry_col!r}")

    pandas_meta = json.loads(meta.get(b"pandas", b"{}") or b"{}")
    index_cols = pandas_meta.get("index_columns") or []
    n = table.num_rows
    ids: list
    if index_cols and isinstance(index_cols[0], str) and index_cols[0] in table.column_names:
        ids = table.column(index_cols[0]).to_pylist()
    elif index_cols and isinstance(index_cols[0], dict) and index_cols[0].get("kind") == "range":
        rng = index_cols[0]
        ids = list(range(rng.get("start", 0), rng.get("stop", n), rng.get("step", 1)))
    elif "__index_level_0__" in table.column_names:
        ids = table.column("__index_level_0__").to_pylist()
    else:
        ids = list(range(n))

    geometries = table.column(geometry_col).to_pylist()
    out: dict[str, tuple[float, float]] = {}
    for iid, geom in zip(ids, geometries):
        if geom is None:
            continue
        if not isinstance(geom, bytes | bytearray | memoryview):
            raise ValueError(f"{path}: geometry is not WKB-encoded")
        out[str(iid)] = wkb_centroid(bytes(geom))
    return out


def _find_element(store_path: str, name: str) -> tuple[str, str] | None:
    for group in _ELEMENT_GROUPS:
        element_dir = os.path.join(store_path, group, name)
        if os.path.isdir(element_dir):
            return group, element_dir
    return None


def _element_systems(element_dir: str) -> dict[str, st.Affine2D]:
    """Coordinate system name -> transform from the element's intrinsic space.

    For a multiscale element (image, labels) the intrinsic space is level-0
    pixels: dataset 0's own scale / translation is applied first.
    """
    attrs = _attrs(_open_group(element_dir))
    if "coordinateTransformations" in attrs:
        axes = st.axis_names(attrs.get("axes")) or ["x", "y"]
        return st.to_systems(attrs["coordinateTransformations"], axes)
    multiscales = (attrs.get("ome") or {}).get("multiscales") or attrs.get("multiscales")
    if not multiscales:
        raise ValueError(f"{element_dir} carries no coordinate transformations")
    ms = multiscales[0]
    axes = st.axis_names(ms.get("axes"))
    level0 = st.IDENTITY
    datasets = ms.get("datasets") or []
    if datasets:
        for t in datasets[0].get("coordinateTransformations") or []:
            m, _ = st.from_ngff(t, axes)
            level0 = st.compose(level0, m)
    systems = st.to_systems(ms.get("coordinateTransformations"), axes) or {"global": st.IDENTITY}
    return {name: st.compose(level0, m) for name, m in systems.items()}


def _to_image_pixels(
    store_path: str, element_name: str | None, image_systems: dict[str, st.Affine2D], image: str
) -> st.Affine2D:
    """Map from an element's intrinsic coordinates to the image's level-0 pixels."""
    if element_name is None:
        cs = "global" if "global" in image_systems else next(iter(image_systems))
        logger.warning(
            f"No region element to place obsm coordinates; taking them as {image} "
            f"coordinate system {cs!r}"
        )
        return st.invert(image_systems[cs])
    found = _find_element(store_path, element_name)
    if found is None:
        raise ValueError(f"region element {element_name!r} not found in {store_path}")
    element_systems = _element_systems(found[1])
    cs = st.pick_system(list(element_systems), list(image_systems))
    if cs is None:
        raise ValueError(
            f"element {element_name!r} (systems {sorted(element_systems)}) and {image} "
            f"(systems {sorted(image_systems)}) share no coordinate system"
        )
    return st.compose(element_systems[cs], st.invert(image_systems[cs]))


# ---------------------------------------------------------------------------
# Coordinates
# ---------------------------------------------------------------------------


def _obsm_xy(table: Any, where: str) -> tuple[np.ndarray, np.ndarray]:
    node = table["obsm"]["spatial"]
    if _is_array(node):
        values = np.asarray(node[:], dtype=np.float64)
        if values.ndim != 2 or values.shape[1] < 2:
            raise ValueError(f"{where}/obsm/spatial has shape {values.shape}, expected (n, >=2)")
        return values[:, 0], values[:, 1]
    attrs = _attrs(node)
    if attrs.get("encoding-type") != "dataframe":
        raise ValueError(
            f"{where}/obsm/spatial has unsupported encoding {attrs.get('encoding-type')!r}"
        )
    order = list(attrs.get("column-order") or [])
    if len(order) < 2:
        raise ValueError(f"{where}/obsm/spatial dataframe has fewer than two columns")
    cols = []
    for name in order[:2]:
        series = _read_column(node[name], name, f"{where}/obsm/spatial/{name}")
        if series is None:
            raise ValueError(f"{where}/obsm/spatial/{name} has an unsupported encoding")
        cols.append(series.cast(pl.Float64).to_numpy())
    return cols[0], cols[1]


def _row_regions(
    obs: dict[str, pl.Series], regions: list[str], region_key: str | None, n_obs: int
) -> list[str | None]:
    if region_key and region_key in obs:
        return obs[region_key].cast(pl.Utf8).to_list()
    if len(regions) == 1:
        return [regions[0]] * n_obs
    raise ValueError(
        f"table annotates {len(regions)} regions but has no region_key column to tell them apart"
    )


def _region_xy(
    store_path: str,
    regions: list[str],
    row_regions: list[str | None],
    instance_ids: list[str | None],
) -> tuple[np.ndarray, np.ndarray]:
    lookups: dict[str, dict[str, tuple[float, float]]] = {}
    for name in regions:
        found = _find_element(store_path, name)
        if found is None:
            raise ValueError(f"region element {name!r} not found in {store_path}")
        group, element_dir = found
        if group != "shapes":
            raise ValueError(
                f"region {name!r} is a {group} element: only shapes regions give coordinates "
                "(points / labels regions are not supported yet)"
            )
        lookups[name] = _read_shapes(element_dir)
    xs = np.full(len(row_regions), np.nan)
    ys = np.full(len(row_regions), np.nan)
    missing = 0
    for i, (region, iid) in enumerate(zip(row_regions, instance_ids)):
        xy = lookups.get(region or "", {}).get(iid or "")
        if xy is None:
            missing += 1
            continue
        xs[i], ys[i] = xy
    if missing:
        logger.warning(f"{missing} observation(s) have no matching region geometry (x / y null)")
    return xs, ys


def _coordinates(
    store_path: str,
    table: Any,
    source: SpatialDataTableSource,
    obs: dict[str, pl.Series],
    n_obs: int,
) -> tuple[pl.Series, pl.Series] | None:
    where = f"{os.path.basename(store_path.rstrip('/'))}/{source.table}"
    regions, region_key, instance_key = _table_region_attrs(table)
    has_obsm = "obsm" in table and "spatial" in table["obsm"]
    region_ready = bool(regions) and bool(instance_key) and instance_key in obs

    mode = source.coordinates
    if mode == "auto":
        shapes_regions = region_ready and all(
            (_find_element(store_path, r) or ("",))[0] == "shapes" for r in regions
        )
        mode = "obsm" if has_obsm else "region" if shapes_regions else None
        if mode is None:
            logger.warning(f"{where}: no obsm['spatial'] and no shapes region; x / y omitted")
            return None
    elif mode == "obsm" and not has_obsm:
        raise ValueError(f"{where}: coordinates 'obsm' requested but obsm['spatial'] is missing")
    elif mode == "region" and not region_ready:
        raise ValueError(
            f"{where}: coordinates 'region' requested but the table has no region / "
            "instance_key annotation (or the instance_key column is missing from obs)"
        )

    row_regions: list[str | None]
    if mode == "obsm":
        xs, ys = _obsm_xy(table, where)
        if len(xs) != n_obs:
            raise ValueError(f"{where}/obsm/spatial has {len(xs)} rows, obs has {n_obs}")
        row_regions = _row_regions(obs, regions, region_key, n_obs) if regions else [None] * n_obs
    else:
        row_regions = _row_regions(obs, regions, region_key, n_obs)
        assert instance_key is not None
        instance_ids = obs[instance_key].cast(pl.Utf8).to_list()
        xs, ys = _region_xy(store_path, regions, row_regions, instance_ids)

    if source.image:
        image_dir = os.path.join(store_path, *source.image.split("/"))
        if not os.path.isdir(image_dir):
            raise ValueError(f"image element {source.image!r} not found in {store_path}")
        image_systems = _element_systems(image_dir)
        xs, ys = xs.copy(), ys.copy()
        # One transform per region element (rows of several regions may differ).
        keys = np.asarray([r or "" for r in row_regions], dtype=object)
        for key in dict.fromkeys(keys.tolist()):
            element: str | None = key or None
            if mode == "obsm" and element and _find_element(store_path, element) is None:
                element = None
            m = _to_image_pixels(store_path, element, image_systems, source.image)
            sel = keys == key
            xs[sel], ys[sel] = st.apply(m, xs[sel], ys[sel])

    return (
        pl.Series("x", xs, dtype=pl.Float64).fill_nan(None),
        pl.Series("y", ys, dtype=pl.Float64).fill_nan(None),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _table_dir(store_path: str, source: SpatialDataTableSource) -> str:
    table_dir = os.path.join(store_path, *source.table.split("/"))
    if not os.path.isdir(table_dir):
        raise ValueError(f"table element {source.table!r} not found in {store_path}")
    return table_dir


def read_spatialdata_table(store_path: str, source: SpatialDataTableSource | dict) -> pl.DataFrame:
    """The table element of a SpatialData store, one row per observation."""
    source = _source(source)
    table = _open_group(_table_dir(store_path, source))
    encoding = _attrs(table).get("encoding-type")
    if encoding != "anndata":
        raise ValueError(f"{source.table} in {store_path} is not an AnnData group ({encoding!r})")
    if "obs" not in table:
        raise ValueError(f"{source.table} in {store_path} has no obs dataframe")

    obs_group = table["obs"]
    obs_where = f"{source.table}/obs"
    index = _dataframe_index(obs_group, obs_where)
    n_obs = index.len()

    columns: dict[str, pl.Series] = {}
    origins: dict[str, str] = {}

    def add(series: pl.Series, origin: str) -> None:
        if series.name in columns:
            raise ValueError(
                f"column {series.name!r} ({origin}) collides with the {origins[series.name]} "
                f"column of the same name in {source.table} of {store_path}"
            )
        if series.len() != n_obs:
            raise ValueError(f"{origin} has {series.len()} rows, obs has {n_obs}")
        columns[series.name] = series
        origins[series.name] = origin

    store_name = os.path.basename(os.path.normpath(store_path))
    add(pl.Series("sample", [bioimage_sample_name(store_name)] * n_obs, dtype=pl.Utf8), "sample")

    obs: dict[str, pl.Series] = {}
    for name in _attrs(obs_group).get("column-order") or []:
        if name not in obs_group:
            raise ValueError(f"{obs_where} lists column {name!r} but does not store it")
        series = _read_column(obs_group[name], name, f"{obs_where}/{name}")
        if series is not None:
            obs[name] = series

    _, _, instance_key = _table_region_attrs(table)
    if instance_key not in obs:
        add(index, "obs index")
    for series in obs.values():
        add(series, "obs")

    xy = _coordinates(store_path, table, source, obs, n_obs)
    if xy is not None:
        add(xy[0], "coordinate")
        add(xy[1], "coordinate")

    for series in _gene_columns(table, source, n_obs):
        add(series, "gene")

    return pl.DataFrame(list(columns.values()))


def _hash_tree(digest: Any, root: str, rel_root: str) -> tuple[int, float]:
    """Feed every file under ``root`` (path, size, mtime; metadata content too)."""
    total, newest = 0, os.path.getmtime(root)
    for dirpath, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            stat = os.stat(path)
            rel = os.path.join(rel_root, os.path.relpath(path, root))
            digest.update(f"{rel}\0{stat.st_size}\0{stat.st_mtime_ns}\0".encode())
            if name in _METADATA_FILES:
                with open(path, "rb") as fh:
                    digest.update(fh.read())
            total += stat.st_size
            newest = max(newest, stat.st_mtime)
    return total, newest


def _hash_metadata(digest: Any, root: str, rel_root: str) -> None:
    for name in _METADATA_FILES:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            digest.update(f"{rel_root}/{name}\0".encode())
            with open(path, "rb") as fh:
                digest.update(fh.read())


def spatialdata_table_stats(
    store_path: str, source: SpatialDataTableSource | dict
) -> tuple[int, float, str]:
    """``(size, newest mtime, fingerprint)`` of what a table DC reads from a store.

    Covers the DC's spatialdata block, the table subtree, the geometry of the
    region elements it annotates (shapes / points) and the root metadata of
    the region (labels / images) and ``image`` elements. Elements the table
    does not reference are left out, so touching them does not re-extract.
    """
    source = _source(source)
    table_dir = _table_dir(store_path, source)
    store_name = os.path.basename(os.path.normpath(store_path))
    digest = hashlib.sha256(f"{store_name}\0{source.model_dump_json()}\0".encode())
    total, newest = _hash_tree(digest, table_dir, source.table)

    regions, _, _ = _table_region_attrs(_open_group(table_dir))
    for name in regions:
        found = _find_element(store_path, name)
        if found is None:
            continue
        group, element_dir = found
        rel = f"{group}/{name}"
        if group in ("shapes", "points"):
            size, mtime = _hash_tree(digest, element_dir, rel)
            total, newest = total + size, max(newest, mtime)
        else:
            _hash_metadata(digest, element_dir, rel)
    if source.image:
        image_dir = os.path.join(store_path, *source.image.split("/"))
        if os.path.isdir(image_dir):
            _hash_metadata(digest, image_dir, source.image)
    return total, newest, digest.hexdigest()


def spatialdata_table_fingerprint(store_path: str, source: SpatialDataTableSource | dict) -> str:
    """Change-detection hash (sha256 hex) of what a table DC reads from a store."""
    return spatialdata_table_stats(store_path, source)[2]
