"""Where the genome browser opens, and the config the wave-2 options write.

The opening order of ``build_jbrowse_payload``, the mate locus, the sashimi
arcs of an alignments track and the tracks the circular view may draw. The
manifest and the probe are faked: no Mongo, no storage.
"""

from __future__ import annotations

from typing import Any

import pytest

from depictio.api.v1.services.jbrowse import probe, render
from depictio.api.v1.services.jbrowse.config_builder import build_track_config
from depictio.api.v1.services.jbrowse.tracks import TrackRow, TracksDC, track_key
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig

DC_ID = "646b0f3c1e4a2d7f8e5b8ca9"
HG38_DEFAULT = "chr17:7,661,779-7,687,538"


def _row(uri: str, fmt: str, category: str | None = None, index: str | None = None) -> TrackRow:
    return TrackRow(
        key=track_key(uri),
        track_id=uri,
        name=uri,
        uri=uri,
        index_uri=index,
        fmt=fmt,
        category=category,
        row={"uri": uri},
    )


@pytest.fixture
def manifest(monkeypatch) -> list[TrackRow]:
    tracks = [
        _row("a.bw", "bigwig", "coverage"),
        _row("r.bam", "bam", "reads", "r.bam.bai"),
        _row("svs.vcf.gz", "vcf", "sv", "svs.vcf.gz.tbi"),
        _row("fusions.bed", "bed", "sv"),
        _row("calls.vcf.gz", "vcf", "snv", "calls.vcf.gz.tbi"),
    ]
    monkeypatch.setattr(
        render, "tracks_by_key", lambda tdc, delta_version=None: {t.key: t for t in tracks}
    )
    return tracks


def _tdc() -> TracksDC:
    return TracksDC(
        dc_id=DC_ID,
        wf_id="646b0f3c1e4a2d7f8e5b8c00",
        project_id="646b0f3c1e4a2d7f8e5b8c01",
        props=DCGenomicTracksConfig(format="tsv"),
        delta_location=None,
    )


def _payload(component: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
    component = {"show_annotation": False, **(component or {})}
    return render.build_jbrowse_payload(component, _tdc(), None, "user-1", **kw)


# --------------------------------------------------------------------------
# Opening order
# --------------------------------------------------------------------------

FIRST_CALL = {"locus": "chr4:1000-2000", "mate_locus": "chr4:9000-9500"}


class TestOpeningOrder:
    @pytest.fixture
    def probed(self, monkeypatch) -> list[Any]:
        seen: list[Any] = []

        def first_region(tdc, tracks, delta_version=None):
            seen.append([t.track_id for t in tracks])
            return "chr22:100-200"

        monkeypatch.setattr(probe, "first_region", first_region)
        return seen

    def test_the_filter_wins_over_everything(self, manifest, probed):
        out = _payload(
            {"location": "chr1:1-10"},
            locus="chr2:5-9",
            mate_locus="chr3:1-2",
            first_call=FIRST_CALL,
        )
        assert (out["location"], out["opening"]) == ("chr2:5-9", "filter")
        assert out["mate_location"] == "chr3:1-2"
        assert probed == []

    def test_the_yaml_location_comes_next_and_has_no_mate(self, manifest, probed):
        out = _payload({"location": "chr1:1-10"}, first_call=FIRST_CALL)
        assert (out["location"], out["opening"]) == ("chr1:1-10", "yaml")
        assert out["mate_location"] is None
        assert probed == []

    def test_then_the_first_call_with_its_mate(self, manifest, probed):
        out = _payload(first_call=FIRST_CALL)
        assert (out["location"], out["opening"]) == ("chr4:1000-2000", "first_call")
        assert out["mate_location"] == "chr4:9000-9500"
        assert probed == []

    def test_a_first_call_without_a_mate_leaves_it_empty(self, manifest):
        out = _payload(first_call={"locus": "chr4:1-2", "mate_locus": None})
        assert out["mate_location"] is None

    def test_then_the_first_region_holding_data_of_the_shown_tracks(self, manifest, probed):
        out = _payload({"initial_tracks": 2})
        assert (out["location"], out["opening"]) == ("chr22:100-200", "data")
        assert out["mate_location"] is None
        assert probed == [["a.bw", "r.bam"]]

    def test_the_preset_is_the_last_resort(self, manifest):
        out = _payload()  # the probe finds nothing (conftest)
        assert (out["location"], out["opening"]) == (HG38_DEFAULT, "preset")


# --------------------------------------------------------------------------
# Mate locus
# --------------------------------------------------------------------------


class TestMateLocus:
    SPEC = {
        "chrom_column": "chrom",
        "start_column": "pos",
        "padding": 100,
        "mate": {"chrom_column": "chrom_b", "start_column": "pos_b", "end_column": "end_b"},
    }

    def test_frames_the_mate_columns_with_the_same_padding(self):
        rows = [{"chrom": "4", "pos": 10, "chrom_b": "9", "pos_b": 1_000, "end_b": 1_200}]
        assert render.mate_locus_from_rows(rows, self.SPEC) == "9:900-1300"

    def test_end_defaults_to_the_start(self):
        spec = {**self.SPEC, "mate": {"chrom_column": "chrom_b", "start_column": "pos_b"}}
        rows = [{"chrom_b": "9", "pos_b": 500}]
        assert render.mate_locus_from_rows(rows, spec) == "9:400-600"

    def test_none_without_a_mate_or_with_unusable_cells(self):
        assert render.mate_locus_from_rows([{"chrom": "4"}], {"chrom_column": "chrom"}) is None
        rows = [{"chrom_b": None, "pos_b": 5}]
        assert render.mate_locus_from_rows(rows, self.SPEC) is None


# --------------------------------------------------------------------------
# Sashimi and circular tracks
# --------------------------------------------------------------------------


def _bam_conf(**kw: Any) -> dict[str, Any]:
    track = _row("r.bam", "bam", index="r.bam.bai")
    return build_track_config(track, "hg38", lambda t, role: f"/{role}", [], **kw)


class TestSashimi:
    def test_off_by_default_leaves_the_alignments_display_alone(self):
        assert "displays" not in _bam_conf()

    def test_arcs_sit_on_the_coverage_renderer_of_the_alignments_display(self):
        (display,) = _bam_conf(show_junctions=True)["displays"]
        assert display["type"] == "LinearAlignmentsDisplay"
        assert display["displayId"] == "r.bam-LinearAlignmentsDisplay"
        coverage = display["snpCoverageDisplay"]
        assert coverage["type"] == "LinearSNPCoverageDisplay"
        assert coverage["renderers"]["SNPCoverageRenderer"]["showArcs"] is True

    def test_it_composes_with_the_fetch_size_limit(self):
        (display,) = _bam_conf(show_junctions=True, fetch_size_limit=9)["displays"]
        coverage = display["snpCoverageDisplay"]
        assert coverage["fetchSizeLimit"] == 9
        assert coverage["renderers"]["SNPCoverageRenderer"]["showArcs"] is True
        assert display["pileupDisplay"]["fetchSizeLimit"] == 9

    def test_only_alignment_tracks_are_touched(self):
        track = _row("a.bw", "bigwig")
        conf = build_track_config(
            track, "hg38", lambda t, role: f"/{role}", [], show_junctions=True
        )
        assert "displays" not in conf

    def test_the_payload_applies_the_component_flag(self, manifest):
        out = _payload({"show_junctions": True, "initial_tracks": 5, "location": "chr1:1-9"})
        (bam,) = (t for t in out["tracks"] if t["trackId"] == "r.bam")
        assert bam["displays"][0]["snpCoverageDisplay"]["renderers"]["SNPCoverageRenderer"][
            "showArcs"
        ]
        plain = _payload({"initial_tracks": 5, "location": "chr1:1-9"})
        (bam,) = (t for t in plain["tracks"] if t["trackId"] == "r.bam")
        assert "displays" not in bam


class TestCircularTracks:
    def test_the_sv_category_by_default(self, manifest):
        out = _payload({"initial_tracks": 5, "location": "x"})
        assert out["sv_track_ids"] == ["svs.vcf.gz", "fusions.bed"]

    def test_other_categories_can_be_named(self, manifest):
        out = _payload({"initial_tracks": 5, "circular_categories": ["snv"], "location": "x"})
        assert out["sv_track_ids"] == ["calls.vcf.gz"]

    def test_only_tracks_that_were_built_are_listed(self, manifest):
        out = _payload({"initial_tracks": 5, "max_tracks": 5, "location": "x"})
        assert set(out["sv_track_ids"]) <= {t["trackId"] for t in out["tracks"]}

    def test_no_circular_category_no_ids(self, manifest):
        out = _payload({"initial_tracks": 5, "circular_categories": [], "location": "x"})
        assert out["sv_track_ids"] == []

    def test_the_read_pair_display_is_echoed(self, manifest):
        assert _payload({"read_pairs_display": "arcs", "location": "x"})["read_pairs_display"] == (
            "arcs"
        )
        assert _payload({"location": "x"})["read_pairs_display"] == "pileup"
