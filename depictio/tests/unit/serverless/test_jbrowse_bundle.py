"""The genome browser offline: index arithmetic, file shipping, session rewrite.

``depictio/serverless/genome_index.py`` reads BAI/TBI/CSI indexes to find the
bytes a region needs; ``depictio/serverless/jbrowse_bundle.py`` ships a frozen
JBrowse session's files (whole, sliced to the opening locus, or not at all,
with the reason) and rewrites its locations to the runtime's fetch shim;
``producer_a._jbrowse_opener`` maps the API's track-proxy URLs back to the
storage locations the proxy itself reads.

The data is the synthetic demo genome (``serverless/examples/genome_demo.py``)
and the real htslib-written tabix files of the genome_tracks_examples project.
"""

from __future__ import annotations

import base64
import copy
import json
import re
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from depictio.serverless import genome_index as gi
from depictio.serverless import jbrowse_bundle as jb
from depictio.serverless.examples import genome_demo as demo
from depictio.serverless.objects import ObjectBudget

REPO_ROOT = Path(__file__).resolve().parents[4]
SV_CALLS = (
    REPO_ROOT / "depictio/projects/init/genome_tracks_examples/data/strandseq/sv_calls/GM18939x02"
)


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("genome")
    demo.write_demo_files(root)
    return root


def _blob(inline: dict[str, str], entry: dict) -> bytes:
    return base64.b64decode(inline[entry["blob"]])


def _files_by_label(result: jb.BundleResult) -> dict[str, dict]:
    return {f["label"]: f for f in result.payload["bundle"]["files"].values()}


def _key_of(location: dict) -> str:
    assert location["uri"].startswith(jb.BUNDLE_ORIGIN), location
    return location["uri"].removeprefix(jb.BUNDLE_ORIGIN)


# --- genome_index ----------------------------------------------------------------


def test_parse_locus_spellings() -> None:
    assert gi.parse_locus("chr8:6,000,000-14,000,000") == gi.Locus("chr8", 5_999_999, 14_000_000)
    assert gi.parse_locus("ctgA:1..20") == gi.Locus("ctgA", 0, 20)
    assert gi.parse_locus("chrX") == gi.Locus("chrX", 0, None)
    assert gi.parse_locus("a:1-2 b:3-4") == gi.Locus("a", 0, 2)
    assert gi.parse_locus("") is None
    assert gi.parse_locus(None) is None
    # The browser fetches the blocks around the view: the slice is the locus
    # plus its width on each side, clamped to the reference.
    assert gi.Locus("c", 100, 200).widened(250).label() == "c:1-250"


def test_reg2bins_matches_the_spec_levels() -> None:
    bins = gi.reg2bins(0, 1)
    assert bins == [0, 1, 9, 73, 585, 4681]  # one bin per level
    # A 16 kb leaf boundary crossed: two leaves.
    assert {4681, 4682} <= set(gi.reg2bins(16_000, 17_000))


def test_find_ref_tries_aliases_and_the_chr_prefix() -> None:
    names = ["1", "2", "MT", "NC_045512v2"]
    assert gi.find_ref(names, "chr2") == 1
    assert gi.find_ref(names, "chrM") == 2
    assert gi.find_ref(names, "MN908947.3", [{"MN908947.3", "NC_045512v2"}]) == 3
    assert gi.find_ref(names, "chr9") == -1


def test_real_tabix_index_parses_and_points_at_the_data() -> None:
    tbi = (SV_CALLS / "GM18939x02PE20401-SV.bed.gz.tbi").read_bytes()
    idx = gi.parse_index(tbi)
    assert idx.kind == "TBI"
    assert "chr8" in idx.names
    chunks = idx.chunks_for(idx.names.index("chr8"), 6_000_000, 14_000_000)
    assert chunks, "the chr8 calls are in the file"
    # The blocks a reader touches, decompressed, hold chr8 lines only within them.
    data = (SV_CALLS / "GM18939x02PE20401-SV.bed.gz").read_bytes()
    text = gi.bgzf_decompress(data).decode()
    assert "chr8\t" in text
    for first, _last in idx.block_ranges_for(idx.names.index("chr8"), 6_000_000, 14_000_000):
        assert first < len(data)


def test_synthetic_bam_and_bai_round_trip(demo_dir: Path) -> None:
    bam = (demo_dir / "reads.bam").read_bytes()
    idx = gi.parse_index((demo_dir / "reads.bam.bai").read_bytes())
    assert idx.kind == "BAI" and idx.names == []  # BAI names nothing: the header does
    assert gi.bam_ref_names(bam[: 2 * gi.BGZF_MAX_BLOCK]) == ["ctgA", "ctgB"]
    near = idx.block_ranges_for(0, 150_000, 150_600)
    far = idx.block_ranges_for(0, 1_000, 1_600)
    # The linear index skips everything before the region: the reads near
    # 150 kb start in the file's last page, those near 1 kb in its first.
    assert min(s for s, _ in near) >= 2 * jb.PAGE_SIZE
    assert min(s for s, _ in far) < jb.PAGE_SIZE


def test_csi_index_with_tabix_aux_names() -> None:
    names = b"chr1\x00chr2\x00"
    aux = struct.pack("<7i", 0, 1, 2, 3, ord("#"), 0, len(names)) + names
    leaf = ((1 << 15) - 1) // 7 + (100_000 >> 14)
    body = (
        b"CSI\x01"
        + struct.pack("<3i", 14, 5, len(aux))
        + aux
        + struct.pack("<i", 2)
        + struct.pack("<i", 1)
        + struct.pack("<IQi", leaf, 5 << 16, 1)
        + struct.pack("<QQ", 5 << 16, 9 << 16)
        + struct.pack("<i", 0)
    )
    w = demo.BgzfWriter()
    w.write(body)
    idx = gi.parse_index(w.close())
    assert idx.kind == "CSI" and idx.names == ["chr1", "chr2"]
    assert idx.chunks_for(0, 100_000, 100_100) == [(5 << 16, 9 << 16)]
    assert idx.block_ranges_for(0, 100_000, 100_100) == [(5, 9 + gi.BGZF_MAX_BLOCK - 1)]
    assert idx.chunks_for(1, 100_000, 100_100) == []


def test_index_format_errors_are_typed() -> None:
    with pytest.raises(gi.IndexFormatError):
        gi.parse_index(b"NOPE" + b"\x00" * 20)
    with pytest.raises(gi.IndexFormatError):
        gi.bam_ref_names(b"not bgzf at all")


def test_pages_cover_ranges_and_merge_runs() -> None:
    p = jb.PAGE_SIZE
    assert jb.pages_for([(0, 10)], 10 * p) == [(0, 1)]
    assert jb.pages_for([(0, 10), (p + 5, 2 * p + 1), (5 * p, 5 * p)], 10 * p) == [
        (0, 3),
        (5, 1),
    ]
    # Ranges past the end are clamped to the last page.
    assert jb.pages_for([(9 * p, 20 * p)], 9 * p + 3) == [(9, 1)]


# --- bundle_session ---------------------------------------------------------------


def test_small_files_ship_whole_and_every_location_is_rewritten(demo_dir: Path) -> None:
    inline: dict[str, str] = {}
    session = demo.demo_session()
    result = jb.bundle_session(session, demo.demo_opener(demo_dir), ObjectBudget(), inline)

    assert result.renderable and result.omitted == []
    assert result.shipped_tracks == result.total_tracks == 3
    assert (
        session["tracks"][0]["adapter"]["bedLocation"]["uri"] == "demo://genes.bed"
    )  # not mutated
    payload = result.payload
    assert "demo://" not in json.dumps(payload["tracks"]) + json.dumps(payload["assembly"])
    files = payload["bundle"]["files"]
    for track in payload["tracks"]:
        for _, loc in jb.locations(track["adapter"]):
            entry = files[_key_of(loc)]
            assert entry["pages"] is None
    bam = payload["tracks"][2]["adapter"]["bamLocation"]
    assert _blob(inline, files[_key_of(bam)]) == (demo_dir / "reads.bam").read_bytes()
    assert payload["bundle"]["renderable"] is True
    assert "reference sequence shipped" in result.detail()


def test_a_big_indexed_file_ships_only_the_pages_of_the_opening_locus(demo_dir: Path) -> None:
    inline: dict[str, str] = {}
    result = jb.bundle_session(
        demo.demo_session(),
        demo.demo_opener(demo_dir),
        ObjectBudget(),
        inline,
        small_file_bytes=64 * 1024,
    )
    files = _files_by_label(result)
    reads = files["reads.bam"]
    assert reads["pages"] == [[0, 1], [2, 1]]  # the header page and the locus' page
    assert reads["region"] == "ctgA:149,401-151,200"
    whole = (demo_dir / "reads.bam").read_bytes()
    p = jb.PAGE_SIZE
    assert _blob(inline, reads) == whole[:p] + whole[2 * p : 3 * p]
    # Every block the index names for the (widened) locus is inside the pages.
    idx = gi.parse_index((demo_dir / "reads.bam.bai").read_bytes())
    for first, last in idx.block_ranges_for(0, 149_400, 151_200):
        assert 2 * p <= first and min(last, len(whole) - 1) < 3 * p
    # The index itself always ships whole.
    assert files["reads.bam.bai"]["pages"] is None
    assert "1 sliced to ctgA:149,401-151,200" in result.detail()


def test_a_real_tabix_track_is_sliced_by_its_named_reference(tmp_path: Path) -> None:
    for suffix in (".bed.gz", ".bed.gz.tbi"):
        name = f"GM18939x02PE20401-SV{suffix}"
        (tmp_path / name).write_bytes((SV_CALLS / name).read_bytes())
    (tmp_path / "hg38.sizes").write_text("chr8\t145138636\nchr13\t114364328\n")
    session = {
        "assembly": {
            "name": "hg38",
            "sequence": {
                "type": "ReferenceSequenceTrack",
                "trackId": "seq",
                "adapter": {
                    "type": "ChromSizesAdapter",
                    "chromSizesLocation": {"uri": "demo://hg38.sizes"},
                },
            },
        },
        "location": "chr8:6,000,000-14,000,000",
        "tracks": [
            {
                "type": "FeatureTrack",
                "trackId": "sv",
                "name": "SV calls",
                "adapter": {
                    "type": "BedTabixAdapter",
                    "bedGzLocation": {"uri": "demo://GM18939x02PE20401-SV.bed.gz"},
                    "index": {
                        "indexType": "TBI",
                        "location": {"uri": "demo://GM18939x02PE20401-SV.bed.gz.tbi"},
                    },
                },
            }
        ],
        "shown_track_ids": ["sv"],
        "track_rows": [{"track_id": "sv"}],
    }
    result = jb.bundle_session(
        session, demo.demo_opener(tmp_path), ObjectBudget(), {}, small_file_bytes=0
    )
    assert result.renderable and result.sliced == 1
    assert _files_by_label(result)["GM18939x02PE20401-SV.bed.gz"]["pages"] == [[0, 1]]


def test_a_track_over_the_budget_is_dropped_with_its_reason(demo_dir: Path) -> None:
    inline: dict[str, str] = {}
    result = jb.bundle_session(
        demo.demo_session(),
        demo.demo_opener(demo_dir),
        ObjectBudget(),
        inline,
        cap=300 * 1024,  # the FASTA + BED + bedGraph fit, the reads (even sliced) do not
        small_file_bytes=64 * 1024,
    )
    assert result.renderable
    assert [o.track_id for o in result.omitted] == ["demo-reads"]
    why = result.omitted[0].reason
    assert re.search(r"^BAM, 6\d\d KB: over the 1\d\d KB left of the budget", why)
    assert "left of the budget" in why and "DEPICTIO_STATIC_JBROWSE_MAX_MB" in why
    assert "sliced to ctgA:149,401-151,200" in why
    payload = result.payload
    assert [t["trackId"] for t in payload["tracks"]] == ["demo-genes", "demo-coverage"]
    assert "demo-reads" not in payload["shown_track_ids"]
    assert [r["track_id"] for r in payload["track_rows"]] == ["demo-genes", "demo-coverage"]
    assert payload["bundle"]["omitted"][0]["track_id"] == "demo-reads"
    assert "left out: Reads: BAM" in result.detail()
    assert not any("reads.bam" == f["label"] for f in payload["bundle"]["files"].values())


def test_a_file_over_the_per_file_cap_names_that_cap(demo_dir: Path) -> None:
    result = jb.bundle_session(
        demo.demo_session(),
        demo.demo_opener(demo_dir),
        ObjectBudget(per_object=200 * 1024),
        {},
    )
    reads = next(o for o in result.omitted if o.track_id == "demo-reads")
    assert "per-file cap (DEPICTIO_STATIC_OBJECT_MAX_MB)" in reads.reason


def test_a_sequence_too_big_falls_back_to_chromosome_lengths(demo_dir: Path) -> None:
    inline: dict[str, str] = {}
    result = jb.bundle_session(
        demo.demo_session(),
        demo.demo_opener(demo_dir),
        ObjectBudget(per_object=100 * 1024),  # the 164 KB FASTA does not fit
        inline,
    )
    assert result.renderable
    adapter = result.payload["assembly"]["sequence"]["adapter"]
    assert adapter["type"] == "ChromSizesAdapter"
    entry = result.payload["bundle"]["files"][_key_of(adapter["chromSizesLocation"])]
    assert _blob(inline, entry).decode() == "ctgA\t160000\nctgB\t5000\n"  # from the .fai
    assert "without bases" in result.detail()
    assert "reference sequence (FASTA" in result.detail()


def test_twobit_sizes_are_read_from_its_index(tmp_path: Path) -> None:
    seqs = {"chrA": 10, "chrBB": 33}
    head = struct.pack("<IIII", gi.TWOBIT_MAGIC, 0, len(seqs), 0)
    index = b""
    records = b""
    offset = len(head) + sum(1 + len(n) + 4 for n in seqs)
    for name, n in seqs.items():
        index += bytes([len(name)]) + name.encode() + struct.pack("<I", offset + len(records))
        rec = struct.pack("<IIII", n, 0, 0, 0) + b"\x00" * ((n + 3) // 4)
        records += rec
    path = tmp_path / "g.2bit"
    path.write_bytes(head + index + records)
    assert jb._sizes_from_twobit(demo.LocalFile(path)) == [("chrA", 10), ("chrBB", 33)]


def test_nothing_readable_is_not_renderable_and_ships_nothing(demo_dir: Path) -> None:
    inline: dict[str, str] = {"dc_x": "keep"}

    def refuse(uri: str):
        raise jb.SourceRefused("host not allow-listed")

    result = jb.bundle_session(demo.demo_session(), refuse, ObjectBudget(), inline)
    assert not result.renderable
    assert "chromosome lengths could not be read" in (result.reason or "")
    assert result.payload["bundle"] == {
        "version": jb.BUNDLE_FORMAT_VERSION,
        "renderable": False,
        "reason": result.reason,
        "files": {},
        "omitted": [],
        "region": "ctgA:150,001-150,600",
        "sequence": None,
    }
    assert inline == {"dc_x": "keep"}
    assert result.detail().startswith("export-time session only")
    # The session is kept as it was (the runtime shows its track table).
    assert result.payload["tracks"] == demo.demo_session()["tracks"]


def test_an_unreadable_track_and_a_cram_without_sequence_are_left_out(demo_dir: Path) -> None:
    session = demo.demo_session()
    session["tracks"].append(
        {
            "type": "VariantTrack",
            "trackId": "gone",
            "name": "Gone",
            "adapter": {"type": "VcfAdapter", "vcfLocation": {"uri": "demo://nope.vcf"}},
        }
    )
    session["tracks"].append(
        {
            "type": "AlignmentsTrack",
            "trackId": "cram",
            "name": "CRAM reads",
            "adapter": {
                "type": "CramAdapter",
                "cramLocation": {"uri": "demo://reads.cram"},
                "craiLocation": {"uri": "demo://reads.cram.crai"},
            },
        }
    )
    result = jb.bundle_session(
        session, demo.demo_opener(demo_dir), ObjectBudget(per_object=100 * 1024), {}
    )
    reasons = {o.track_id: o.reason for o in result.omitted}
    assert reasons["gone"].startswith("VCF unreadable")
    assert "reference sequence, which is not in the bundle" in reasons["cram"]


def test_dry_run_plans_the_same_without_writing_blobs(demo_dir: Path) -> None:
    real_inline: dict[str, str] = {}
    real = jb.bundle_session(
        demo.demo_session(),
        demo.demo_opener(demo_dir),
        ObjectBudget(),
        real_inline,
        small_file_bytes=64 * 1024,
    )
    dry_inline: dict[str, str] = {}
    budget = ObjectBudget()
    dry = jb.bundle_session(
        demo.demo_session(),
        demo.demo_opener(demo_dir),
        budget,
        dry_inline,
        dry_run=True,
        small_file_bytes=64 * 1024,
    )
    assert dry_inline == {}
    assert dry.detail() == real.detail()
    assert budget.used == real.shipped_bytes


def test_the_budget_is_shared_with_the_bundle_objects(demo_dir: Path) -> None:
    objects = ObjectBudget(cap=100 * 1024)
    objects.used = 90 * 1024  # images and structures took most of it
    result = jb.bundle_session(demo.demo_session(), demo.demo_opener(demo_dir), objects, {})
    assert not result.renderable or result.shipped_bytes <= 10 * 1024
    assert "files per bundle, DEPICTIO_STATIC_OBJECTS_MAX_MB" in (
        result.reason or json.dumps([o.reason for o in result.omitted])
    )


def test_the_committed_demo_manifest_is_current(demo_dir: Path, tmp_path: Path) -> None:
    """genome.json is what genome_demo.py writes (the offline spec opens it)."""
    committed = json.loads(demo.OUT.read_text())
    payload = committed["frozen"]["genome-browser"]["payload"]
    fresh = jb.bundle_session(
        demo.demo_session(),
        demo.demo_opener(demo_dir),
        ObjectBudget(),
        {},
        small_file_bytes=64 * 1024,
    )
    assert payload["bundle"]["files"] == json.loads(json.dumps(fresh.payload["bundle"]["files"]))
    assert committed["tiers"]["genome-browser"]["detail"] == fresh.detail()


# --- producer A: the opener ---------------------------------------------------------


def test_the_opener_resolves_proxy_urls_like_the_proxy(monkeypatch) -> None:
    from depictio.api.v1.services import remote_read
    from depictio.api.v1.services.jbrowse import tracks as tracks_mod
    from depictio.serverless import producer_a

    tdc = SimpleNamespace(project_id="p1", props=SimpleNamespace(assembly=None))
    track = SimpleNamespace(
        uri="calls/s1.vcf.gz", index_uri="calls/s1.vcf.gz.tbi", fmt="vcf", name="S1 calls"
    )
    seen: dict = {}

    def by_key(t, version):
        seen["version"] = version
        return {"k1": track}

    monkeypatch.setattr(tracks_mod, "find_tracks_dc", lambda dc: tdc if dc == "dc1" else None)
    monkeypatch.setattr(tracks_mod, "tracks_by_key", by_key)
    monkeypatch.setattr(tracks_mod, "user_can_read_project", lambda pid, uid: uid == "u1")
    monkeypatch.setattr(tracks_mod, "s3_base_folder", lambda dc, props: "s3://bucket/dc1/")
    monkeypatch.setattr(
        remote_read,
        "resolve_location",
        lambda uri, base: remote_read.ByteSource("depictio_s3", bucket="bucket", key=base + uri),
    )
    user = producer_a.ExportUser(id="u1")
    open_uri = producer_a._jbrowse_opener(user)
    src = open_uri("/depictio/api/v1/jbrowse/tracks/dc1/k1/index?uid=u1&exp=1&sig=x&v=3")
    assert src.src.key == "s3://bucket/dc1/calls/s1.vcf.gz.tbi"
    assert src.label == "S1 calls (index)"
    assert seen["version"] == 3
    with pytest.raises(jb.SourceRefused):
        open_uri("/depictio/api/v1/jbrowse/tracks/other/k1/data")
    with pytest.raises(jb.SourceRefused):
        producer_a._jbrowse_opener(producer_a.ExportUser(id="u2"))(
            "/depictio/api/v1/jbrowse/tracks/dc1/k1/data"
        )
    with pytest.raises(jb.SourceRefused):
        open_uri("file:///etc/passwd")
    ucsc_file = open_uri("https://hgdownload.soe.ucsc.edu/gbdb/wuhCor1/ncbiGene.bb")
    assert ucsc_file.src.url.endswith("ncbiGene.bb") and ucsc_file.label == "ncbiGene.bb"


def test_jbrowse_addon_entry_is_a_valid_manifest_addon(tmp_path: Path, monkeypatch) -> None:
    from depictio.serverless import addons as addons_mod

    (tmp_path / "addons.json").write_text(
        json.dumps(
            {"jbrowse": {"version": "4.3.0", "file": "jbrowse.js", "bytes": 3, "sha256": ""}}
        )
    )
    (tmp_path / "jbrowse.js").write_text("globalThis.__depictioJBrowseVendor=function(){};")
    monkeypatch.setenv(addons_mod.ADDONS_DIR_ENV, str(tmp_path))
    entry = addons_mod.addon_entry("jbrowse", "genome browser tiles: x")
    assert entry is not None and entry.name == "jbrowse" and entry.version == "4.3.0"
    html = addons_mod.apply_addons("<html><body></body></html>", ["jbrowse"])
    assert '<script data-depictio-addon="jbrowse">' in html


def test_bundle_result_detail_is_stable_for_a_copy(demo_dir: Path) -> None:
    session = demo.demo_session()
    before = copy.deepcopy(session)
    jb.bundle_session(session, demo.demo_opener(demo_dir), ObjectBudget(), {})
    assert session == before


def test_a_session_that_cannot_render_gives_its_budget_back(demo_dir: Path) -> None:
    """The assembly shipped, then no track fit: its blobs leave the bundle, and
    a blob another tile shipped first stays."""
    shared_key = "jb_shared"
    inline: dict[str, str] = {shared_key: "AAAA"}
    objects = ObjectBudget()
    objects.seen.add(shared_key)
    objects.used = 4
    session = demo.demo_session()
    for track in session["tracks"]:
        for _, loc in jb.locations(track["adapter"]):
            loc["uri"] = "demo://missing"
    result = jb.bundle_session(session, demo.demo_opener(demo_dir), objects, inline)
    assert not result.renderable
    assert result.reason and result.reason.startswith("no track fits the bundle")
    assert inline == {shared_key: "AAAA"}
    assert objects.used == 4 and objects.seen == {shared_key}
