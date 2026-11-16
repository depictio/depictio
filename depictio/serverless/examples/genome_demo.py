"""A tiny synthetic genome for the offline genome browser: files, session, manifest.

Writes, with the standard library only (deterministic: one seeded RNG):

* ``demo.fa`` + ``demo.fa.fai`` — two contigs, ``ctgA`` and ``ctgB``;
* ``reads.bam`` + ``reads.bam.bai`` — paired-free 100 bp reads tiling
  ``ctgA``, a BGZF file several JBrowse pages long, so that producer A's slicer
  ships only the pages the opening locus needs;
* ``genes.bed`` — a plain BED of features (shipped whole);
* ``coverage.bedgraph`` — a plain bedGraph signal (shipped whole).

Used by the unit tests (``tests/unit/serverless/test_jbrowse_bundle.py``) and
by ``generate_genome_demo_manifest`` below, which runs the session through
:func:`depictio.serverless.jbrowse_bundle.bundle_session` — the code producer A
runs — and writes the committed demo manifest the offline Playwright spec
opens (``depictio/viewer/demo/manifests/genome.json``):

    DEPICTIO_CONTEXT=cli uv run --extra dev python \\
        depictio/serverless/examples/genome_demo.py
"""

from __future__ import annotations

import json
import random
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTIGS = {"ctgA": 160_000, "ctgB": 5_000}
READ_LEN = 100
READ_STEP = 4
#: The session opens here; the slicer keeps the pages around it.
LOCATION = "ctgA:150,001-150,600"

_BGZF_EOF = bytes.fromhex("1f8b08040000000000ff0600424302001b0003000000000000000000")


# --- BGZF ----------------------------------------------------------------------


def _bgzf_block(data: bytes) -> bytes:
    comp = zlib.compressobj(6, zlib.DEFLATED, -15)
    body = comp.compress(data) + comp.flush()
    bsize = len(body) + 25
    header = b"\x1f\x8b\x08\x04\x00\x00\x00\x00\x00\xff\x06\x00BC\x02\x00" + struct.pack(
        "<H", bsize
    )
    return header + body + struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data))


class BgzfWriter:
    """Accumulates records; ``voffset()`` is the virtual offset of the next byte."""

    BLOCK = 0xFF00

    def __init__(self) -> None:
        self.out = bytearray()
        self.buf = bytearray()

    def voffset(self) -> int:
        return (len(self.out) << 16) | len(self.buf)

    def write(self, data: bytes) -> None:
        self.buf += data

    def flush_block(self) -> None:
        if self.buf:
            self.out += _bgzf_block(bytes(self.buf))
            self.buf = bytearray()

    def maybe_flush(self) -> None:
        if len(self.buf) >= self.BLOCK:
            self.flush_block()

    def close(self) -> bytes:
        self.flush_block()
        return bytes(self.out) + _BGZF_EOF


# --- BAM + BAI -----------------------------------------------------------------


def _reg2bin(beg: int, end: int) -> int:
    end -= 1
    if beg >> 14 == end >> 14:
        return ((1 << 15) - 1) // 7 + (beg >> 14)
    if beg >> 17 == end >> 17:
        return ((1 << 12) - 1) // 7 + (beg >> 17)
    if beg >> 20 == end >> 20:
        return ((1 << 9) - 1) // 7 + (beg >> 20)
    if beg >> 23 == end >> 23:
        return ((1 << 6) - 1) // 7 + (beg >> 23)
    if beg >> 26 == end >> 26:
        return ((1 << 3) - 1) // 7 + (beg >> 26)
    return 0


_NT = {"=": 0, "A": 1, "C": 2, "G": 4, "T": 8, "N": 15}


def _bam_record(ref_id: int, pos: int, name: str, seq: str, flag: int = 0) -> bytes:
    l_seq = len(seq)
    name_b = name.encode() + b"\x00"
    cigar = struct.pack("<I", (l_seq << 4) | 0)  # <l_seq>M
    packed = bytearray()
    for i in range(0, l_seq, 2):
        hi = _NT[seq[i]]
        lo = _NT[seq[i + 1]] if i + 1 < l_seq else 0
        packed.append((hi << 4) | lo)
    qual = bytes([30] * l_seq)
    core = struct.pack(
        "<iiBBHHHiiii",
        ref_id,
        pos,
        len(name_b),
        60,
        _reg2bin(pos, pos + l_seq),
        1,
        flag,
        l_seq,
        -1,
        -1,
        0,
    )
    body = core + name_b + cigar + bytes(packed) + qual
    return struct.pack("<i", len(body)) + body


@dataclass
class _Read:
    ref_id: int
    pos: int
    end: int
    beg_v: int
    end_v: int


def write_bam(path: Path, genome: dict[str, str], rng: random.Random) -> None:
    """``path`` and ``path.bai``: reads tiling the first contig, with mismatches."""
    names = list(genome)
    text = "@HD\tVN:1.6\tSO:coordinate\n" + "".join(
        f"@SQ\tSN:{n}\tLN:{len(s)}\n" for n, s in genome.items()
    )
    w = BgzfWriter()
    header = b"BAM\x01" + struct.pack("<i", len(text)) + text.encode()
    header += struct.pack("<i", len(names))
    for n, s in genome.items():
        nb = n.encode() + b"\x00"
        header += struct.pack("<i", len(nb)) + nb + struct.pack("<i", len(s))
    w.write(header)
    w.flush_block()
    reads: list[_Read] = []
    ref = genome[names[0]]
    for i, pos in enumerate(range(0, len(ref) - READ_LEN, READ_STEP)):
        seq = list(ref[pos : pos + READ_LEN])
        for _ in range(2):  # sequencing errors: JBrowse draws mismatches
            j = rng.randrange(READ_LEN)
            seq[j] = rng.choice("ACGT")
        beg_v = w.voffset()
        w.write(_bam_record(0, pos, f"r{i:06d}", "".join(seq), flag=16 if i % 2 else 0))
        reads.append(_Read(0, pos, pos + READ_LEN, beg_v, w.voffset()))
        w.maybe_flush()
    data = w.close()
    # Virtual end offsets recorded at the end of a buffered block point past
    # its data; they are equivalent to the next block's offset 0 for readers.
    path.write_bytes(data)
    path.with_name(path.name + ".bai").write_bytes(_bai(reads, len(names)))


def _bai(reads: list[_Read], n_ref: int) -> bytes:
    per_ref: list[dict[int, list[list[int]]]] = [{} for _ in range(n_ref)]
    linear: list[dict[int, int]] = [{} for _ in range(n_ref)]
    for r in reads:
        b = _reg2bin(r.pos, r.end)
        chunks = per_ref[r.ref_id].setdefault(b, [])
        if chunks and chunks[-1][1] == r.beg_v:
            chunks[-1][1] = r.end_v
        else:
            chunks.append([r.beg_v, r.end_v])
        for win in range(r.pos >> 14, ((r.end - 1) >> 14) + 1):
            linear[r.ref_id].setdefault(win, r.beg_v)
    out = bytearray(b"BAI\x01" + struct.pack("<i", n_ref))
    for ref_id in range(n_ref):
        bins = per_ref[ref_id]
        out += struct.pack("<i", len(bins))
        for b in sorted(bins):
            out += struct.pack("<Ii", b, len(bins[b]))
            for beg, end in bins[b]:
                out += struct.pack("<QQ", beg, end)
        lin = linear[ref_id]
        n_intv = (max(lin) + 1) if lin else 0
        out += struct.pack("<i", n_intv)
        last = 0
        for win in range(n_intv):
            last = lin.get(win, last)
            out += struct.pack("<Q", last)
    return bytes(out)


# --- tabix (for the slicer's tests) ---------------------------------------------


def write_tabix_bed(path: Path, rows: list[tuple[str, int, int, str]], names: list[str]) -> None:
    """A bgzipped BED and its ``.tbi`` (the tabix index of the SAM/tabix spec)."""
    w = BgzfWriter()
    per_ref: list[dict[int, list[list[int]]]] = [{} for _ in names]
    linear: list[dict[int, int]] = [{} for _ in names]
    for chrom, start, end, label in rows:
        ref_id = names.index(chrom)
        beg_v = w.voffset()
        w.write(f"{chrom}\t{start}\t{end}\t{label}\n".encode())
        end_v = w.voffset()
        b = _reg2bin(start, end)
        chunks = per_ref[ref_id].setdefault(b, [])
        if chunks and chunks[-1][1] == beg_v:
            chunks[-1][1] = end_v
        else:
            chunks.append([beg_v, end_v])
        for win in range(start >> 14, ((end - 1) >> 14) + 1):
            linear[ref_id].setdefault(win, beg_v)
        w.maybe_flush()
    path.write_bytes(w.close())
    nm = b"".join(n.encode() + b"\x00" for n in names)
    idx = bytearray(b"TBI\x01" + struct.pack("<8i", len(names), 0, 1, 2, 3, ord("#"), 0, len(nm)))
    idx += nm
    for ref_id in range(len(names)):
        bins = per_ref[ref_id]
        idx += struct.pack("<i", len(bins))
        for b in sorted(bins):
            idx += struct.pack("<Ii", b, len(bins[b]))
            for beg, end in bins[b]:
                idx += struct.pack("<QQ", beg, end)
        lin = linear[ref_id]
        n_intv = (max(lin) + 1) if lin else 0
        idx += struct.pack("<i", n_intv)
        last = 0
        for win in range(n_intv):
            last = lin.get(win, last)
            idx += struct.pack("<Q", last)
    w2 = BgzfWriter()
    w2.write(bytes(idx))
    path.with_name(path.name + ".tbi").write_bytes(w2.close())


# --- the demo files ------------------------------------------------------------


def write_demo_files(root: Path, seed: int = 7) -> dict[str, Path]:
    rng = random.Random(seed)
    root.mkdir(parents=True, exist_ok=True)
    genome = {n: "".join(rng.choice("ACGT") for _ in range(n_len)) for n, n_len in CONTIGS.items()}
    fasta = root / "demo.fa"
    lines, fai = [], []
    offset = 0
    for name, seq in genome.items():
        head = f">{name}\n"
        offset += len(head)
        fai.append(f"{name}\t{len(seq)}\t{offset}\t60\t61\n")
        body = "".join(seq[i : i + 60] + "\n" for i in range(0, len(seq), 60))
        lines.append(head + body)
        offset += len(body)
    fasta.write_text("".join(lines))
    (root / "demo.fa.fai").write_text("".join(fai))
    write_bam(root / "reads.bam", genome, rng)
    genes = [
        ("ctgA", 149_200, 149_900, "geneAlpha", "+"),
        ("ctgA", 150_100, 150_450, "geneBeta", "-"),
        ("ctgA", 150_700, 151_800, "geneGamma", "+"),
        ("ctgB", 1_000, 2_000, "geneDelta", "+"),
    ]
    (root / "genes.bed").write_text(
        "".join(f"{c}\t{s}\t{e}\t{n}\t0\t{st}\n" for c, s, e, n, st in genes)
    )
    bg = []
    for start in range(0, CONTIGS["ctgA"], 200):
        value = 20 + 15 * ((start // 200) % 7) + rng.randrange(5)
        bg.append(f"ctgA\t{start}\t{start + 200}\t{value}\n")
    (root / "coverage.bedgraph").write_text("".join(bg))
    return {p.name: p for p in root.iterdir()}


# --- the session render_jbrowse would return -------------------------------------


def _loc(name: str) -> dict[str, str]:
    return {"uri": f"demo://{name}", "locationType": "UriLocation"}


def demo_session() -> dict[str, Any]:
    """A frozen ``render_jbrowse`` answer over the demo files (``demo://`` URIs)."""
    tracks = [
        {
            "type": "FeatureTrack",
            "trackId": "demo-genes",
            "name": "Genes",
            "assemblyNames": ["demo"],
            "category": ["Annotation"],
            "adapter": {"type": "BedAdapter", "bedLocation": _loc("genes.bed")},
        },
        {
            "type": "QuantitativeTrack",
            "trackId": "demo-coverage",
            "name": "Coverage",
            "assemblyNames": ["demo"],
            "category": ["Signal"],
            "adapter": {"type": "BedGraphAdapter", "bedGraphLocation": _loc("coverage.bedgraph")},
        },
        {
            "type": "AlignmentsTrack",
            "trackId": "demo-reads",
            "name": "Reads",
            "assemblyNames": ["demo"],
            "category": ["Alignments"],
            "adapter": {
                "type": "BamAdapter",
                "bamLocation": _loc("reads.bam"),
                "index": {"indexType": "BAI", "location": _loc("reads.bam.bai")},
            },
        },
    ]
    rows = [
        {
            "track_id": t["trackId"],
            "name": t["name"],
            "format": {"demo-genes": "bed", "demo-coverage": "bedgraph", "demo-reads": "bam"}[
                t["trackId"]
            ],
            "sample": None,
            "selection_value": None,
            "category": t["category"][0],
            "color": None,
            "group": None,
            "source": "manifest",
            "uri": t["trackId"],
            "index_uri": None,
            "storage": "depictio",
        }
        for t in tracks
    ]
    return {
        "assembly": {
            "name": "demo",
            "displayName": "Synthetic demo genome",
            "sequence": {
                "type": "ReferenceSequenceTrack",
                "trackId": "demo-ReferenceSequenceTrack",
                "adapter": {
                    "type": "IndexedFastaAdapter",
                    "fastaLocation": _loc("demo.fa"),
                    "faiLocation": _loc("demo.fa.fai"),
                },
            },
        },
        "tracks": tracks,
        "shown_track_ids": [t["trackId"] for t in tracks],
        "location": LOCATION,
        "opening": "yaml",
        "mate_location": None,
        "picked": None,
        "view": {"hideHeader": False, "hideHeaderOverview": True, "trackLabels": "offset"},
        "configuration": {},
        "track_rows": rows,
        "selection_column": None,
        "tracks_dc_id": "000000000000000000000000",
        "filter_applied": False,
        "total_tracks": len(tracks),
        "matched_tracks": len(tracks),
        "truncated": False,
        "max_tracks": 12,
        "force_load": False,
        "ucsc_missing": [],
        "data_version": None,
        "variant_legend": None,
        "remote_base": None,
        "assembly_kind": "custom",
        "sv_track_ids": [],
        "read_pairs_display": "pileup",
        "display": None,
        "locus_source": None,
    }


class LocalFile:
    """A ``jbrowse_bundle.FileSource`` over a file on disk."""

    def __init__(self, path: Path, label: str | None = None):
        self.path = path
        self.label = label or path.name

    def size(self) -> int:
        return self.path.stat().st_size

    def read(self, start: int, end: int) -> bytes:
        with self.path.open("rb") as fh:
            fh.seek(start)
            return fh.read(end - start + 1)


def demo_opener(root: Path):
    from depictio.serverless.jbrowse_bundle import SourceRefused

    def open_uri(uri: str) -> LocalFile:
        if not uri.startswith("demo://"):
            raise SourceRefused(f"not a demo file: {uri}")
        path = root / uri.removeprefix("demo://")
        if not path.is_file():
            raise SourceRefused(f"no such demo file: {path.name}")
        return LocalFile(path)

    return open_uri


# --- the committed demo manifest -------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT = REPO_ROOT / "depictio" / "viewer" / "demo" / "manifests" / "genome.json"
DASHBOARD_ID = "6a6a6a6a6a6a6a6a6a6a6a6a"


def build_demo_manifest(root: Path) -> dict[str, Any]:
    from depictio.models.models.serverless import (
        BundleManifest,
        BundleMode,
        ComponentTier,
        DashboardSection,
        FrozenPayload,
        Producer,
        TierEntry,
        TierReason,
    )
    from depictio.serverless.addons import addon_entry
    from depictio.serverless.jbrowse_bundle import bundle_session
    from depictio.serverless.objects import ObjectBudget

    write_demo_files(root)
    inline_blobs: dict[str, str] = {}
    # A small-file threshold under the BAM's size, so the demo ships its reads
    # sliced to the opening locus (a real export slices files past 1 MB).
    result = bundle_session(
        demo_session(), demo_opener(root), ObjectBudget(), inline_blobs, small_file_bytes=64 * 1024
    )
    addon = addon_entry("jbrowse", "genome browser tiles: Reads over the demo genome")
    if addon is None:
        raise SystemExit(
            "the jbrowse add-on is not built: run `pnpm run build:static` in depictio/viewer first"
        )
    text = {
        "index": "text-genome",
        "component_type": "text",
        "title": "A genome browser, offline",
        "body": (
            "Reads, genes and a signal over a synthetic genome, drawn by JBrowse from "
            "files shipped inside this HTML. The reads were sliced to the opening locus.\n"
        ),
        "alignment": "left",
        "surface": "none",
        "title_align": "left",
        "vertical_alignment": "center",
        "dc_id": None,
        "wf_id": None,
        "workflow_tag": "",
        "data_collection_tag": "",
        "description": "",
        "order": 1,
    }
    browser = {
        "index": "genome-browser",
        "component_type": "jbrowse",
        "title": "Reads over the demo genome",
        "description": "BAM sliced to the opening locus, BED and bedGraph shipped whole",
        "workflow_tag": "genome_demo",
        "data_collection_tag": "tracks",
        "wf_id": None,
        "dc_id": None,
        "location": LOCATION,
        "show_header": True,
        "show_overview": False,
        "track_labels": "offset",
        "selection_enabled": False,
        "views": [],
    }
    doc = {
        "title": "Genome browser — static bundle example",
        "subtitle": "JBrowse over bundled genome files (a sliced BAM, a BED, a bedGraph)",
        "stored_metadata": [text, browser],
        "left_panel_layout_data": [],
        "right_panel_layout_data": [
            {"i": "box-text-genome", "x": 0, "y": 0, "w": 8, "h": 1, "static": False},
            {"i": "box-genome-browser", "x": 0, "y": 1, "w": 8, "h": 9, "static": False},
        ],
        "stored_layout_data": [],
    }
    manifest = BundleManifest(
        mode=BundleMode.SINGLE_FILE,
        producer=Producer.EXPORT_FROM_INSTANCE,
        built_at="2026-01-01T00:00:00+00:00",
        depictio_version="demo",
        dashboard=DashboardSection(id=DASHBOARD_ID, title=doc["title"], doc=doc),
        tiers={
            "text-genome": TierEntry(tier=ComponentTier.LIVE),
            "genome-browser": TierEntry(
                tier=ComponentTier.FROZEN, reason=TierReason.JBROWSE, detail=result.detail()
            ),
        },
        frozen={"genome-browser": FrozenPayload(kind="jbrowse", payload=result.payload)},
        inline_blobs=inline_blobs,
        addons=[addon],
    )
    return manifest.model_dump(mode="json")


def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        manifest = build_demo_manifest(Path(tmp))
    OUT.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(REPO_ROOT)} ({OUT.stat().st_size / 1024:.0f} KiB)")
    print("genome-browser:", manifest["tiers"]["genome-browser"]["detail"])


if __name__ == "__main__":
    main()
