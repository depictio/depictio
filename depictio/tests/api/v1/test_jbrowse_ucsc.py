"""UCSC Genome Browser tracks as default genome-browser tracks.

The UCSC REST API is never called: the catalogue is parsed from a canned
``/list/tracks`` response, and the proxy's reads are faked.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.jbrowse_endpoints import routes
from depictio.api.v1.services import remote_read
from depictio.api.v1.services.jbrowse import render, ucsc
from depictio.api.v1.services.jbrowse.tracks import TrackRow, TracksDC, track_key
from depictio.models.models.data_collections_types.genomic_tracks import (
    CustomAssembly,
    DCGenomicTracksConfig,
)

LIST_TRACKS: dict[str, Any] = {
    "downloadTime": "2026:09:28T09:43:39Z",
    "hg38": {
        "clinvarMain": {
            "shortLabel": "ClinVar SNVs",
            "longLabel": "ClinVar Short Variants",
            "type": "bigBed 12 +",
            "bigDataUrl": "/gbdb/hg38/bbi/clinvar/clinvarMain.bb",
            "group": "phenDis",
        },
        "knownGene": {
            "shortLabel": "GENCODE V50",
            "type": "bigGenePred knownGenePep knownGeneMrna",
            "bigDataUrl": "/gbdb/hg38/gencode/gencodeV50.bb",
            "group": "genes",
        },
        "gc5Base": {
            "shortLabel": "GC Percent",
            "type": "bigWig 0 100",
            "bigDataUrl": "/gbdb/hg38/bbi/gc5BaseBw/gc5Base.bw",
        },
        "lrSv": {
            "shortLabel": "Long-read SVs",
            "type": "vcfTabix",
            "bigDataUrl": "/gbdb/hg38/lrsv.vcf.gz",
        },
        # Not readable: database-backed, foreign host, unsupported type, http.
        "cpgIslandExt": {"shortLabel": "CpG Islands", "type": "bed 4 +"},
        "encodeSignal": {
            "shortLabel": "ENCODE signal",
            "type": "bigWig",
            "bigDataUrl": "https://encode-public.s3.amazonaws.com/x.bw",
        },
        "interactions": {"type": "bigInteract", "bigDataUrl": "/gbdb/hg38/i.bb"},
        "plainHttp": {"type": "bigBed 3", "bigDataUrl": "http://hgdownload.soe.ucsc.edu/x.bb"},
        "notADict": "ignored",
    },
}


@pytest.fixture(autouse=True)
def canned_catalog(monkeypatch):
    ucsc._cache.clear()
    calls: list[str] = []

    def fetch(genome: str):
        calls.append(genome)
        return ucsc.parse_catalog(genome, LIST_TRACKS)

    monkeypatch.setattr(ucsc, "_fetch_catalog", fetch)
    yield calls
    ucsc._cache.clear()


class TestCatalog:
    def test_only_range_readable_files_are_kept(self):
        tracks = ucsc.catalog("hg38")
        assert set(tracks) == {"clinvarMain", "knownGene", "gc5Base", "lrSv"}

    def test_relative_paths_land_on_the_download_server(self):
        track = ucsc.catalog("hg38")["clinvarMain"]
        assert track.url == "https://hgdownload.soe.ucsc.edu/gbdb/hg38/bbi/clinvar/clinvarMain.bb"
        assert track.kind == "bigBed"
        assert track.group == "phenDis"
        assert track.index_url is None

    def test_vcf_gets_its_tabix_index(self):
        assert ucsc.catalog("hg38")["lrSv"].index_url.endswith("/gbdb/hg38/lrsv.vcf.gz.tbi")

    def test_allow_listed_foreign_host_is_readable(self, monkeypatch):
        monkeypatch.setattr(
            settings.jbrowse, "remote_https_hosts", "encode-public.s3.amazonaws.com"
        )
        assert "encodeSignal" in ucsc.parse_catalog("hg38", LIST_TRACKS)

    def test_catalog_is_cached(self, canned_catalog):
        ucsc.catalog("hg38")
        ucsc.catalog("hg38")
        assert canned_catalog == ["hg38"]

    def test_unreachable_api_gives_an_empty_catalog(self, monkeypatch):
        def boom(genome):
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(ucsc, "_fetch_catalog", boom)
        assert ucsc.catalog("mm10") == {}

    def test_search_matches_name_and_label(self):
        names = [t["name"] for t in ucsc.search("hg38", "clin")]
        assert names == ["clinvarMain"]
        assert [t["name"] for t in ucsc.search("hg38", "gencode")] == ["knownGene"]
        assert len(ucsc.search("hg38", "", limit=2)) == 2


class TestGenome:
    @pytest.mark.parametrize(
        ("assembly", "genome"),
        [
            ("hg38", "hg38"),
            ("GRCh38", "hg38"),
            ("hs1", "hs1"),
            ("TAIR10", "GCF_000001735.4"),
            ("GCA_000001405.29", "GCA_000001405.29"),
            ("not-a-genome", None),
            (None, None),
        ],
    )
    def test_preset_names_and_aliases(self, assembly, genome):
        assert ucsc.ucsc_genome(assembly) == genome

    def test_custom_assembly_through_an_alias(self):
        custom = CustomAssembly(name="MN908947.3", fasta_uri="ref.fa", aliases=["wuhCor1"])
        assert ucsc.ucsc_genome(custom) == "wuhCor1"
        assert ucsc.ucsc_genome(CustomAssembly(name="v", fasta_uri="ref.fa")) is None


class TestTrackConfigs:
    def test_configs_and_missing_names(self):
        confs, missing = ucsc.track_configs(
            "hg38", ["clinvarMain", "gc5Base", "lrSv", "nope"], "hg38", ucsc.proxy_url("/api")
        )
        assert missing == ["nope"]
        clinvar, gc, vcf = confs
        assert clinvar["type"] == "FeatureTrack"
        assert clinvar["trackId"] == "ucsc-hg38-clinvarMain"
        assert clinvar["category"] == ["UCSC", "phenDis"]
        assert (
            clinvar["adapter"]["bigBedLocation"]["uri"] == "/api/jbrowse/ucsc/hg38/clinvarMain/data"
        )
        assert gc["adapter"]["type"] == "BigWigAdapter"
        assert vcf["adapter"]["index"]["location"]["uri"] == "/api/jbrowse/ucsc/hg38/lrSv/index"

    def test_direct_access_reads_ucsc_itself(self, monkeypatch):
        monkeypatch.setattr(settings.jbrowse, "preset_access", "direct")
        (conf,), _ = ucsc.track_configs("hg38", ["clinvarMain"], "hg38", ucsc.proxy_url("/api"))
        assert conf["adapter"]["bigBedLocation"]["uri"].startswith(
            "https://hgdownload.soe.ucsc.edu/"
        )

    def test_disabled_or_unknown_genome_resolves_nothing(self, monkeypatch):
        assert ucsc.track_configs(None, ["clinvarMain"], "v", ucsc.proxy_url("/api")) == (
            [],
            ["clinvarMain"],
        )
        monkeypatch.setattr(settings.jbrowse, "ucsc_tracks_enabled", False)
        assert ucsc.track_configs("hg38", ["clinvarMain"], "hg38", ucsc.proxy_url("/api"))[0] == []


class TestPayload:
    @pytest.fixture
    def tdc(self, monkeypatch) -> TracksDC:
        track = TrackRow(
            key=track_key("a.bw"), track_id="a", name="a", uri="a.bw", index_uri=None, fmt="bigwig"
        )
        monkeypatch.setattr(render, "tracks_by_key", lambda tdc: {track.key: track})
        return TracksDC(
            dc_id="646b0f3c1e4a2d7f8e5b8ca9",
            wf_id="646b0f3c1e4a2d7f8e5b8c00",
            project_id="646b0f3c1e4a2d7f8e5b8c01",
            props=DCGenomicTracksConfig(format="tsv"),
            delta_location=None,
        )

    def test_ucsc_tracks_are_shown_and_listed(self, tdc):
        component = {"show_annotation": False, "ucsc_tracks": ["clinvarMain", "nope"]}
        payload = render.build_jbrowse_payload(component, tdc, None, "u")
        # Reference tracks open above the collection's.
        assert payload["shown_track_ids"] == ["ucsc-hg38-clinvarMain", "a"]
        assert payload["ucsc_missing"] == ["nope"]
        row = payload["track_rows"][-1]
        assert row["source"] == "ucsc"
        assert row["name"] == "ClinVar SNVs"
        assert row["category"] == "phenDis"

    def test_fetch_limit_reaches_ucsc_tracks(self, tdc):
        component = {
            "show_annotation": False,
            "ucsc_tracks": ["clinvarMain"],
            "fetch_size_limit_mb": 2,
        }
        payload = render.build_jbrowse_payload(component, tdc, None, "u")
        (display,) = payload["tracks"][-1]["displays"]
        assert display["fetchSizeLimit"] == 2 * 1024 * 1024

    def test_annotation_row_is_listed(self, tdc):
        payload = render.build_jbrowse_payload({}, tdc, None, "u")
        assert payload["track_rows"][0]["source"] == "annotation"

    def test_ucsc_tracks_open_under_the_annotation(self, tdc):
        payload = render.build_jbrowse_payload({"ucsc_tracks": ["gc5Base"]}, tdc, None, "u")
        assert payload["shown_track_ids"] == ["hg38-genes", "ucsc-hg38-gc5Base", "a"]


class TestRoutes:
    @pytest.fixture
    def client(self, monkeypatch):
        reads: list[str] = []

        def size(src):
            reads.append(src.url)
            return 100

        monkeypatch.setattr(remote_read, "source_size", size)
        monkeypatch.setattr(remote_read, "open_range", lambda src, rng: iter([b"z" * rng.length]))
        app = FastAPI()
        app.include_router(routes.jbrowse_endpoints_router, prefix="/jbrowse")
        return TestClient(app), reads

    def test_list_for_a_preset_alias(self, client):
        c, _ = client
        body = c.get("/jbrowse/ucsc/GRCh38/tracks", params={"q": "clin"}).json()
        assert body["genome"] == "hg38"
        assert [t["name"] for t in body["tracks"]] == ["clinvarMain"]

    def test_list_for_an_unknown_assembly(self, client):
        c, _ = client
        assert c.get("/jbrowse/ucsc/whatever/tracks").json() == {"genome": None, "tracks": []}

    def test_proxy_reads_the_catalogued_file_only(self, client):
        c, reads = client
        r = c.get("/jbrowse/ucsc/hg38/clinvarMain/data", headers={"Range": "bytes=0-9"})
        assert r.status_code == 206
        assert reads == ["https://hgdownload.soe.ucsc.edu/gbdb/hg38/bbi/clinvar/clinvarMain.bb"]

    def test_vcf_index(self, client):
        c, reads = client
        assert c.head("/jbrowse/ucsc/hg38/lrSv/index").status_code == 200
        assert reads[-1].endswith("lrsv.vcf.gz.tbi")

    @pytest.mark.parametrize(
        "path",
        [
            "/jbrowse/ucsc/hg38/cpgIslandExt/data",  # database-backed, no file
            "/jbrowse/ucsc/hg38/clinvarMain/index",  # bigBed has no index
            "/jbrowse/ucsc/hg38/clinvarMain/secret",
            "/jbrowse/ucsc/hg38/nope/data",
        ],
    )
    def test_unknown_files_are_404(self, client, path):
        c, reads = client
        assert c.get(path).status_code == 404
        assert reads == []
