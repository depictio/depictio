"""``initial_categories``: the genome browser opens on named categories, not a row count.

``initial_tracks`` takes the first N manifest rows, so a template that reorders its
manifest silently changes what opens. ``initial_categories`` names the categories.
"""

from __future__ import annotations

from typing import Any

import pytest

from depictio.api.v1.services.jbrowse import config_builder, probe, render
from depictio.api.v1.services.jbrowse.config_builder import clear_index_exists_cache
from depictio.api.v1.services.jbrowse.tracks import TrackRow, TracksDC, track_key
from depictio.models.models.data_collections_types.genomic_tracks import DCGenomicTracksConfig

DC_ID = "646b0f3c1e4a2d7f8e5b8ca9"


def _row(track_id: str, sample: str | None, category: str | None, fmt: str = "vcf") -> TrackRow:
    uri = f"{track_id}.{fmt}"
    return TrackRow(
        key=track_key(uri),
        track_id=track_id,
        name=track_id,
        uri=uri,
        index_uri=None,
        fmt=fmt,
        sample=sample,
        category=category,
        row={"uri": uri},
    )


MANIFEST = [
    _row("S1.hc", "S1", "Small variants"),
    _row("S1.dv", "S1", "Small variants"),
    _row("S1.reads", "S1", "Alignments", "cram"),
    _row("S1.manta", "S1", "Structural variants"),
    _row("S1.tiddit", "S1", "Other"),
    _row("S2.hc", "S2", "Small variants"),
    _row("S2.reads", "S2", "Alignments", "cram"),
    _row("ref.genes", None, "Alignments", "bed"),
]


def _ids(rows: list[TrackRow]) -> list[str]:
    return [t.track_id for t in rows]


def test_the_categories_of_the_first_matching_sample_open() -> None:
    component = {"initial_categories": ["Small variants", "Alignments", "Structural variants"]}
    # The sample-less row rides with the sample; S2 is left for the picker.
    assert _ids(render._opening_tracks(component, MANIFEST)) == [
        "S1.hc",
        "S1.dv",
        "S1.reads",
        "S1.manta",
        "ref.genes",
    ]


def test_the_lead_sample_is_that_of_the_first_row_of_a_wanted_category() -> None:
    component = {"initial_categories": ["Alignments"]}
    manifest = [MANIFEST[5], MANIFEST[0], MANIFEST[6], MANIFEST[2]]
    assert _ids(render._opening_tracks(component, manifest)) == ["S2.reads"]


def test_no_categories_keeps_the_first_rows() -> None:
    assert _ids(render._opening_tracks({"initial_tracks": 2}, MANIFEST)) == ["S1.hc", "S1.dv"]
    assert _ids(render._opening_tracks({"initial_categories": []}, MANIFEST))[:5] == [
        "S1.hc",
        "S1.dv",
        "S1.reads",
        "S1.manta",
        "S1.tiddit",
    ]


def test_categories_no_row_has_open_nothing() -> None:
    assert render._opening_tracks({"initial_categories": ["Peaks"]}, MANIFEST) == []


@pytest.fixture
def seen(monkeypatch) -> list[list[str]]:
    monkeypatch.setattr(config_builder, "_probe_index", lambda uri, base: True)
    clear_index_exists_cache()
    monkeypatch.setattr(
        render, "tracks_by_key", lambda tdc, delta_version=None: {t.key: t for t in MANIFEST}
    )
    calls: list[list[str]] = []

    def first_region(tdc, tracks, delta_version=None):
        calls.append(_ids(tracks))
        return "chr22:100-200"

    monkeypatch.setattr(probe, "first_region", first_region)
    return calls


def test_the_payload_shows_the_selected_categories(seen) -> None:
    tdc = TracksDC(
        dc_id=DC_ID,
        wf_id="646b0f3c1e4a2d7f8e5b8c00",
        project_id="646b0f3c1e4a2d7f8e5b8c01",
        props=DCGenomicTracksConfig(format="tsv"),
        delta_location=None,
    )
    component: dict[str, Any] = {
        "show_annotation": False,
        "initial_categories": ["Small variants", "Structural variants"],
    }
    out = render.build_jbrowse_payload(component, tdc, None, "user-1")
    assert seen == [["S1.hc", "S1.dv", "S1.manta"]]
    assert out["opening"] == "data"
