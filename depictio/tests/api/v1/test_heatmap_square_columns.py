"""A filter on the rows of a sample-by-sample matrix cuts its columns too."""

from __future__ import annotations

import polars as pl

from depictio.api.v1.celery_tasks import _square_matrix_columns

COLUMNS = ["s1", "s2", "s3", "s4"]


def test_the_columns_follow_the_rows_a_filter_kept():
    kept = pl.DataFrame({"sample": ["s3", "s1"], "s1": [0.1, 0.0], "s3": [0.0, 0.1]})
    assert _square_matrix_columns(kept, "sample", COLUMNS) == ["s1", "s3"]


def test_a_matrix_of_taxa_by_samples_keeps_its_columns():
    taxa = pl.DataFrame({"Phylum": ["Metazoa"], "s1": [3]})
    assert _square_matrix_columns(taxa, "Phylum", COLUMNS) == COLUMNS


def test_every_row_kept_or_none_keeps_the_columns():
    every = pl.DataFrame({"sample": COLUMNS})
    assert _square_matrix_columns(every, "sample", COLUMNS) == COLUMNS
    assert _square_matrix_columns(every.head(0), "sample", COLUMNS) == COLUMNS
