"""Regression tests for MultiQC general-stats columns that share a display title.

Two different MultiQC metrics can carry the same column ``title``: a pipeline
that runs both ``samtools stats`` and ``samtools flagstat`` over the same BAMs
reports ``reads_mapped`` and ``mapped_passed``, both titled "Reads mapped".

The de-duplication in ``_process_multiqc_data`` used to key on that display
title, so the second metric overwrote the first entry and ``rename()`` gave two
columns the same name. ``df[column]`` then returned a DataFrame instead of a
Series and ``pd.to_numeric`` raised ``arg must be a list, tuple, 1-d array, or
Series`` inside ``_multiqc_data_bars_colormap`` — a 500 from
``POST /dashboards/render_multiqc_general_stats`` for every nf-core template
whose report carries a duplicated title (atacseq, chipseq, cutandrun, rnaseq,
taxprofiler).
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from depictio.api.v1.services.multiqc.general_stats_payload import (
    _generate_data_bar_styles,
    _process_multiqc_data,
)


def _column_meta(title: str, namespace: str | None = None, suffix: str = "M") -> str:
    meta: dict = {
        "title": title,
        "description": f"{title} description",
        "scale": "GnBu",
        "format": "{:,.1f}",
        "suffix": suffix,
        "min": 0.0,
        "max": None,
        "hidden": False,
    }
    if namespace is not None:
        meta["namespace"] = namespace
    return json.dumps(meta)


def _write_parquet(tmp_path, metrics: list[dict], samples: tuple[str, ...]) -> str:
    """Write a minimal general-stats parquet in the shape MultiQC emits.

    ``metrics`` entries are ``{"metric", "section_key", "column_meta", "values"}``
    where ``values`` holds one number per entry of ``samples``.
    """
    rows: list[dict] = []
    for index, sample in enumerate(samples):
        for spec in metrics:
            rows.append(
                {
                    "anchor": "general_stats_table",
                    "type": "plot_input_row",
                    "section_key": spec["section_key"],
                    "sample": sample,
                    "metric": spec["metric"],
                    "val_mod": float(spec["values"][index]),
                    "column_meta": spec["column_meta"],
                }
            )
    path = tmp_path / "multiqc.parquet"
    pl.DataFrame(rows).write_parquet(path)
    return str(path)


# Two metrics, one shared title — the samtools stats / flagstat collision.
_COLLIDING_METRICS = [
    {
        "metric": "reads_mapped",
        "section_key": "samtools",
        "column_meta": _column_meta("Reads mapped", namespace="Samtools: stats"),
        "values": [10.0, 20.0, 30.0],
    },
    {
        "metric": "mapped_passed",
        "section_key": "samtools_3",
        "column_meta": _column_meta("Reads mapped", namespace="Samtools: flagstat"),
        "values": [11.0, 21.0, 31.0],
    },
]

_SAMPLES = ("sample_a", "sample_b", "sample_c")


@pytest.fixture
def colliding_parquet(tmp_path):
    return _write_parquet(tmp_path, _COLLIDING_METRICS, _SAMPLES)


@pytest.fixture
def distinct_parquet(tmp_path):
    metrics = [
        {
            "metric": "reads_mapped",
            "section_key": "samtools",
            "column_meta": _column_meta("Reads mapped", namespace="Samtools: stats"),
            "values": [10.0, 20.0, 30.0],
        },
        {
            "metric": "percent_duplication",
            "section_key": "picard",
            "column_meta": _column_meta("% Dups", namespace="Picard", suffix="%"),
            "values": [1.0, 2.0, 3.0],
        },
    ]
    return _write_parquet(tmp_path, metrics, _SAMPLES)


class TestDuplicateDisplayTitles:
    def test_both_metrics_survive_with_distinct_columns(self, colliding_parquet):
        df, _df_display, internal_to_display, *_ = _process_multiqc_data(
            colliding_parquet, show_hidden=True
        )

        metric_columns = [c for c in df.columns if c != "Sample Name"]
        assert len(metric_columns) == 2, f"a metric was swallowed: {list(df.columns)}"
        assert len(set(metric_columns)) == 2, f"duplicate internal names: {metric_columns}"
        # A duplicated column name makes df[col] a DataFrame, which is what broke
        # pd.to_numeric downstream.
        for column in metric_columns:
            assert df[column].ndim == 1

    def test_display_names_are_disambiguated_by_namespace(self, colliding_parquet):
        _df, _df_display, internal_to_display, *_ = _process_multiqc_data(
            colliding_parquet, show_hidden=True
        )

        display_names = {v for k, v in internal_to_display.items() if k != "Sample Name"}
        assert display_names == {
            "Reads mapped (M) (Samtools: stats)",
            "Reads mapped (M) (Samtools: flagstat)",
        }

    def test_values_stay_attached_to_the_right_metric(self, colliding_parquet):
        df, _df_display, internal_to_display, *_ = _process_multiqc_data(
            colliding_parquet, show_hidden=True
        )

        by_display = {internal_to_display[c]: c for c in df.columns if c != "Sample Name"}
        stats_col = by_display["Reads mapped (M) (Samtools: stats)"]
        flagstat_col = by_display["Reads mapped (M) (Samtools: flagstat)"]

        df_sorted = df.sort_values("Sample Name")
        assert list(df_sorted[stats_col]) == [10.0, 20.0, 30.0]
        assert list(df_sorted[flagstat_col]) == [11.0, 21.0, 31.0]

    def test_data_bar_styles_build_for_both_columns(self, colliding_parquet):
        """The exact call that raised the 500 before the fix."""
        (
            _df,
            df_for_display,
            internal_to_display,
            tools,
            column_metadata,
            percentage_columns,
            _groups,
        ) = _process_multiqc_data(colliding_parquet, show_hidden=True)

        styles, column_formats = _generate_data_bar_styles(
            df_for_display, tools, column_metadata, internal_to_display, percentage_columns
        )

        assert styles
        styled_columns = {style["if"]["column_id"] for style in styles}
        assert styled_columns == {c for c in df_for_display.columns if c != "Sample Name"}
        assert set(column_formats) == {
            "Reads mapped (M) (Samtools: stats)",
            "Reads mapped (M) (Samtools: flagstat)",
        }

    def test_section_key_disambiguates_when_namespace_is_absent(self, tmp_path):
        metrics = [
            {**spec, "column_meta": _column_meta("Reads mapped")} for spec in _COLLIDING_METRICS
        ]
        parquet = _write_parquet(tmp_path, metrics, _SAMPLES)

        _df, _df_display, internal_to_display, *_ = _process_multiqc_data(parquet, show_hidden=True)

        display_names = {v for k, v in internal_to_display.items() if k != "Sample Name"}
        assert display_names == {
            "Reads mapped (M) (samtools)",
            "Reads mapped (M) (samtools_3)",
        }

    def test_same_title_and_namespace_still_yields_two_columns(self, tmp_path):
        metrics = [
            {
                **spec,
                "section_key": "samtools",
                "column_meta": _column_meta("Reads mapped", namespace="Samtools: stats"),
            }
            for spec in _COLLIDING_METRICS
        ]
        parquet = _write_parquet(tmp_path, metrics, _SAMPLES)

        df, _df_display, internal_to_display, *_ = _process_multiqc_data(parquet, show_hidden=True)

        metric_columns = [c for c in df.columns if c != "Sample Name"]
        assert len(set(metric_columns)) == 2
        display_names = {v for k, v in internal_to_display.items() if k != "Sample Name"}
        assert display_names == {
            "Reads mapped (M) (Samtools: stats)",
            "Reads mapped (M) (Samtools: stats) (2)",
        }


class TestNonCollidingTitlesUnchanged:
    def test_titles_keep_their_plain_names(self, distinct_parquet):
        _df, _df_display, internal_to_display, *_ = _process_multiqc_data(
            distinct_parquet, show_hidden=True
        )

        display_names = {v for k, v in internal_to_display.items() if k != "Sample Name"}
        # No qualifier is appended when nothing collides — the templates that
        # already rendered must keep byte-identical headers.
        assert display_names == {"Reads mapped (M)", "% Dups (%)"}

    def test_percentage_columns_track_the_final_display_name(self, distinct_parquet):
        *_rest, percentage_columns, _groups = _process_multiqc_data(
            distinct_parquet, show_hidden=True
        )
        assert percentage_columns == ["% Dups (%)"]

    def test_internal_names_round_trip(self, distinct_parquet):
        df, _df_display, internal_to_display, *_ = _process_multiqc_data(
            distinct_parquet, show_hidden=True
        )
        assert set(internal_to_display) == set(df.columns)
        assert internal_to_display["Sample Name"] == "Sample Name"
