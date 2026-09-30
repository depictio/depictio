"""SpatialData stores read as a ``table`` data collection.

Stores are hand-built in tmp_path with zarr (v2 and v3) and pyarrow, writing
the AnnData / SpatialData encodings directly, so neither anndata nor
spatialdata is needed. The committed example store is checked against frozen
values of the spot table it was exported to.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import zarr

from depictio.cli.cli.utils import spatial_transforms as st
from depictio.cli.cli.utils.deltatables import read_files_lazy
from depictio.cli.cli.utils.scan import (
    _is_current_single_location,
    process_files,
    scan_run_for_multiple_data_collections,
)
from depictio.cli.cli.utils.spatialdata_table import (
    read_spatialdata_table,
    spatialdata_table_fingerprint,
    wkb_centroid,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.data_collections import DataCollection
from depictio.models.models.users import Permission, UserBase
from depictio.models.models.workflows import WorkflowConfig, WorkflowRun

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLE_STORE = REPO_ROOT / "depictio/projects/init/bioimage_examples/data/skin_spatialdata.zarr"
DC_ID = "646b0f3c1e4a2d7f8e5b8caa"
NOW = "2026-09-27 10:00:00"
OWNER = {"id": "507f1f77bcf86cd799439011", "email": "owner@example.org"}

XY = [{"name": "x", "type": "space"}, {"name": "y", "type": "space"}]
CYX = [
    {"name": "c", "type": "channel"},
    {"name": "y", "type": "space"},
    {"name": "x", "type": "space"},
]


def to_global(t: dict, axes: list[dict] = XY, cs: str = "global") -> dict:
    """An element transform into coordinate system ``cs`` (SpatialData style)."""
    names = "".join(a["name"] for a in axes)
    return {
        **t,
        "input": {"name": names, "axes": axes},
        "output": {"name": cs, "axes": axes},
    }


IDENTITY_XY = to_global({"type": "identity"})
IDENTITY_CYX = to_global({"type": "identity"}, CYX)


# ---------------------------------------------------------------------------
# Store builders
# ---------------------------------------------------------------------------


def _array(group, name: str, values, encoding: str = "array"):
    arr = group.create_array(name, data=np.asarray(values))
    arr.attrs.update({"encoding-type": encoding, "encoding-version": "0.2.0"})
    return arr


def _write_column(group, name: str, spec) -> None:
    """Write one AnnData dataframe column. ``spec`` is an array, or (encoding, ...)."""
    if not isinstance(spec, tuple):
        values = np.asarray(spec)
        _array(group, name, values, "string-array" if values.dtype.kind == "U" else "array")
        return
    kind, *rest = spec
    sub = group.require_group(name)
    if kind == "categorical":
        codes, categories = rest
        sub.attrs.update({"encoding-type": "categorical", "ordered": False})
        _array(sub, "codes", np.asarray(codes, dtype=np.int8))
        cats = np.asarray(categories)
        _array(sub, "categories", cats, "string-array" if cats.dtype.kind == "U" else "array")
    elif kind in ("nullable-integer", "nullable-boolean", "nullable-string-array"):
        values, mask = rest
        sub.attrs.update({"encoding-type": kind})
        _array(sub, "values", values, "string-array" if kind.endswith("string-array") else "array")
        _array(sub, "mask", np.asarray(mask, dtype=bool))
    else:
        sub.attrs.update({"encoding-type": kind})


def _write_dataframe(group, name: str, index: list[str], columns: dict) -> None:
    df = group.require_group(name)
    df.attrs.update(
        {
            "encoding-type": "dataframe",
            "encoding-version": "0.2.0",
            "_index": "_index",
            "column-order": list(columns),
        }
    )
    _array(df, "_index", np.asarray(index), "string-array")
    for col, spec in columns.items():
        _write_column(df, col, spec)


def _write_matrix(group, name: str, matrix) -> None:
    """Dense 2-D array, or ("csr_matrix" | "csc_matrix", dense) written sparse."""
    if not isinstance(matrix, tuple):
        _array(group, name, matrix)
        return
    kind, dense = matrix
    dense = np.asarray(dense)
    sub = group.require_group(name)
    sub.attrs.update({"encoding-type": kind, "shape": list(dense.shape)})
    major = dense if kind == "csr_matrix" else dense.T
    data, indices, indptr = [], [], [0]
    for row in major:
        nz = np.nonzero(row)[0]
        indices.extend(nz.tolist())
        data.extend(row[nz].tolist())
        indptr.append(len(indices))
    _array(sub, "data", np.asarray(data, dtype=dense.dtype))
    _array(sub, "indices", np.asarray(indices, dtype=np.int32))
    _array(sub, "indptr", np.asarray(indptr, dtype=np.int64))


def make_table(
    store: Path,
    *,
    zarr_format: int = 3,
    name: str = "table",
    index: list[str],
    obs: dict,
    var: list[str] | None = None,
    X=None,
    layers: dict | None = None,
    obsm_spatial=None,
    region: str | list[str] | None = None,
    region_key: str | None = None,
    instance_key: str | None = None,
) -> Path:
    root = zarr.open_group(str(store), mode="a", zarr_format=zarr_format)
    table = root.require_group("tables").require_group(name)
    attrs: dict = {"encoding-type": "anndata", "encoding-version": "0.1.0"}
    if region is not None:
        attrs.update(
            {
                "spatialdata-encoding-type": "ngff:regions_table",
                "region": region,
                "region_key": region_key,
                "instance_key": instance_key,
            }
        )
    table.attrs.update(attrs)
    _write_dataframe(table, "obs", index, obs)
    var = var or []
    _write_dataframe(table, "var", var, {})
    if X is not None:
        _write_matrix(table, "X", X)
    if layers:
        layers_group = table.require_group("layers")
        for layer_name, matrix in layers.items():
            _write_matrix(layers_group, layer_name, matrix)
    obsm = table.require_group("obsm")
    if obsm_spatial is not None:
        if isinstance(obsm_spatial, dict):
            _write_dataframe(obsm, "spatial", index, obsm_spatial)
        else:
            _array(obsm, "spatial", np.asarray(obsm_spatial, dtype=np.float64))
    return store


def wkb_point(x: float, y: float) -> bytes:
    return struct.pack("<BIdd", 1, 1, x, y)


def wkb_polygon(*rings: list[tuple[float, float]], order: str = "<") -> bytes:
    out = struct.pack(order + "BII", 1 if order == "<" else 0, 3, len(rings))
    for ring in rings:
        out += struct.pack(order + "I", len(ring))
        for x, y in ring:
            out += struct.pack(order + "dd", x, y)
    return out


def wkb_multipolygon(*polygons: bytes) -> bytes:
    return struct.pack("<BII", 1, 6, len(polygons)) + b"".join(polygons)


def make_shapes(
    store: Path,
    name: str,
    ids: list,
    geometries: list[bytes],
    transforms: list[dict] | None = None,
    *,
    zarr_format: int = 3,
    index_name: str = "instance_id",
) -> Path:
    root = zarr.open_group(str(store), mode="a", zarr_format=zarr_format)
    element = root.require_group("shapes").require_group(name)
    element.attrs.update(
        {
            "encoding-type": "ngff:shapes",
            "axes": ["x", "y"],
            "coordinateTransformations": transforms or [IDENTITY_XY],
            "spatialdata_attrs": {"version": "0.3"},
        }
    )
    table = pa.table(
        {"geometry": pa.array(geometries, type=pa.binary()), index_name: pa.array(ids)}
    )
    table = table.replace_schema_metadata(
        {
            "pandas": json.dumps({"index_columns": [index_name]}),
            "geo": json.dumps(
                {"primary_column": "geometry", "columns": {"geometry": {"encoding": "WKB"}}}
            ),
        }
    )
    element_dir = store / "shapes" / name
    pq.write_table(table, element_dir / "shapes.parquet")
    return element_dir


def make_image(
    store: Path,
    name: str,
    transforms: list[dict] | None = None,
    *,
    zarr_format: int = 3,
    level0: list[dict] | None = None,
) -> Path:
    root = zarr.open_group(str(store), mode="a", zarr_format=zarr_format)
    element = root.require_group("images").require_group(name)
    multiscales = [
        {
            "axes": CYX,
            "datasets": [
                {
                    "path": "s0",
                    "coordinateTransformations": level0 or [{"type": "scale", "scale": [1, 1, 1]}],
                }
            ],
            "coordinateTransformations": transforms or [IDENTITY_CYX],
        }
    ]
    if zarr_format == 3:
        element.attrs.update({"ome": {"version": "0.5", "multiscales": multiscales}})
    else:
        element.attrs.update({"multiscales": multiscales})
    return store / "images" / name


def spots_store(tmp_path: Path, name: str = "slide.zarr", zarr_format: int = 3, **table_kw) -> Path:
    """Three spots annotating one shapes region; no obsm, so coordinates come from shapes."""
    store = tmp_path / name
    make_shapes(
        store,
        "spots",
        ["s1", "s2", "s3"],
        [wkb_point(10, 20), wkb_point(30, 40), wkb_point(50, 60)],
        zarr_format=zarr_format,
    )
    kw = {
        "index": ["0", "1", "2"],
        "obs": {
            "spot_id": np.array(["s1", "s2", "s3"]),
            "cluster": ("categorical", [0, 1, -1], ["A", "B"]),
        },
        "region": "spots",
        "instance_key": "spot_id",
        **table_kw,
    }
    return make_table(store, zarr_format=zarr_format, **kw)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestAffineAlgebra:
    def test_compose_applies_first_then_second(self):
        m = st.compose(st.scale(2, 3), st.translation(1, -1))
        x, y = st.apply(m, np.array([1.0]), np.array([1.0]))
        assert (x[0], y[0]) == (3.0, 2.0)

    def test_invert_round_trips(self):
        m = st.compose(st.scale(2, 0.5), st.translation(5, 7))
        rot = (0.0, -1.0, 3.0, 1.0, 0.0, -2.0)
        full = st.compose(m, rot)
        xs, ys = st.apply(full, np.array([1.0, -4.0]), np.array([2.0, 9.0]))
        bx, by = st.apply(st.invert(full), xs, ys)
        np.testing.assert_allclose(bx, [1.0, -4.0])
        np.testing.assert_allclose(by, [2.0, 9.0])

    def test_singular_matrix_is_rejected(self):
        with pytest.raises(st.UnsupportedTransformError, match="not invertible"):
            st.invert(st.scale(0, 1))

    def test_scale_follows_axis_order(self):
        m, _ = st.from_ngff({"type": "scale", "scale": [1.0, 4.0, 2.0]}, ["c", "y", "x"])
        assert m == st.scale(2.0, 4.0)

    def test_affine_nested_and_flat_forms_agree(self):
        nested = {"type": "affine", "affine": [[0, 2, 5], [3, 0, 7], [0, 0, 1]]}
        flat = {"type": "affine", "affine": [0, 2, 5, 3, 0, 7]}
        assert st.from_ngff(nested, ["x", "y"])[0] == (0, 2, 5, 3, 0, 7)
        assert st.from_ngff(flat, ["x", "y"])[0] == (0, 2, 5, 3, 0, 7)

    def test_affine_on_cyx_axes_keeps_the_xy_part(self):
        t = {"type": "affine", "affine": [[1, 0, 0, 0], [0, 2, 0, 10], [0, 0, 3, 20]]}
        assert st.from_ngff(t, ["c", "y", "x"])[0] == (3, 0, 20, 0, 2, 10)

    def test_sequence_composes_in_order(self):
        seq = {
            "type": "sequence",
            "transformations": [
                {"type": "scale", "scale": [2, 2]},
                {"type": "translation", "translation": [1, 1]},
            ],
        }
        m, _ = st.from_ngff(seq, ["x", "y"])
        assert m == st.compose(st.scale(2, 2), st.translation(1, 1))

    def test_unknown_type_is_a_clear_error(self):
        with pytest.raises(st.UnsupportedTransformError, match="'rotation' is not supported"):
            st.from_ngff({"type": "rotation"}, ["x", "y"])

    def test_pick_system_prefers_global(self):
        assert st.pick_system(["aligned", "global"], ["aligned", "global"]) == "global"
        assert st.pick_system(["aligned"], ["other", "aligned"]) == "aligned"
        assert st.pick_system(["a"], ["b"]) is None


class TestWkbCentroid:
    def test_point(self):
        assert wkb_centroid(wkb_point(3.5, -2)) == (3.5, -2.0)

    def test_square_polygon(self):
        square = [(0, 0), (4, 0), (4, 2), (0, 2), (0, 0)]
        assert wkb_centroid(wkb_polygon(square)) == pytest.approx((2.0, 1.0))

    def test_big_endian_polygon(self):
        square = [(0, 0), (4, 0), (4, 2), (0, 2), (0, 0)]
        assert wkb_centroid(wkb_polygon(square, order=">")) == pytest.approx((2.0, 1.0))

    def test_hole_is_subtracted(self):
        outer = [(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)]
        hole = [(2, 0), (4, 0), (4, 4), (2, 4), (2, 0)]  # right half removed
        assert wkb_centroid(wkb_polygon(outer, hole)) == pytest.approx((1.0, 2.0))

    def test_multipolygon_is_area_weighted(self):
        small = wkb_polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
        big = wkb_polygon([(10, 0), (13, 0), (13, 3), (10, 3), (10, 0)])
        x, y = wkb_centroid(wkb_multipolygon(small, big))
        assert x == pytest.approx((0.5 * 1 + 11.5 * 9) / 10)
        assert y == pytest.approx((0.5 * 1 + 1.5 * 9) / 10)

    def test_point_z_drops_z(self):
        assert wkb_centroid(struct.pack("<BIddd", 1, 1001, 1, 2, 3)) == (1.0, 2.0)

    def test_linestring_is_rejected(self):
        with pytest.raises(ValueError, match="type 2 is not supported"):
            wkb_centroid(struct.pack("<BII", 1, 2, 0))


# ---------------------------------------------------------------------------
# Columns and encodings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("zarr_format", [2, 3])
class TestEncodings:
    def test_obs_encodings_and_column_order(self, tmp_path, zarr_format):
        store = make_table(
            tmp_path / "sample_A.zarr",
            zarr_format=zarr_format,
            index=["c0", "c1", "c2"],
            obs={
                "cluster": ("categorical", [1, -1, 0], ["low", "high"]),
                "label": np.array(["a", "b", "c"]),
                "count": ("nullable-integer", np.array([1, 2, 3]), [False, True, False]),
                "keep": ("nullable-boolean", np.array([True, False, True]), [False, False, True]),
                "tag": ("nullable-string-array", np.array(["t", "", "u"]), [False, True, False]),
                "flag": np.array([True, False, True]),
                "area": np.array([1.5, 2.5, 3.5]),
                "blob": ("awkward-array",),
            },
        )

        df = read_spatialdata_table(str(store), {})

        assert df.columns == [
            "sample",
            "obs_id",
            "cluster",
            "label",
            "count",
            "keep",
            "tag",
            "flag",
            "area",
        ]
        assert df["sample"].to_list() == ["sample_A"] * 3
        assert df["obs_id"].to_list() == ["c0", "c1", "c2"]
        assert df["cluster"].to_list() == ["high", None, "low"]
        assert df["cluster"].dtype == pl.Utf8
        assert df["label"].to_list() == ["a", "b", "c"]
        assert df["count"].to_list() == [1, None, 3]
        assert df["keep"].to_list() == [True, False, None]
        assert df["tag"].to_list() == ["t", None, "u"]
        assert df["flag"].dtype == pl.Boolean
        assert df["area"].to_list() == [1.5, 2.5, 3.5]

    def test_genes_from_dense_x(self, tmp_path, zarr_format):
        X = np.array([[1, 0, 2], [0, 3, 0]], dtype=np.int32)
        store = make_table(
            tmp_path / "s.zarr",
            zarr_format=zarr_format,
            index=["a", "b"],
            obs={},
            var=["g1", "g2", "g3"],
            X=X,
        )

        df = read_spatialdata_table(str(store), {"genes": ["g3", "g1"]})

        assert df.columns == ["sample", "obs_id", "g3", "g1"]
        assert df["g3"].to_list() == [2, 0]
        assert df["g1"].to_list() == [1, 0]

    @pytest.mark.parametrize("kind", ["csr_matrix", "csc_matrix"])
    def test_genes_from_sparse_x(self, tmp_path, zarr_format, kind):
        X = np.array([[1.0, 0, 2], [0, 3, 0], [4, 0, 0]])
        store = make_table(
            tmp_path / "s.zarr",
            zarr_format=zarr_format,
            index=["a", "b", "c"],
            obs={},
            var=["g1", "g2", "g3"],
            X=(kind, X),
        )

        df = read_spatialdata_table(str(store), {"genes": ["g1", "g2", "g3"]})

        assert df.select("g1", "g2", "g3").to_numpy().tolist() == X.tolist()

    def test_csr_is_read_in_blocks(self, tmp_path, zarr_format, monkeypatch):
        """Blocks smaller than a row still land every value in its row."""
        monkeypatch.setattr("depictio.cli.cli.utils.spatialdata_table._CSR_BLOCK_NNZ", 2)
        X = np.array([[1, 0, 2, 5], [0, 3, 0, 0], [4, 0, 6, 7], [0, 0, 0, 8]])
        store = make_table(
            tmp_path / "s.zarr",
            zarr_format=zarr_format,
            index=["a", "b", "c", "d"],
            obs={},
            var=["g1", "g2", "g3", "g4"],
            X=("csr_matrix", X),
        )

        df = read_spatialdata_table(str(store), {"genes": ["g4", "g1", "g3"]})

        assert df.select("g4", "g1", "g3").to_numpy().tolist() == X[:, [3, 0, 2]].tolist()

    def test_gene_columns_are_float64_whatever_the_x_dtype(self, tmp_path, zarr_format):
        """Stores of one DC may hold int counts or float values; one dtype keeps
        them numeric when the Files are aligned."""
        X = np.array([[1, 2], [3, 4]], dtype=np.int32)
        store = make_table(
            tmp_path / "s.zarr",
            zarr_format=zarr_format,
            index=["a", "b"],
            obs={},
            var=["g1", "g2"],
            X=X,
        )

        df = read_spatialdata_table(str(store), {"genes": ["g1", "g2"]})

        assert df.schema["g1"] == pl.Float64
        assert df["g2"].to_list() == [2.0, 4.0]

    def test_genes_from_a_layer(self, tmp_path, zarr_format):
        store = make_table(
            tmp_path / "s.zarr",
            zarr_format=zarr_format,
            index=["a", "b"],
            obs={},
            var=["g1"],
            X=np.array([[1], [2]]),
            layers={"counts": ("csr_matrix", np.array([[10], [0]]))},
        )

        df = read_spatialdata_table(str(store), {"genes": ["g1"], "layer": "counts"})

        assert df["g1"].to_list() == [10, 0]

    def test_obsm_coordinates(self, tmp_path, zarr_format):
        store = make_table(
            tmp_path / "s.zarr",
            zarr_format=zarr_format,
            index=["a", "b"],
            obs={},
            obsm_spatial=[[1.0, 2.0], [3.0, 4.0]],
        )

        df = read_spatialdata_table(str(store), {"coordinates": "obsm"})

        assert df.columns == ["sample", "obs_id", "x", "y"]
        assert df["x"].to_list() == [1.0, 3.0]
        assert df["y"].to_list() == [2.0, 4.0]

    def test_region_coordinates(self, tmp_path, zarr_format):
        store = spots_store(tmp_path, zarr_format=zarr_format)

        df = read_spatialdata_table(str(store), {})

        # instance_key is an obs column, so no obs_id.
        assert df.columns == ["sample", "spot_id", "cluster", "x", "y"]
        assert df["x"].to_list() == [10.0, 30.0, 50.0]
        assert df["y"].to_list() == [20.0, 40.0, 60.0]
        assert df["x"].dtype == pl.Float64


class TestColumns:
    def test_obsm_dataframe_encoding(self, tmp_path):
        store = make_table(
            tmp_path / "s.zarr",
            index=["a", "b"],
            obs={},
            obsm_spatial={"px": np.array([5.0, 6.0]), "py": np.array([7, 8])},
        )

        df = read_spatialdata_table(str(store), {})

        assert df["x"].to_list() == [5.0, 6.0]
        assert df["y"].to_list() == [7.0, 8.0]

    def test_auto_prefers_obsm_over_region(self, tmp_path):
        store = spots_store(tmp_path, obsm_spatial=[[1, 1], [2, 2], [3, 3]])

        df = read_spatialdata_table(str(store), {})

        assert df["x"].to_list() == [1.0, 2.0, 3.0]

    def test_auto_without_coordinates_omits_xy(self, tmp_path):
        store = make_table(tmp_path / "s.zarr", index=["a"], obs={"v": np.array([1])})

        df = read_spatialdata_table(str(store), {})

        assert df.columns == ["sample", "obs_id", "v"]

    def test_explicit_obsm_without_obsm_is_an_error(self, tmp_path):
        store = spots_store(tmp_path)

        with pytest.raises(ValueError, match="obsm\\['spatial'\\] is missing"):
            read_spatialdata_table(str(store), {"coordinates": "obsm"})

    def test_explicit_region_without_annotation_is_an_error(self, tmp_path):
        store = make_table(tmp_path / "s.zarr", index=["a"], obs={})

        with pytest.raises(ValueError, match="coordinates 'region' requested"):
            read_spatialdata_table(str(store), {"coordinates": "region"})

    def test_several_regions_join_by_region_and_instance(self, tmp_path):
        store = tmp_path / "s.zarr"
        make_shapes(store, "left", [1, 2], [wkb_point(1, 1), wkb_point(2, 2)])
        square = wkb_polygon([(10, 10), (12, 10), (12, 14), (10, 14), (10, 10)])
        make_shapes(store, "right", [1], [square])
        make_table(
            store,
            index=["r0", "r1", "r2", "r3"],
            obs={
                "region": ("categorical", [0, 1, 0, 1], ["left", "right"]),
                "cell_id": np.array([2, 1, 1, 9]),
            },
            region=["left", "right"],
            region_key="region",
            instance_key="cell_id",
        )

        df = read_spatialdata_table(str(store), {})

        assert df["x"].to_list() == [2.0, 11.0, 1.0, None]
        assert df["y"].to_list() == [2.0, 12.0, 1.0, None]

    def test_points_region_is_not_supported_yet(self, tmp_path):
        store = tmp_path / "s.zarr"
        zarr.open_group(str(store), mode="a").require_group("points").require_group("dots")
        make_table(
            store,
            index=["a"],
            obs={"i": np.array([0])},
            region="dots",
            instance_key="i",
        )

        with pytest.raises(ValueError, match="not supported yet"):
            read_spatialdata_table(str(store), {"coordinates": "region"})

    def test_unknown_gene_is_an_error(self, tmp_path):
        store = make_table(tmp_path / "s.zarr", index=["a"], obs={}, var=["g1"], X=[[1]])

        with pytest.raises(ValueError, match="nope"):
            read_spatialdata_table(str(store), {"genes": ["nope"]})

    def test_missing_table_is_an_error(self, tmp_path):
        store = make_table(tmp_path / "s.zarr", index=["a"], obs={})

        with pytest.raises(ValueError, match="tables/other"):
            read_spatialdata_table(str(store), {"table": "tables/other"})

    def test_obs_x_y_are_kept_as_obs_x_obs_y(self, tmp_path):
        store = make_table(
            tmp_path / "s.zarr",
            index=["a"],
            obs={"x": np.array([7.0]), "y": np.array([8.0])},
            obsm_spatial=[[1, 2]],
        )

        df = read_spatialdata_table(str(store), {})

        assert df.select("x", "y", "obs_x", "obs_y").row(0) == (1.0, 2.0, 7.0, 8.0)

    @pytest.mark.parametrize("column", ["sample"])
    def test_obs_column_colliding_with_an_output_column(self, tmp_path, column):
        store = make_table(
            tmp_path / "s.zarr",
            index=["a"],
            obs={column: np.array([1.0])},
            obsm_spatial=[[0, 0]],
        )

        with pytest.raises(ValueError, match=f"column '{column}'"):
            read_spatialdata_table(str(store), {})

    def test_gene_colliding_with_an_obs_column(self, tmp_path):
        store = make_table(
            tmp_path / "s.zarr",
            index=["a"],
            obs={"g1": np.array([1])},
            var=["g1"],
            X=[[5]],
        )

        with pytest.raises(ValueError, match="column 'g1' \\(gene\\)"):
            read_spatialdata_table(str(store), {"genes": ["g1"]})


# ---------------------------------------------------------------------------
# Transforms to image pixels
# ---------------------------------------------------------------------------


class TestImagePixels:
    def _xy(self, store: Path) -> list[tuple[float, float]]:
        df = read_spatialdata_table(str(store), {"image": "images/he"})
        return list(zip(df["x"].to_list(), df["y"].to_list()))

    def test_identity(self, tmp_path):
        store = spots_store(tmp_path)
        make_image(store, "he")

        assert self._xy(store)[0] == (10.0, 20.0)

    def test_image_scale(self, tmp_path):
        store = spots_store(tmp_path)
        # One image pixel is 0.5 global units (cyx order).
        make_image(store, "he", [to_global({"type": "scale", "scale": [1, 0.5, 0.5]}, CYX)])

        assert self._xy(store)[0] == pytest.approx((20.0, 40.0))

    def test_shapes_translation(self, tmp_path):
        store = tmp_path / "s.zarr"
        make_shapes(
            store,
            "spots",
            ["s1"],
            [wkb_point(1, 2)],
            [to_global({"type": "translation", "translation": [10, 100]})],
        )
        make_table(
            store, index=["0"], obs={"id": np.array(["s1"])}, region="spots", instance_key="id"
        )
        make_image(store, "he")

        assert self._xy(store) == [(11.0, 102.0)]

    def test_affine(self, tmp_path):
        store = tmp_path / "s.zarr"
        # 90 degree rotation plus shift: x' = -y + 5, y' = x + 1.
        affine = {"type": "affine", "affine": [[0, -1, 5], [1, 0, 1], [0, 0, 1]]}
        make_shapes(store, "spots", ["s1"], [wkb_point(2, 3)], [to_global(affine)])
        make_table(
            store, index=["0"], obs={"id": np.array(["s1"])}, region="spots", instance_key="id"
        )
        make_image(store, "he")

        assert self._xy(store) == [pytest.approx((2.0, 3.0))]

    def test_sequence_and_level0_scale(self, tmp_path):
        store = spots_store(tmp_path)
        seq = {
            "type": "sequence",
            "transformations": [
                {"type": "scale", "scale": [1, 2, 2]},
                {"type": "translation", "translation": [0, 4, 6]},
            ],
        }
        # level-0 pixels are 0.5 intrinsic units; intrinsic -> global = *2 then +(6, 4).
        make_image(
            store,
            "he",
            [to_global(seq, CYX)],
            level0=[{"type": "scale", "scale": [1, 0.5, 0.5]}],
        )

        # global = level0 * 0.5 * 2 + (6, 4) -> level0 = global - (6, 4)
        assert self._xy(store)[0] == pytest.approx((4.0, 16.0))

    def test_visium_like_hires_image(self, tmp_path):
        """Spots in full-resolution pixels; hires image downscaled by its scale factor."""
        store = spots_store(tmp_path)
        factor = 0.08
        make_image(
            store,
            "he",
            [to_global({"type": "scale", "scale": [1, 1 / factor, 1 / factor]}, CYX)],
        )

        assert self._xy(store) == [
            pytest.approx((10 * factor, 20 * factor)),
            pytest.approx((30 * factor, 40 * factor)),
            pytest.approx((50 * factor, 60 * factor)),
        ]

    def test_obsm_uses_the_region_element_transform(self, tmp_path):
        store = tmp_path / "s.zarr"
        make_shapes(
            store,
            "spots",
            ["s1"],
            [wkb_point(0, 0)],
            [to_global({"type": "translation", "translation": [5, 5]})],
        )
        make_table(
            store,
            index=["0"],
            obs={"id": np.array(["s1"])},
            region="spots",
            instance_key="id",
            obsm_spatial=[[1.0, 2.0]],
        )
        make_image(store, "he")

        assert self._xy(store) == [(6.0, 7.0)]

    def test_shared_non_global_system(self, tmp_path):
        store = tmp_path / "s.zarr"
        make_shapes(
            store,
            "spots",
            ["s1"],
            [wkb_point(1, 1)],
            [to_global({"type": "scale", "scale": [3, 3]}, cs="aligned")],
        )
        make_table(
            store, index=["0"], obs={"id": np.array(["s1"])}, region="spots", instance_key="id"
        )
        make_image(store, "he", [to_global({"type": "identity"}, CYX, cs="aligned")])

        assert self._xy(store) == [(3.0, 3.0)]

    def test_no_shared_system_is_an_error(self, tmp_path):
        store = spots_store(tmp_path)
        make_image(store, "he", [to_global({"type": "identity"}, CYX, cs="other")])

        with pytest.raises(ValueError, match="share no coordinate system"):
            self._xy(store)

    def test_unsupported_transform_is_an_error(self, tmp_path):
        store = spots_store(tmp_path)
        make_image(store, "he", [to_global({"type": "mapAxis", "mapAxis": {}}, CYX)])

        with pytest.raises(ValueError, match="'mapAxis' is not supported"):
            self._xy(store)


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


class TestFingerprint:
    def _store(self, tmp_path: Path) -> Path:
        store = spots_store(tmp_path)
        make_image(store, "he")
        points = zarr.open_group(str(store), mode="a").require_group("points").require_group("n")
        points.attrs.update({"v": 1})
        return store

    def test_changes_when_obs_changes(self, tmp_path):
        store = self._store(tmp_path)
        source = {"image": "images/he"}
        before = spatialdata_table_fingerprint(str(store), source)

        obs = zarr.open_group(str(store / "tables/table/obs"), mode="a")
        del obs["spot_id"]
        _array(obs, "spot_id", np.array(["s1", "s2", "sX"]), "string-array")

        assert spatialdata_table_fingerprint(str(store), source) != before

    def test_changes_when_region_geometry_or_image_metadata_changes(self, tmp_path):
        store = self._store(tmp_path)
        source = {"image": "images/he"}
        before = spatialdata_table_fingerprint(str(store), source)

        make_shapes(store, "spots", ["s1", "s2", "s3"], [wkb_point(0, 0)] * 3)
        after_shapes = spatialdata_table_fingerprint(str(store), source)
        make_image(store, "he", [to_global({"type": "scale", "scale": [1, 2, 2]}, CYX)])

        assert len({before, after_shapes, spatialdata_table_fingerprint(str(store), source)}) == 3

    def test_stable_when_an_unrelated_element_changes(self, tmp_path):
        store = self._store(tmp_path)
        source = {"image": "images/he"}
        before = spatialdata_table_fingerprint(str(store), source)

        points = zarr.open_group(str(store / "points" / "n"), mode="a")
        points.attrs.update({"v": 2})
        make_image(store, "other", [to_global({"type": "scale", "scale": [1, 9, 9]}, CYX)])

        assert spatialdata_table_fingerprint(str(store), source) == before

    def test_changes_with_the_dc_config(self, tmp_path):
        store = self._store(tmp_path)

        assert spatialdata_table_fingerprint(str(store), {}) != spatialdata_table_fingerprint(
            str(store), {"coordinates": "region"}
        )


# ---------------------------------------------------------------------------
# Scan + ingest wiring
# ---------------------------------------------------------------------------


@pytest.fixture
def cli_context(monkeypatch):
    """File validation runs its on-disk checks only in CLI context."""
    monkeypatch.setattr("depictio.models.models.files.DEPICTIO_CONTEXT", "cli")


def _permissions() -> Permission:
    return Permission(owners=[UserBase.model_validate(OWNER)])


def _table_dc(mode: str = "single", pattern: str = r".*\.zarr$", **spatialdata) -> DataCollection:
    scan = (
        {"mode": "single", "scan_parameters": {"filename": "unused.zarr"}}
        if mode == "single"
        else {"mode": "recursive", "scan_parameters": {"regex_config": {"pattern": pattern}}}
    )
    return DataCollection.model_validate(
        {
            "_id": DC_ID,
            "data_collection_tag": "spots",
            "config": {
                "type": "table",
                "scan": scan,
                "dc_specific_properties": {"format": "spatialdata", "spatialdata": spatialdata},
            },
        }
    )


def _run(location: Path) -> WorkflowRun:
    return WorkflowRun(
        workflow_id=PyObjectId(),
        run_tag="run",
        workflow_config_id=PyObjectId(),
        run_location=str(location),
        creation_time=NOW,
        last_modification_time=NOW,
        permissions=_permissions(),
    )


@pytest.mark.usefixtures("cli_context")
class TestScanAndIngest:
    def test_single_store_hash_is_the_fingerprint(self, tmp_path):
        store = spots_store(tmp_path)

        (result,) = process_files(
            path=str(store),
            run=_run(tmp_path),
            data_collection=_table_dc(),
            permissions=_permissions(),
            existing_files={},
            skip_regex=True,
        )

        assert result.file.file_location == str(store.resolve())
        assert result.file.file_hash == spatialdata_table_fingerprint(str(store), {})

    def test_store_without_the_table_is_skipped(self, tmp_path):
        store = tmp_path / "empty.zarr"
        make_image(store, "he")

        assert (
            process_files(
                path=str(store),
                run=_run(tmp_path),
                data_collection=_table_dc(),
                permissions=_permissions(),
                existing_files={},
                skip_regex=True,
            )
            == []
        )

    def test_stores_under_a_single_mode_folder_are_not_stale(self, tmp_path):
        folder = tmp_path / "stores"
        store = str((folder / "a.zarr").resolve())

        assert _is_current_single_location(_table_dc(), store, str(folder))

    def test_recursive_scan_registers_each_store_and_ingest_stacks_them(self, tmp_path):
        run_dir = tmp_path / "run_1"
        a = spots_store(run_dir / "a", "sample_A.zarr")
        b = spots_store(run_dir / "b", "sample_B.zarr", zarr_format=2)
        (run_dir / "notes.csv").write_text("x\n1\n")

        with (
            patch("depictio.cli.cli.utils.scan.api_create_files") as create,
            patch("depictio.cli.cli.utils.scan.api_delete_file"),
        ):
            scan_run_for_multiple_data_collections(
                run_location=str(run_dir),
                run_tag="run",
                workflow_config=WorkflowConfig(),
                data_collections=[_table_dc(mode="recursive")],
                all_existing_files={},
                workflow_id=PyObjectId(),
                existing_run=None,
                CLI_config=MagicMock(),
                permissions=_permissions(),
            )
        files = [f for call in create.call_args_list for f in call.kwargs["files"]]

        assert sorted(f.file_location for f in files) == sorted(
            [str(a.resolve()), str(b.resolve())]
        )

        frames = read_files_lazy(files, "spatialdata", {}, {"coordinates": "region"})
        df = pl.concat([lf.collect() for lf in frames]).sort("sample", "spot_id")
        assert df["sample"].to_list() == ["sample_A"] * 3 + ["sample_B"] * 3
        assert df["x"].to_list() == [10.0, 30.0, 50.0] * 2
        assert "depictio_run_id" in df.columns


# ---------------------------------------------------------------------------
# Committed example
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def df() -> pl.DataFrame:
    return read_spatialdata_table(
        str(EXAMPLE_STORE),
        {"image": "images/he", "genes": ["gene_A", "gene_B", "gene_C", "gene_D"]},
    )


@pytest.mark.skipif(not EXAMPLE_STORE.is_dir(), reason="example store not present")
class TestCommittedExample:
    """Frozen values of the spot table exported from the example store."""

    def test_total_counts_matches_the_genes(self, df):
        genes = df["gene_A"] + df["gene_B"] + df["gene_C"] + df["gene_D"]
        assert (df["total_counts"] == genes).all()

    def test_columns(self, df):
        assert df.columns == [
            "sample",
            "region",
            "spot_id",
            "cluster",
            "n_nuclei",
            "total_counts",
            "x",
            "y",
            "gene_A",
            "gene_B",
            "gene_C",
            "gene_D",
        ]

    @pytest.mark.parametrize(
        "row",
        [
            ("spot_0001", "C1", 1, 265.0, 9.0, 22, 7, 9, 2),
            ("spot_0100", "C1", 1, 41.0, 119.85, 21, 0, 18, 1),
            ("spot_0618", "C3", 0, 873.0, 618.68, 6, 4, 15, 11),
        ],
    )
    def test_rows(self, df, row):
        spot_id, cluster, n_nuclei, x, y, *genes = row
        got = df.filter(pl.col("spot_id") == spot_id).row(0, named=True)
        assert got["sample"] == "skin_spatialdata"
        assert (got["cluster"], got["n_nuclei"]) == (cluster, n_nuclei)
        # The exported CSV rounded coordinates to two decimals.
        assert math.isclose(got["x"], x, abs_tol=0.005)
        assert math.isclose(got["y"], y, abs_tol=0.005)
        assert [got[g] for g in ("gene_A", "gene_B", "gene_C", "gene_D")] == genes

    def test_aggregates(self, df):
        assert df.height == 618
        assert df["spot_id"].n_unique() == 618
        assert df["x"].sum() == pytest.approx(277050.0)
        assert df["y"].sum() == pytest.approx(196669.8, abs=618 * 0.005)
        assert df["n_nuclei"].sum() == 356
        assert [df[g].sum() for g in ("gene_A", "gene_B", "gene_C", "gene_D")] == [
            6328,
            5697,
            5371,
            4193,
        ]
        counts = dict(df.group_by("cluster").len().iter_rows())
        assert counts == {"C1": 69, "C2": 116, "C3": 142, "C4": 291}

    def test_region_and_obsm_coordinates_agree(self, df):
        region = read_spatialdata_table(
            str(EXAMPLE_STORE), {"image": "images/he", "coordinates": "region"}
        )
        assert region["x"].to_list() == df["x"].to_list()
        assert region["y"].to_list() == df["y"].to_list()
