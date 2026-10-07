"""`deseq2/qc_pca.py` and `deseq2/qc_sample_dists.py`: the pipeline's own QC tables.

Both are read with ``infer_schema_length: 0``, so every cell is text until the
recipe casts it. DESeq2 writes ``NA`` where it could not compute a value; one
such cell must cost that cell, not the ingest.
"""

from __future__ import annotations

from pathlib import Path

from depictio.recipes import execute_recipe

PCA = (
    '"sample"\t"PC1: 43% variance"\t"PC2: 27% variance"\n'
    '"s1"\t1.5\t-0.5\n'
    '"s2"\tNA\t0.25\n'
    '"s3"\t-1.5\t0.25\n'
)
DISTS = "sample\ts1\ts2\ts3\ns1\t0\t12.5\tNA\ns2\t12.5\t0\t7.25\ns3\tNA\t7.25\t0\n"


def test_qc_pca_keeps_the_row_around_an_na_cell(tmp_path: Path) -> None:
    (tmp_path / "deseq2_qc").mkdir()
    (tmp_path / "deseq2_qc" / "deseq2.pca.vals.txt").write_text(PCA)

    out = execute_recipe("deseq2/qc_pca.py", tmp_path)

    assert out["sample_id"].to_list() == ["s1", "s2", "s3"]
    assert out["dim_1"].to_list() == [1.5, None, -1.5]
    assert out["dim_2"].to_list() == [-0.5, 0.25, 0.25]
    assert out["dim_1_percent"].unique().to_list() == [43.0]
    assert out["dim_2_percent"].unique().to_list() == [27.0]


def test_qc_sample_dists_keeps_the_matrix_around_an_na_cell(tmp_path: Path) -> None:
    (tmp_path / "deseq2_qc").mkdir()
    (tmp_path / "deseq2_qc" / "deseq2.sample.dists.txt").write_text(DISTS)

    out = execute_recipe("deseq2/qc_sample_dists.py", tmp_path)

    assert out.columns == ["sample", "s1", "s2", "s3"]
    assert out["sample"].to_list() == ["s1", "s2", "s3"]
    assert out["s3"].to_list() == [None, 7.25, 0.0]
    assert out["s1"].to_list() == [0.0, 12.5, None]


def _qc_pca_module():
    import importlib.util

    path = Path(__file__).parents[2] / "catalog" / "deseq2" / "qc_pca.py"
    spec = importlib.util.spec_from_file_location("_deseq2_qc_pca", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_qc_pca_resolves_components_per_matrix_in_one_frame() -> None:
    """Two matrices stacked diagonally in one frame keep their own axes and percentages."""
    import polars as pl

    first = pl.DataFrame(
        {
            "sample": ["a1", "a2", "a3"],
            "PC1: 63% variance": ["1.0", "NA", "-1.0"],
            "PC2: 34% variance": ["0.5", "0.25", "-0.5"],
        }
    )
    second = pl.DataFrame(
        {
            "sample": ["b1", "b2"],
            "PC1: 91% variance": ["2.0", "-2.0"],
            "PC2: 7% variance": ["0.1", "-0.1"],
        }
    )
    frame = pl.concat([first, second], how="diagonal_relaxed").with_columns(
        pl.all().replace("NA", None)
    )

    out = _qc_pca_module().transform({"pca": frame})

    assert out.columns == [
        "sample_id",
        "dim_1",
        "dim_2",
        "dim_1_percent",
        "dim_2_percent",
        "pca_set",
    ]
    assert out["sample_id"].to_list() == ["a1", "a2", "a3", "b1", "b2"]
    assert out["dim_1"].to_list() == [1.0, None, -1.0, 2.0, -2.0]
    assert out["dim_2"].null_count() == 0
    assert out["dim_1_percent"].to_list() == [63.0, 63.0, 63.0, 91.0, 91.0]
    assert out["dim_2_percent"].to_list() == [34.0, 34.0, 34.0, 7.0, 7.0]
    assert out["pca_set"].n_unique() == 2
