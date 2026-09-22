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
