"""JBrowse configuration built for the genome browser component.

Covers the per-format track configs (adapters, explicit index locations,
displays), the assembly blocks, the merge order of presets / DC defaults /
component overrides, and the render payload (which tracks are shown, capped,
carried, and how they are annotated). The manifest is faked: no Mongo, no
Delta table.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from depictio.api.v1.services.jbrowse import render
from depictio.api.v1.services.jbrowse.assemblies import get_assembly_preset
from depictio.api.v1.services.jbrowse.config_builder import (
    BUILTIN_PRESETS,
    NARROWPEAK_COLUMNS,
    apply_fetch_size_limit,
    build_assembly_config,
    build_track_config,
    deep_merge,
    resolve_preset,
)
from depictio.api.v1.services.jbrowse.tracks import (
    TrackRow,
    TracksDC,
    manifest_rows,
    track_key,
)
from depictio.models.models.data_collections_types.genomic_tracks import (
    CustomAssembly,
    DCGenomicTracksConfig,
    infer_index_uri,
    infer_track_format,
)

DC_ID = "646b0f3c1e4a2d7f8e5b8ca9"


def _track(
    uri: str,
    fmt: str | None = None,
    index_uri: str | None = "infer",
    color: str | None = None,
    **row: Any,
) -> TrackRow:
    fmt = fmt or infer_track_format(uri)
    assert fmt
    if index_uri == "infer":
        index_uri = infer_index_uri(uri, fmt)
    key = track_key(uri)
    return TrackRow(
        key=key,
        track_id=row.pop("track_id", key),
        name=uri.rsplit("/", 1)[-1],
        uri=uri,
        index_uri=index_uri,
        fmt=fmt,
        color=color,
        sample=row.get("cell"),
        row={"uri": uri, **row},
    )


def _url_for(track: TrackRow, role: str) -> str:
    return f"/proxy/{track.key}/{role}"


def _build(track: TrackRow, layers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return build_track_config(track, "hg38", _url_for, layers or [])


def _all_locations(node: Any) -> list[dict[str, Any]]:
    """Every dict holding a ``uri`` anywhere in ``node``."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "uri" in node:
            found.append(node)
        for v in node.values():
            found += _all_locations(v)
    elif isinstance(node, list):
        for v in node:
            found += _all_locations(v)
    return found


# --------------------------------------------------------------------------
# build_track_config
# --------------------------------------------------------------------------


class TestTrackAdapters:
    def test_bigwig(self):
        conf = _build(_track("c1.bw"))
        assert conf["type"] == "QuantitativeTrack"
        assert conf["adapter"]["type"] == "BigWigAdapter"
        assert conf["adapter"]["bigWigLocation"]["uri"].endswith("/data")
        assert conf["assemblyNames"] == ["hg38"]
        assert conf["category"] == ["bigwig"]

    def test_plain_bed_is_read_whole(self):
        conf = _build(_track("calls.bed"))
        assert conf["type"] == "FeatureTrack"
        assert conf["adapter"] == {
            "type": "BedAdapter",
            "bedLocation": {
                "uri": conf["adapter"]["bedLocation"]["uri"],
                "locationType": "UriLocation",
            },
        }

    def test_bgzipped_bed_uses_tabix(self):
        conf = _build(_track("calls.bed.gz"))
        adapter = conf["adapter"]
        assert adapter["type"] == "BedTabixAdapter"
        assert adapter["bedGzLocation"]["uri"].endswith("/data")
        assert adapter["index"]["indexType"] == "TBI"
        assert adapter["index"]["location"]["uri"].endswith("/index")

    def test_bgzipped_bed_with_csi(self):
        conf = _build(_track("calls.bed.gz", index_uri="calls.bed.gz.csi"))
        assert conf["adapter"]["index"]["indexType"] == "CSI"

    def test_narrowpeak_column_names(self):
        conf = _build(_track("peaks.narrowPeak"))
        assert conf["adapter"]["type"] == "BedAdapter"
        assert conf["adapter"]["columnNames"] == NARROWPEAK_COLUMNS
        conf = _build(_track("peaks.narrowPeak.gz"))
        assert conf["adapter"]["type"] == "BedTabixAdapter"
        assert conf["adapter"]["columnNames"] == NARROWPEAK_COLUMNS

    def test_broadpeak_has_no_peak_column(self):
        conf = _build(_track("peaks.broadPeak"))
        assert conf["adapter"]["columnNames"] == NARROWPEAK_COLUMNS[:-1]

    def test_vcf(self):
        assert _build(_track("sv.vcf"))["adapter"]["type"] == "VcfAdapter"
        conf = _build(_track("sv.vcf.gz"))
        assert conf["type"] == "VariantTrack"
        assert conf["adapter"]["type"] == "VcfTabixAdapter"
        assert conf["adapter"]["vcfGzLocation"]["uri"].endswith("/data")
        assert conf["adapter"]["index"]["location"]["uri"].endswith("/index")

    def test_bam_bai_and_csi(self):
        conf = _build(_track("reads.bam"))
        assert conf["type"] == "AlignmentsTrack"
        assert conf["adapter"]["type"] == "BamAdapter"
        assert conf["adapter"]["index"]["indexType"] == "BAI"
        conf = _build(_track("reads.bam", index_uri="reads.bam.csi"))
        assert conf["adapter"]["index"]["indexType"] == "CSI"

    def test_cram(self):
        conf = _build(_track("reads.cram"))
        assert conf["adapter"]["type"] == "CramAdapter"
        assert conf["adapter"]["cramLocation"]["uri"].endswith("/data")
        assert conf["adapter"]["craiLocation"]["uri"].endswith("/index")

    def test_gff3_and_gtf(self):
        assert _build(_track("genes.gff3"))["adapter"]["type"] == "Gff3Adapter"
        assert _build(_track("genes.gff3.gz"))["adapter"]["type"] == "Gff3TabixAdapter"
        assert _build(_track("genes.gtf"))["adapter"]["type"] == "GtfAdapter"

    def test_bigbed_and_bedgraph(self):
        assert _build(_track("a.bb"))["adapter"]["type"] == "BigBedAdapter"
        assert _build(_track("a.bedgraph"))["adapter"]["type"] == "BedGraphAdapter"
        assert _build(_track("a.bedgraph.gz"))["adapter"]["type"] == "BedGraphTabixAdapter"

    def test_fasta_is_not_a_track(self):
        with pytest.raises(ValueError):
            _build(_track("ref.fa"))

    @pytest.mark.parametrize(
        "uri", ["c.bw", "c.bed.gz", "c.vcf.gz", "c.bam", "c.cram", "c.gff3.gz", "c.bb"]
    )
    def test_locations_are_explicit(self, uri):
        """The ``uri`` shorthand derives index URLs by suffixing, which breaks
        signed query strings: every location must be a full UriLocation."""
        conf = _build(_track(uri))
        locations = _all_locations(conf["adapter"])
        assert locations
        assert all(loc.get("locationType") == "UriLocation" for loc in locations)
        assert "uri" not in conf["adapter"]

    def test_metadata_drops_nulls(self):
        conf = _build(_track("c1.bw", cell="C1", batch=None))
        assert conf["metadata"] == {"uri": "c1.bw", "cell": "C1"}

    def test_category_from_manifest(self):
        track = _track("c1.bw")
        track.category = "Coverage"
        assert _build(track)["category"] == ["Coverage"]


class TestDisplays:
    def test_display_ids_are_set(self):
        conf = _build(_track("c1.bw", color="red"))
        assert conf["displays"][0]["displayId"] == f"{conf['trackId']}-LinearWiggleDisplay"

    def test_quantitative_color(self):
        conf = _build(_track("c1.bw", color="#ff0000"))
        (display,) = conf["displays"]
        assert display["type"] == "LinearWiggleDisplay"
        assert display["renderers"]["XYPlotRenderer"]["color"] == "#ff0000"

    def test_quantitative_without_color_has_no_display(self):
        assert "displays" not in _build(_track("c1.bw"))

    def test_feature_color_is_a_jexl_fallback(self):
        conf = _build(_track("calls.bed", color="purple"))
        color1 = conf["displays"][0]["renderer"]["color1"]
        assert color1.startswith("jexl:")
        assert "'purple'" in color1
        assert "itemRgb" in color1

    def test_feature_default_color(self):
        color1 = _build(_track("calls.bed"))["displays"][0]["renderer"]["color1"]
        assert "'goldenrod'" in color1

    def test_variant_track_has_no_color_display(self):
        assert "displays" not in _build(_track("sv.vcf.gz", color="red"))

    def test_format_layers_merge_by_display_type(self):
        layers = [
            {"bigwig": {"displays": [{"type": "LinearWiggleDisplay", "height": 60}]}},
            {"bigwig": {"displays": [{"type": "LinearWiggleDisplay", "autoscale": "local"}]}},
            {"bed": {"displays": [{"type": "LinearBasicDisplay", "height": 1}]}},
        ]
        conf = _build(_track("c1.bw", color="blue"), layers)
        (display,) = conf["displays"]
        assert display["height"] == 60
        assert display["autoscale"] == "local"
        assert display["renderers"]["XYPlotRenderer"]["color"] == "blue"
        assert display["displayId"]

    def test_later_layer_wins(self):
        layers = [
            {"bigwig": {"displays": [{"type": "LinearWiggleDisplay", "height": 60}]}},
            {"bigwig": {"displays": [{"type": "LinearWiggleDisplay", "height": 90}]}},
        ]
        assert _build(_track("c1.bw"), layers)["displays"][0]["height"] == 90


class TestDeepMerge:
    def test_dicts_merge_recursively(self):
        assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"c": 3}, "d": 4}) == {
            "a": {"b": 1, "c": 3},
            "d": 4,
        }

    def test_display_lists_merge_by_type(self):
        base = [{"type": "A", "x": 1}, {"type": "B", "y": 1}]
        merged = deep_merge(base, [{"type": "B", "y": 2}, {"type": "C"}])
        assert merged == [{"type": "A", "x": 1}, {"type": "B", "y": 2}, {"type": "C"}]

    def test_other_lists_are_replaced(self):
        assert deep_merge({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}
        assert deep_merge([{"type": "A"}], [{"no_type": 1}]) == [{"no_type": 1}]

    def test_inputs_are_not_mutated(self):
        base = {"displays": [{"type": "A", "h": 1}]}
        override = {"displays": [{"type": "A", "h": 2}]}
        deep_merge(base, override)
        assert base == {"displays": [{"type": "A", "h": 1}]}

    def test_scalar_override(self):
        assert deep_merge({"a": 1}, {"a": None}) == {"a": None}


class TestPresets:
    def test_builtin(self):
        assert resolve_preset("signal", {}) is BUILTIN_PRESETS["signal"]

    def test_dc_preset_shadows_builtin(self):
        mine = {"formats": {}}
        assert resolve_preset("signal", {"signal": mine}) is mine

    def test_unknown_and_empty(self):
        assert resolve_preset("nope", {}) is None
        assert resolve_preset(None, {"x": {}}) is None


# --------------------------------------------------------------------------
# build_assembly_config
# --------------------------------------------------------------------------


def _asm_url(uri: str, role: str) -> str:
    return f"/asm/{role}"


class TestAssembly:
    def test_preset(self):
        conf, annotation, location = build_assembly_config("hg38", _asm_url)
        assert conf["name"] == "hg38"
        adapter = conf["sequence"]["adapter"]
        assert adapter["type"] == "TwoBitAdapter"
        assert adapter["twoBitLocation"]["uri"].endswith("hg38.2bit")
        assert adapter["chromSizesLocation"]["uri"].endswith("hg38.chrom.sizes")
        assert conf["refNameAliases"]["adapter"]["location"]["uri"].endswith("chromAlias.txt")
        assert annotation is not None
        assert annotation["adapter"]["type"] == "BigBedAdapter"
        assert annotation["assemblyNames"] == ["hg38"]
        assert location

    def test_preset_by_alias(self):
        conf, _, _ = build_assembly_config("GRCh38", _asm_url)
        assert conf["name"] == "hg38"
        preset = get_assembly_preset("grch37")
        assert preset is not None and preset.name == "hg19"

    def test_unknown_preset(self):
        with pytest.raises(ValueError, match="Unknown assembly"):
            build_assembly_config("hg00", _asm_url)

    def test_custom_twobit(self):
        asm = CustomAssembly(
            name="myAsm", twobit_uri="ref.2bit", chrom_sizes_uri="ref.sizes", aliases=["m"]
        )
        conf, annotation, location = build_assembly_config(asm, _asm_url)
        assert annotation is None and location is None
        assert conf["displayName"] == "myAsm"
        assert conf["aliases"] == ["m"]
        adapter = conf["sequence"]["adapter"]
        assert adapter["type"] == "TwoBitAdapter"
        assert adapter["twoBitLocation"]["uri"] == "/asm/twobit"
        assert adapter["chromSizesLocation"]["uri"] == "/asm/chrom_sizes"
        assert "refNameAliases" not in conf

    def test_custom_bgzip_fasta(self):
        seen: list[tuple[str, str]] = []

        def url(uri: str, role: str) -> str:
            seen.append((uri, role))
            return f"/asm/{role}"

        asm = CustomAssembly(name="v", fasta_uri="ref.fa.gz", refname_aliases_uri="al.txt")
        conf, _, _ = build_assembly_config(asm, url)
        adapter = conf["sequence"]["adapter"]
        assert adapter["type"] == "BgzipFastaAdapter"
        assert adapter["gziLocation"]["uri"] == "/asm/gzi"
        assert ("ref.fa.gz.fai", "fai") in seen
        assert ("ref.fa.gz.gzi", "gzi") in seen
        assert conf["refNameAliases"]["adapter"]["location"]["uri"] == "/asm/aliases"

    def test_custom_plain_fasta(self):
        asm = CustomAssembly(name="v", fasta_uri="ref.fa", fai_uri="idx/ref.fai")
        conf, _, _ = build_assembly_config(asm, _asm_url)
        adapter = conf["sequence"]["adapter"]
        assert adapter["type"] == "IndexedFastaAdapter"
        assert adapter["faiLocation"]["uri"] == "/asm/fai"
        assert "gziLocation" not in adapter
        assert conf["sequence"]["trackId"] == "v-ReferenceSequenceTrack"


# --------------------------------------------------------------------------
# manifest_rows
# --------------------------------------------------------------------------


class TestManifestRows:
    def test_rows_become_tracks(self):
        import polars as pl

        props = DCGenomicTracksConfig(
            format="tsv", sample_column="cell", name_column="label", track_id_column="id"
        )
        df = pl.DataFrame(
            {
                "uri": ["a.bw", "b.bam", "c.unknown", None, "a.bw"],
                "format": [None, None, None, "bed", None],
                "index_uri": [None, "idx/b.bai", None, None, None],
                "cell": ["C1", "C2", "C3", "C4", "C1"],
                "label": ["A", None, "C", "D", "A"],
                "id": ["t-a", "t-b", "t-c", "t-d", "t-a"],
            }
        )
        rows = manifest_rows(df, props)
        assert [r.track_id for r in rows] == ["t-a", "t-b"]
        assert rows[0].fmt == "bigwig" and rows[0].index_uri is None
        assert rows[1].index_uri == "idx/b.bai"
        assert rows[1].name == "t-b"
        assert rows[0].sample == "C1"

    def test_missing_uri_column(self):
        import polars as pl

        props = DCGenomicTracksConfig(format="tsv", uri_column="path")
        assert manifest_rows(pl.DataFrame({"uri": ["a.bw"]}), props) == []

    def test_default_format(self):
        import polars as pl

        props = DCGenomicTracksConfig(format="tsv", default_format="bed")
        (row,) = manifest_rows(pl.DataFrame({"uri": ["calls.txt"]}), props)
        assert row.fmt == "bed"


# --------------------------------------------------------------------------
# build_jbrowse_payload
# --------------------------------------------------------------------------


def _tdc(**props: Any) -> TracksDC:
    return TracksDC(
        dc_id=DC_ID,
        wf_id="646b0f3c1e4a2d7f8e5b8c00",
        project_id="646b0f3c1e4a2d7f8e5b8c01",
        props=DCGenomicTracksConfig(format="tsv", sample_column="cell", **props),
        delta_location=None,
    )


@pytest.fixture
def cells(monkeypatch) -> list[TrackRow]:
    tracks = [
        _track(f"cells/c{i:02d}.bw", track_id=f"c{i:02d}", cell=f"C{i:02d}") for i in range(30)
    ]
    tracks.append(_track("genes.gtf", track_id="genes", cell=None))
    monkeypatch.setattr(render, "tracks_by_key", lambda tdc: {t.key: t for t in tracks})
    return tracks


def _payload(component: dict[str, Any], filtered=None, tdc: TracksDC | None = None, **kw):
    component = {"show_annotation": False, **component}
    return render.build_jbrowse_payload(component, tdc or _tdc(), filtered, "user-1", **kw)


class TestPayloadSelection:
    def test_no_filter_shows_initial_tracks(self, cells):
        payload = _payload({"initial_tracks": 3})
        assert payload["shown_track_ids"] == ["c00", "c01", "c02"]
        assert payload["filter_applied"] is False
        assert payload["truncated"] is False
        assert payload["total_tracks"] == 31
        assert payload["matched_tracks"] == 31
        # Every track is offered (track menus), the shown ones first.
        ids = [c["trackId"] for c in payload["tracks"]]
        assert ids[:3] == ["c00", "c01", "c02"]
        assert len(ids) == 31

    def test_filtered_is_capped(self, cells):
        payload = _payload({"max_tracks": 10}, filtered=cells[:25])
        assert len(payload["shown_track_ids"]) == 10
        assert payload["truncated"] is True
        assert payload["filter_applied"] is True
        assert payload["matched_tracks"] == 25

    def test_filtered_offers_every_match(self, cells):
        payload = _payload({"max_tracks": 10}, filtered=cells[:25])
        assert len(payload["tracks"]) == 25
        assert len(payload["track_rows"]) == 25
        assert payload["max_tracks"] == 10

    def test_offered_tracks_are_capped(self, cells, monkeypatch):
        monkeypatch.setattr(render, "MAX_CONFIG_TRACKS", 5)
        payload = _payload({"max_tracks": 3}, filtered=cells[:25])
        assert len(payload["tracks"]) == 5
        assert payload["shown_track_ids"] == ["c00", "c01", "c02"]

    def test_force_load_flag(self, cells):
        assert _payload({})["force_load"] is False
        assert _payload({"force_load": True})["force_load"] is True

    def test_fetch_size_limit_on_every_display(self, cells):
        payload = _payload({"initial_tracks": 1, "fetch_size_limit_mb": 5})
        (display,) = payload["tracks"][0]["displays"]
        assert display["type"] == "LinearWiggleDisplay"
        assert display["fetchSizeLimit"] == 5 * 1024 * 1024

    def test_filtered_to_nothing(self, cells):
        payload = _payload({}, filtered=[])
        assert payload["shown_track_ids"] == []
        assert payload["tracks"] == []
        assert payload["matched_tracks"] == 0

    def test_default_tracks_come_first(self, cells):
        payload = _payload({"default_tracks": ["genes", "missing"]}, filtered=cells[5:7])
        assert payload["shown_track_ids"] == ["genes", "c05", "c06"]

    def test_default_tracks_are_not_duplicated(self, cells):
        payload = _payload({"default_tracks": ["c05"]}, filtered=cells[5:7])
        assert payload["shown_track_ids"] == ["c05", "c06"]

    def test_track_mode_all_carries_more_configs(self, cells):
        payload = _payload({"track_mode": "all", "max_tracks": 2}, filtered=cells[3:6])
        assert payload["shown_track_ids"] == ["c03", "c04"]
        assert len(payload["tracks"]) == 31
        assert len(payload["track_rows"]) == 31

    def test_selection_value_in_track_rows(self, cells):
        payload = _payload({"initial_tracks": 1})
        row = payload["track_rows"][0]
        assert row == {
            "track_id": "c00",
            "name": "c00.bw",
            "format": "bigwig",
            "sample": "C00",
            "selection_value": "C00",
            "category": None,
            "color": None,
            "source": "manifest",
        }
        assert payload["selection_column"] == "cell"

    def test_component_selection_column_wins(self, cells):
        payload = _payload({"initial_tracks": 1, "selection_column": "uri"})
        assert payload["track_rows"][0]["selection_value"] == "cells/c00.bw"


class TestPayloadConfig:
    def test_annotation_track_of_the_preset(self, cells):
        payload = _payload({"initial_tracks": 1, "show_annotation": True})
        assert payload["tracks"][0]["trackId"] == "hg38-genes"
        assert payload["shown_track_ids"] == ["hg38-genes", "c00"]
        assert payload["location"]

    def test_annotation_can_be_hidden(self, cells):
        payload = _payload({"initial_tracks": 1, "show_annotation": False})
        assert all(c["trackId"] != "hg38-genes" for c in payload["tracks"])

    def test_custom_assembly_has_no_annotation(self, cells):
        tdc = _tdc(assembly={"name": "v", "fasta_uri": "ref.fa"})
        payload = _payload({"initial_tracks": 1, "show_annotation": True}, tdc=tdc)
        assert payload["shown_track_ids"] == ["c00"]
        assert payload["assembly"]["name"] == "v"
        assert payload["location"] is None
        fasta = payload["assembly"]["sequence"]["adapter"]["fastaLocation"]["uri"]
        assert fasta.startswith(f"/depictio/api/v1/jbrowse/assembly/{DC_ID}/fasta?")

    def test_component_assembly_overrides_dc(self, cells):
        payload = _payload({"initial_tracks": 1, "assembly": "mm10"})
        assert payload["assembly"]["name"] == "mm10"
        assert payload["tracks"][0]["assemblyNames"] == ["mm10"]

    def test_signed_proxy_urls(self, cells):
        from depictio.api.v1.services.jbrowse import signing

        payload = _payload({"initial_tracks": 1})
        url = payload["tracks"][0]["adapter"]["bigWigLocation"]["uri"]
        parsed = urlparse(url)
        assert parsed.path == f"/depictio/api/v1/jbrowse/tracks/{DC_ID}/{cells[0].key}/data"
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        assert q["uid"] == "user-1"
        assert signing.verify("track", DC_ID, cells[0].key, "data", "user-1", q["exp"], q["sig"])

    def test_direct_access_keeps_https(self, monkeypatch):
        remote = _track("https://tracks.example.org/a.bam", track_id="r")
        monkeypatch.setattr(render, "tracks_by_key", lambda tdc: {remote.key: remote})
        payload = _payload({}, tdc=_tdc(direct_access=True))
        adapter = payload["tracks"][0]["adapter"]
        assert adapter["bamLocation"]["uri"] == "https://tracks.example.org/a.bam"
        assert adapter["index"]["location"]["uri"] == "https://tracks.example.org/a.bam.bai"

    def test_preset_dc_defaults_and_overrides_order(self, cells):
        tdc = _tdc(
            display_defaults={
                "bigwig": {"displays": [{"type": "LinearWiggleDisplay", "height": 70}]}
            }
        )
        payload = _payload(
            {
                "initial_tracks": 1,
                "preset": "signal",
                "config_overrides": {
                    "formats": {
                        "bigwig": {"displays": [{"type": "LinearWiggleDisplay", "maxScore": 5}]}
                    }
                },
            },
            tdc=tdc,
        )
        (display,) = payload["tracks"][0]["displays"]
        assert display["height"] == 70  # DC default over the preset's 60
        assert display["autoscale"] == "local"  # from the preset
        assert display["maxScore"] == 5  # component override

    def test_per_track_override(self, cells):
        payload = _payload(
            {"initial_tracks": 2, "config_overrides": {"tracks": {"c01": {"name": "Renamed"}}}}
        )
        names = {c["trackId"]: c["name"] for c in payload["tracks"]}
        assert names["c00"] == "c00.bw"
        assert names["c01"] == "Renamed"

    def test_view_and_configuration_overrides(self, cells):
        payload = _payload(
            {
                "initial_tracks": 0,
                "show_header": False,
                "preset": "compact",
                "config_overrides": {
                    "view": {"trackLabels": "hidden"},
                    "configuration": {"theme": {"palette": {}}},
                },
            }
        )
        assert payload["view"] == {
            "hideHeader": True,
            "hideHeaderOverview": False,
            "trackLabels": "hidden",
        }
        assert payload["configuration"] == {"theme": {"palette": {}}}

    def test_preset_view(self, cells):
        payload = _payload({"initial_tracks": 0, "preset": "compact"})
        assert payload["view"]["trackLabels"] == "overlapping"

    def test_extra_tracks(self, cells):
        extra = {"trackId": "extra", "type": "FeatureTrack", "adapter": {}}
        payload = _payload(
            {"initial_tracks": 1, "config_overrides": {"extra_tracks": [extra, {"no": "id"}]}}
        )
        assert payload["tracks"][-1]["trackId"] == "extra"
        assert payload["tracks"][-1]["assemblyNames"] == ["hg38"]
        assert payload["shown_track_ids"] == ["c00", "extra"]

    def test_assembly_override(self, cells):
        payload = _payload(
            {"initial_tracks": 0, "config_overrides": {"assembly": {"displayName": "Mine"}}}
        )
        assert payload["assembly"]["displayName"] == "Mine"
        assert payload["assembly"]["name"] == "hg38"

    def test_unrenderable_tracks_are_skipped(self, monkeypatch):
        fasta = _track("ref.fa", track_id="ref")
        bw = _track("a.bw", track_id="a")
        monkeypatch.setattr(render, "tracks_by_key", lambda tdc: {fasta.key: fasta, bw.key: bw})
        payload = _payload({})
        assert [c["trackId"] for c in payload["tracks"]] == ["a"]
        assert payload["shown_track_ids"] == ["a"]

    def test_explicit_locus_wins(self, cells):
        payload = _payload({"initial_tracks": 0, "location": "chr2:1-10"}, locus="chr3:5-6")
        assert payload["location"] == "chr3:5-6"
        payload = _payload({"initial_tracks": 0, "location": "chr2:1-10"})
        assert payload["location"] == "chr2:1-10"


class TestLocusFromRows:
    SPEC = {"chrom_column": "chrom", "start_column": "start", "end_column": "end", "padding": 100}

    def test_padded_first_row(self):
        rows = [{"chrom": "chr1", "start": 1000, "end": 2000}, {"chrom": "chr2"}]
        assert render.locus_from_rows(rows, self.SPEC) == "chr1:900-2100"

    def test_start_clamped_to_one_and_sorted(self):
        rows = [{"chrom": "chr1", "start": "150.0", "end": 50}]
        assert render.locus_from_rows(rows, self.SPEC) == "chr1:1-250"

    def test_end_defaults_to_start_and_default_padding(self):
        spec = {"chrom_column": "chrom", "start_column": "pos"}
        assert render.locus_from_rows([{"chrom": "7", "pos": 10_000}], spec) == "7:5000-15000"

    @pytest.mark.parametrize(
        "rows",
        [[], [{"chrom": "chr1", "start": "x", "end": 1}], [{"chrom": None, "start": 1, "end": 2}]],
    )
    def test_unusable(self, rows):
        assert render.locus_from_rows(rows, self.SPEC) is None


def test_manifest_rows_follow_order_column():
    """Ingestion clusters rows by link columns: `order_column` restores the intent."""
    import polars as pl

    from depictio.api.v1.services.jbrowse.tracks import manifest_rows
    from depictio.models.models.data_collections_types.genomic_tracks import (
        DCGenomicTracksConfig,
    )

    df = pl.DataFrame(
        {"uri": ["b.bw", "a.bw", "c.bw"], "sample": ["s2", "s1", "s3"], "order": [2, 3, 1]}
    )
    props = DCGenomicTracksConfig(format="tsv", sample_column="sample", order_column="order")
    assert [t.uri for t in manifest_rows(df, props)] == ["c.bw", "b.bw", "a.bw"]
    unordered = DCGenomicTracksConfig(format="tsv", sample_column="sample")
    assert [t.uri for t in manifest_rows(df, unordered)] == ["b.bw", "a.bw", "c.bw"]


def test_preset_files_go_through_the_api_in_proxy_mode(monkeypatch):
    from depictio.api.v1.configs.config import settings
    from depictio.api.v1.services.jbrowse import render

    monkeypatch.setattr(settings.jbrowse, "preset_access", "proxy")
    conf, annotation, _ = build_assembly_config("hg38", lambda u, r: u, render._preset_url)
    assert conf["sequence"]["adapter"]["twoBitLocation"]["uri"] == (
        "/depictio/api/v1/jbrowse/preset/hg38/twobit"
    )
    assert annotation is not None
    assert annotation["adapter"]["bigBedLocation"]["uri"].endswith("/preset/hg38/annotation")


# --------------------------------------------------------------------------
# fetch size limit
# --------------------------------------------------------------------------


class TestFetchSizeLimit:
    def test_none_leaves_config_alone(self):
        conf = {"type": "FeatureTrack", "trackId": "t"}
        assert apply_fetch_size_limit(dict(conf), None) == conf

    def test_existing_display_gets_the_limit(self):
        conf = {
            "type": "VariantTrack",
            "trackId": "t",
            "displays": [{"type": "LinearVariantDisplay", "height": 30}],
        }
        out = apply_fetch_size_limit(conf, 123)
        assert out["displays"] == [
            {"type": "LinearVariantDisplay", "height": 30, "fetchSizeLimit": 123}
        ]

    def test_alignments_limit_sits_on_sub_displays(self):
        out = apply_fetch_size_limit({"type": "AlignmentsTrack", "trackId": "t"}, 9)
        (display,) = out["displays"]
        assert display["type"] == "LinearAlignmentsDisplay"
        assert "fetchSizeLimit" not in display
        assert display["pileupDisplay"] == {
            "type": "LinearPileupDisplay",
            "displayId": "t-LinearPileupDisplay",
            "fetchSizeLimit": 9,
        }
        assert display["snpCoverageDisplay"]["fetchSizeLimit"] == 9

    def test_bam_track_via_build(self):
        track = _track("reads.bam", track_id="r")
        conf = build_track_config(track, "hg38", lambda t, role: f"/{role}", [], 7)
        (display,) = conf["displays"]
        assert display["displayId"] == "r-LinearAlignmentsDisplay"
        assert display["pileupDisplay"]["fetchSizeLimit"] == 7
