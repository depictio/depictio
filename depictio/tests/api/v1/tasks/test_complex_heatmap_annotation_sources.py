"""Where a complex heatmap's column-annotation strips come from.

Two sources feed the same ``{annotation: {sample: value}}`` shape. The
declarative one joins the linked metadata DC per request; the fallback reads a
``_col_annotations_json`` column several ingest recipes bake into the matrix and
that, until this change, nothing on the advanced-viz path ever read.

The baked column is the delicate one: its values are positional against the
sample columns as they stood at ingest, so a shape change has to be detected
rather than zipped through.
"""

from __future__ import annotations

import json

import polars as pl

from depictio.api.v1.celery_tasks import (
    _BAKED_ANNOTATIONS_COL,
    _annotation_join_sources,
    _annotation_map_from_baked_column,
    _drawable_col_annotations,
)

_SAMPLES = ["GM12878_REP1", "GM12878_REP2", "K562_REP1", "K562_REP2"]


def _matrix(annotations: object, samples: list[str] | None = None) -> pl.DataFrame:
    """A tiny genes-by-samples matrix carrying a baked annotations column."""
    cols = samples if samples is not None else _SAMPLES
    data: dict[str, list] = {"gene_name": ["A", "B"]}
    for s in cols:
        data[s] = [1.0, 2.0]
    if annotations is not None:
        data[_BAKED_ANNOTATIONS_COL] = [annotations, annotations]
    return pl.DataFrame(data)


def _baked(values: list[str]) -> str:
    return json.dumps({"condition": {"values": values, "type": "categorical", "colors": {}}})


class TestBakedColumn:
    def test_positional_values_become_a_per_sample_map(self) -> None:
        df = _matrix(_baked(["GM12878", "GM12878", "K562", "K562"]))
        assert _annotation_map_from_baked_column(df, _SAMPLES) == {
            "condition": {
                "GM12878_REP1": "GM12878",
                "GM12878_REP2": "GM12878",
                "K562_REP1": "K562",
                "K562_REP2": "K562",
            }
        }

    def test_a_length_mismatch_is_skipped_rather_than_mislabelled(self) -> None:
        """Three values for four samples would slide every label one left."""
        df = _matrix(_baked(["GM12878", "GM12878", "K562"]))
        assert _annotation_map_from_baked_column(df, _SAMPLES) is None

    def test_a_matrix_without_the_column_yields_nothing(self) -> None:
        assert _annotation_map_from_baked_column(_matrix(None), _SAMPLES) is None

    def test_malformed_json_yields_nothing(self) -> None:
        assert _annotation_map_from_baked_column(_matrix("{not json"), _SAMPLES) is None

    def test_an_empty_frame_yields_nothing(self) -> None:
        df = _matrix(_baked(["GM12878"] * 4)).head(0)
        assert _annotation_map_from_baked_column(df, _SAMPLES) is None

    def test_recipe_colours_are_dropped_so_the_server_palette_applies(self) -> None:
        """The caller assigns Dark2; a per-recipe palette would break the
        row-vs-column distinction the two tracks rely on."""
        spec = json.dumps(
            {"condition": {"values": ["a", "a", "b", "b"], "colors": {"a": "#ff0000"}}}
        )
        out = _annotation_map_from_baked_column(_matrix(spec), _SAMPLES)
        assert out == {
            "condition": {
                "GM12878_REP1": "a",
                "GM12878_REP2": "a",
                "K562_REP1": "b",
                "K562_REP2": "b",
            }
        }


class TestDeclarativeJoin:
    """Resolution guards, before any Delta load is attempted.

    ``cols`` is deliberately NOT one of them: an empty pick still has to resolve,
    because the viz-controls picker is populated from the same load that would
    have drawn the strips.
    """

    def test_an_absent_or_incomplete_join_is_a_no_op(self) -> None:
        for join in (
            None,
            {},
            {"cols": ["condition"]},
            {"cols": ["condition"], "source_column": "sample"},
            {"cols": ["condition"], "source_column": "sample", "source_dc_id": "x"},
            {"cols": ["condition"], "source_dc_id": "x", "source_wf_id": "y"},
        ):
            assert _annotation_join_sources(join, _SAMPLES) == (None, [], [])


class TestSingleLevelStrips:
    """A constant column is declared but not drawn.

    ``read_type`` and ``strandedness`` are worth naming on an rnaseq template
    and are both constant in the megatest cohort. Painting them would add two
    lanes and two legend entries that separate no sample from any other.
    """

    _COLS = ["s1", "s2", "s3", "s4"]

    def test_a_constant_annotation_is_dropped(self) -> None:
        ordered, universes = _drawable_col_annotations(
            {"read_type": dict.fromkeys(self._COLS, "paired-end")}, self._COLS
        )
        assert ordered == {} and universes == {}

    def test_a_varying_annotation_survives_in_column_order(self) -> None:
        ordered, universes = _drawable_col_annotations(
            {"replicate": {"s1": "1", "s2": "2", "s3": "1", "s4": "2"}}, self._COLS
        )
        assert ordered == {"replicate": ["1", "2", "1", "2"]}
        assert universes == {"replicate": ["1", "2"]}

    def test_the_two_are_decided_independently(self) -> None:
        """The rnaseq case exactly: one strip drawn, one declined."""
        ordered, _ = _drawable_col_annotations(
            {
                "condition": {"s1": "A", "s2": "A", "s3": "B", "s4": "B"},
                "strandedness": dict.fromkeys(self._COLS, "reverse"),
            },
            self._COLS,
        )
        assert list(ordered) == ["condition"]

    def test_gaps_are_not_a_level(self) -> None:
        """One real value plus missing samples is still constant."""
        ordered, _ = _drawable_col_annotations(
            {"strandedness": {"s1": "reverse", "s3": "reverse"}}, self._COLS
        )
        assert ordered == {}

    def test_a_sample_with_no_metadata_row_gets_the_gap_marker(self) -> None:
        ordered, _ = _drawable_col_annotations(
            {"condition": {"s1": "A", "s2": "B", "s3": "A"}}, self._COLS
        )
        assert ordered["condition"] == ["A", "B", "A", "\u2014"]

    def test_a_non_mapping_entry_is_ignored(self) -> None:
        ordered, _ = _drawable_col_annotations({"bogus": ["A", "B"]}, self._COLS)
        assert ordered == {}
