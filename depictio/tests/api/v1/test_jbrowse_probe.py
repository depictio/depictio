"""The opening probe: a region holding data, read from a track's index.

The BAI, TBI, CSI and bigWig bytes are built here, byte for byte as the formats
lay them out, and served through a fake store; nothing is read from a network.
"""

from __future__ import annotations

import gzip
import struct
import zlib
from types import SimpleNamespace

import pytest

from depictio.api.v1.services import remote_read
from depictio.api.v1.services.jbrowse import probe
from depictio.api.v1.services.jbrowse.tracks import TrackRow, track_key

# The v1 conftest replaces ``probe.first_region`` for every test; keep the real one.
FIRST_REGION = probe.first_region
LEAF = 4681  # first leaf bin of the standard 14 / 5 binning
PSEUDO = probe.PSEUDO_BIN


# --------------------------------------------------------------------------
# Format builders
# --------------------------------------------------------------------------


def _chunks(chunks: list[tuple[int, int]]) -> bytes:
    return b"".join(struct.pack("<QQ", beg, end) for beg, end in chunks)


def _ref(bins: dict[int, list[tuple[int, int]]], mapped: int | None, csi: bool = False) -> bytes:
    """One reference of a BAI / TBI (or, with ``csi``, a CSI)."""
    entries = list(bins.items())
    if mapped is not None:
        entries.append((PSEUDO, [(0, 1), (mapped, 0)]))
    out = struct.pack("<i", len(entries))
    for bin_id, chunks in entries:
        out += struct.pack("<I", bin_id)
        if csi:
            out += struct.pack("<Q", 0)
        out += struct.pack("<i", len(chunks)) + _chunks(chunks)
    return out


def _linear(n: int = 2) -> bytes:
    return struct.pack("<i", n) + b"\x00" * 8 * n


def bai(refs: list[bytes]) -> bytes:
    return b"BAI\x01" + struct.pack("<i", len(refs)) + b"".join(r + _linear() for r in refs)


def tbi(names: list[str], refs: list[bytes]) -> bytes:
    block = b"".join(n.encode() + b"\x00" for n in names)
    head = struct.pack("<8i", len(refs), 2, 1, 2, 0, ord("#"), 0, len(block))
    raw = b"TBI\x01" + head + block + b"".join(r + _linear() for r in refs)
    return gzip.compress(raw)


def csi(names: list[str], refs: list[bytes]) -> bytes:
    block = b"".join(n.encode() + b"\x00" for n in names)
    aux = struct.pack("<7i", 2, 1, 2, 0, ord("#"), 0, len(block)) + block
    raw = (
        b"CSI\x01"
        + struct.pack("<3i", 14, 5, len(aux))
        + aux
        + struct.pack("<i", len(refs))
        + b"".join(refs)
    )
    return gzip.compress(raw)


def bam_header(names: list[str]) -> bytes:
    text = b"@HD\tVN:1.6\n"
    raw = b"BAM\x01" + struct.pack("<i", len(text)) + text + struct.pack("<i", len(names))
    for name in names:
        encoded = name.encode() + b"\x00"
        raw += struct.pack("<i", len(encoded)) + encoded + struct.pack("<i", 1_000_000)
    return gzip.compress(raw)


def bigwig(
    chroms: dict[int, tuple[str, int]],
    first_block: tuple[int, int, int],
    compressed: bool = True,
    nested_tree: bool = False,
) -> bytes:
    key_size = 8
    items = sorted(chroms.items(), key=lambda kv: kv[1][0])
    leaf = struct.pack("<BBH", 1, 0, len(items))
    for chrom_id, (name, size) in items:
        leaf += name.encode().ljust(key_size, b"\x00") + struct.pack("<II", chrom_id, size)
    ctoff = 64
    tree_head = struct.pack("<IIIIQQ", 0x78CA8C91, 256, key_size, 8, len(items), 0)
    if nested_tree:
        child_at = ctoff + 32 + 4 + key_size + 8
        root = (
            struct.pack("<BBH", 0, 0, 1)
            + items[0][1][0].encode().ljust(key_size, b"\x00")
            + struct.pack("<Q", child_at)
        )
        tree = tree_head + root + leaf
    else:
        tree = tree_head + leaf
    dataoff = ctoff + len(tree)
    block = struct.pack("<IIIIIBBH", *first_block, 1, 1, 1, 0, 1) + struct.pack("<If", 1, 1.0)
    data = struct.pack("<Q", 1) + (zlib.compress(block) if compressed else block)
    header = struct.pack(
        "<IHHQQQHHQQIQ",
        0x888FFC26,
        4,
        0,
        ctoff,
        dataoff,
        0,
        0,
        0,
        0,
        0,
        4096 if compressed else 0,
        0,
    )
    assert len(header) == 64
    return header + tree + data


# --------------------------------------------------------------------------
# Fake store
# --------------------------------------------------------------------------


class Store:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.reads: list[str] = []

    def source(self, key: str, data: bytes) -> remote_read.ByteSource:
        self.files[key] = data
        return remote_read.ByteSource("depictio_s3", bucket="b", key=key)


@pytest.fixture
def store(monkeypatch) -> Store:
    st = Store()

    def size(src):
        if src.key not in st.files:
            raise remote_read.RemoteReadError(404, "not found")
        return len(st.files[src.key])

    def open_range(src, rng):
        st.reads.append(src.key)
        return iter([st.files[src.key][rng.start : rng.end + 1]])

    monkeypatch.setattr(remote_read, "source_size", size)
    monkeypatch.setattr(remote_read, "open_range", open_range)
    probe.clear_cache()
    yield st
    probe.clear_cache()


# --------------------------------------------------------------------------
# BAM
# --------------------------------------------------------------------------


def test_bam_opens_on_the_reference_with_the_most_reads_in_its_densest_bin(store):
    quiet = _ref({LEAF + 1: [(0, 100)]}, mapped=10)
    busy = _ref(
        {
            LEAF + 1: [(0, 500)],
            LEAF + 3: [(500, 90_000)],  # densest 16 kb window
            LEAF + 2: [(90_000, 90_400)],
        },
        mapped=5_000,
    )
    data = store.source("r.bam", bam_header(["chr1", "chr2", "chr3"]))
    index = store.source("r.bam.bai", bai([quiet, busy, _ref({}, mapped=0)]))
    assert probe.probe_source("bam", data, index) == f"chr2:{3 * 16384 + 1}-{4 * 16384}"


def test_bam_without_reads_is_unreadable_not_an_error(store):
    data = store.source("r.bam", bam_header(["chr1"]))
    index = store.source("r.bam.bai", bai([_ref({}, mapped=0)]))
    assert probe.probe_source("bam", data, index) is None


def test_a_coarse_bin_names_its_whole_extent_not_a_corner_of_it(store):
    # Bin 586 is the second bin of level 4: 128 kb wide, from 128 kb.
    coarse = _ref({4681 // 8 + 1: [(0, 1_000)]}, mapped=50)
    data = store.source("r.bam", bam_header(["chrM"]))
    index = store.source("r.bam.bai", bai([coarse]))
    assert probe.probe_source("bam", data, index) == "chrM:131073-262144"


def test_a_bin_covering_the_contig_names_the_contig(store):
    index = store.source("v.tbi", tbi(["chrX"], [_ref({1: [(0, 10)]}, mapped=1)]))  # level 1: 64 Mb
    assert probe.probe_source("vcf", store.source("v.vcf.gz", b""), index) == "chrX"


def test_bam_without_an_index_has_nothing_to_probe(store):
    data = store.source("r.bam", bam_header(["chr1"]))
    assert probe.probe_source("bam", data, None) is None


# --------------------------------------------------------------------------
# tabix
# --------------------------------------------------------------------------


def test_tbi_opens_on_the_first_reference_that_has_bins(store):
    refs = [_ref({}, mapped=0), _ref({LEAF + 5: [(0, 700)]}, mapped=3), _ref({LEAF: [(0, 1)]}, 1)]
    index = store.source("v.vcf.gz.tbi", tbi(["1", "2", "3"], refs))
    data = store.source("v.vcf.gz", b"")
    assert probe.probe_source("vcf", data, index) == f"2:{5 * 16384 + 1}-{6 * 16384}"


def test_csi_reads_its_names_from_the_tabix_header(store):
    refs = [_ref({}, mapped=None, csi=True), _ref({LEAF + 2: [(0, 40)]}, None, csi=True)]
    index = store.source("v.vcf.gz.csi", csi(["chrA", "chrB"], refs))
    data = store.source("v.vcf.gz", b"")
    assert probe.probe_source("vcf", data, index) == f"chrB:{2 * 16384 + 1}-{3 * 16384}"


def test_a_tabix_index_with_no_data_is_unreadable(store):
    index = store.source("v.tbi", tbi(["1"], [_ref({}, mapped=0)]))
    assert probe.probe_source("vcf", store.source("v.vcf.gz", b""), index) is None


# --------------------------------------------------------------------------
# bigWig
# --------------------------------------------------------------------------


def test_bigwig_opens_on_its_first_data_block(store):
    chroms = {0: ("chr1", 248_956_422), 1: ("chr2", 242_193_529)}
    data = store.source("c.bw", bigwig(chroms, (1, 5_000, 9_000)))
    assert probe.probe_source("bigwig", data, None) == "chr2:5001-9000"


def test_bigwig_with_a_nested_chromosome_tree_and_no_compression(store):
    chroms = {0: ("1", 1_000_000), 1: ("2", 900_000)}
    data = store.source("c.bw", bigwig(chroms, (0, 100, 200), compressed=False, nested_tree=True))
    assert probe.probe_source("bigwig", data, None) == "1:101-1100"


def test_a_bigwig_window_is_capped(store):
    data = store.source("c.bw", bigwig({0: ("chr1", 10**8)}, (0, 0, 10**7)))
    assert probe.probe_source("bigwig", data, None) == f"chr1:1-{probe._MAX_BLOCK_WINDOW}"


# --------------------------------------------------------------------------
# Failure safety
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["bam", "vcf", "bigwig", "bigbed", "cram", "gtf"])
def test_garbage_never_raises(store, fmt):
    data = store.source("x", b"\x00\x01garbage" * 50)
    index = store.source("x.idx", b"\xff" * 64)
    assert probe.probe_source(fmt, data, index) is None


def test_a_truncated_index_is_unreadable(store):
    full = bai([_ref({LEAF: [(0, 9)]}, mapped=9)])
    data = store.source("r.bam", bam_header(["chr1"]))
    assert probe.probe_source("bam", data, store.source("r.bai", full[:20])) is None


def test_a_missing_file_is_unreadable(store):
    missing = remote_read.ByteSource("depictio_s3", bucket="b", key="nope.bw")
    assert probe.probe_source("bigwig", missing, None) is None


# --------------------------------------------------------------------------
# Tracks: cache and fallthrough
# --------------------------------------------------------------------------


def _track(uri: str, fmt: str, index: str | None = None) -> TrackRow:
    return TrackRow(key=track_key(uri), track_id=uri, name=uri, uri=uri, index_uri=index, fmt=fmt)


@pytest.fixture
def tdc(monkeypatch, store) -> SimpleNamespace:
    monkeypatch.setattr(probe, "s3_base_folder", lambda dc_id, props: "s3://b/genomic_tracks/dc/")
    monkeypatch.setattr(
        remote_read,
        "resolve_location",
        lambda uri, base: remote_read.ByteSource("depictio_s3", bucket="b", key=uri),
    )
    return SimpleNamespace(dc_id="dc1", props=SimpleNamespace())


def test_a_result_is_cached_per_collection_version_and_file(store, tdc):
    store.files["c.bw"] = bigwig({0: ("chr7", 1_000_000)}, (0, 10, 20))
    track = _track("c.bw", "bigwig")
    assert probe.probe_track(tdc, track, None) == "chr7:11-1010"
    reads = len(store.reads)
    assert probe.probe_track(tdc, track, None) == "chr7:11-1010"
    assert len(store.reads) == reads
    probe.probe_track(tdc, track, 3)  # another data version is its own entry
    assert len(store.reads) > reads


def test_a_failure_is_cached_too_and_never_raises(store, tdc):
    track = _track("missing.bw", "bigwig")
    assert probe.probe_track(tdc, track) is None
    reads = len(store.reads)
    assert probe.probe_track(tdc, track) is None
    assert len(store.reads) == reads


def test_the_first_track_with_data_gives_the_region(store, tdc):
    store.files["bad.bw"] = b"nope"
    store.files["ok.bw"] = bigwig({0: ("chr3", 5_000_000)}, (0, 40, 60))
    tracks = [_track("bad.bw", "bigwig"), _track("ok.bw", "bigwig")]
    assert FIRST_REGION(tdc, tracks) == "chr3:41-1040"
    assert FIRST_REGION(tdc, []) is None


def test_an_unresolvable_location_falls_through(store, monkeypatch, tdc):
    def refuse(uri, base):
        raise remote_read.RemoteReadError(403, "host not allow-listed")

    monkeypatch.setattr(remote_read, "resolve_location", refuse)
    assert probe.probe_track(tdc, _track("x.bw", "bigwig")) is None
