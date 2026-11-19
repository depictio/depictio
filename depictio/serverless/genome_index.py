"""Read the indexes of genome files to find the bytes a region needs.

A genome browser reads an indexed file (BAM, tabix-compressed VCF/BED/GFF) a
few blocks at a time: the index says which BGZF blocks of the data file hold
the records overlapping a region. Producer A uses the same arithmetic to ship
only those blocks of a file too big to ship whole (``jbrowse_bundle``).

Covered here, with nothing but the standard library (the producer must run on
the CLI-only install too):

* BAI (``BAI\\1``), the tabix index (``TBI\\1``, BGZF-compressed) and CSI
  (``CSI\\1``, BGZF-compressed, any ``min_shift``/``depth``) — the binning index
  of the SAM/tabix specifications, and the ``reg2bins`` that walks it;
* the reference names of a BAM header (a BAI does not carry them);
* the sequence sizes of a 2bit file and of a FASTA ``.fai``, for an assembly
  whose sequence is too big to ship (the browser then draws the tracks over
  the chromosome lengths alone).

Every parser raises :class:`IndexFormatError` on bytes it does not recognise.
"""

from __future__ import annotations

import re
import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field

#: Largest BGZF block (the SAM spec caps a block, compressed, at 64 KiB). A
#: chunk's end is a virtual offset INTO a block, so a read of the chunk
#: needs up to one whole block past the block it ends in.
BGZF_MAX_BLOCK = 1 << 16

#: Most bytes :func:`bgzf_decompress` inflates. A real tabix/CSI index or BAM
#: header is a few MB decompressed; the ceiling only exists so a crafted file
#: in a track collection cannot exhaust the worker's memory during an export.
MAX_DECOMPRESSED_BYTES = 256 * 1024 * 1024


class IndexFormatError(ValueError):
    """The bytes are not the index (or header) they were read as."""


@dataclass
class RefIndex:
    """One reference's bins: ``bin -> [(begin_voffset, end_voffset)]``."""

    bins: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    #: The linear index (BAI/TBI): the smallest offset per 16 kb window.
    linear: list[int] = field(default_factory=list)
    #: CSI: the smallest offset of each bin's records.
    loffsets: dict[int, int] = field(default_factory=dict)


@dataclass
class BinningIndex:
    """A parsed BAI / TBI / CSI."""

    kind: str  # "BAI" | "TBI" | "CSI"
    min_shift: int
    depth: int
    refs: list[RefIndex]
    #: Reference names, when the index carries them (TBI, tabix-style CSI).
    names: list[str] = field(default_factory=list)

    def first_data_block(self) -> int | None:
        """File offset of the BGZF block holding the first record."""
        pseudo = pseudo_bin(self.depth)
        offsets = [
            beg >> 16
            for ref in self.refs
            for b, chunks in ref.bins.items()
            if b != pseudo
            for beg, _ in chunks
        ]
        return min(offsets) if offsets else None

    def chunks_for(self, ref_id: int, start: int, end: int) -> list[tuple[int, int]]:
        """Chunks that may hold records overlapping ``[start, end)`` (0-based)."""
        if ref_id < 0 or ref_id >= len(self.refs):
            return []
        ref = self.refs[ref_id]
        floor = self._min_offset(ref, start)
        out: list[tuple[int, int]] = []
        for b in reg2bins(start, end, self.min_shift, self.depth):
            out.extend(c for c in ref.bins.get(b, ()) if c[1] > floor)
        return sorted(out)

    def _min_offset(self, ref: RefIndex, start: int) -> int:
        """No record overlapping ``start`` onwards begins before this offset.

        BAI/TBI: the linear index (smallest offset per 16 kb window); CSI: the
        ``loffset`` of the deepest bin holding ``start``. The higher-level bins
        a region crosses also hold records far before it, which a reader skips
        with this — and so does the slicer, or it would ship them.
        """
        if self.kind == "CSI":
            level_start = ((1 << (self.depth * 3)) - 1) // 7
            b = level_start + (start >> self.min_shift)
            while b > 0 and b not in ref.loffsets:
                b = (b - 1) >> 3  # the parent bin
            return ref.loffsets.get(b, 0)
        if not ref.linear:
            return 0
        return ref.linear[min(start >> 14, len(ref.linear) - 1)]

    def block_ranges_for(self, ref_id: int, start: int, end: int) -> list[tuple[int, int]]:
        """File byte ranges ``[first, last]`` a reader of the region touches."""
        return [
            (beg >> 16, (stop >> 16) + BGZF_MAX_BLOCK - 1)
            for beg, stop in self.chunks_for(ref_id, start, end)
        ]


def pseudo_bin(depth: int) -> int:
    """The bin that holds a reference's mapped/unmapped counts, not records
    (37450 for BAI/TBI's depth 5)."""
    return ((1 << ((depth + 1) * 3)) - 1) // 7 + 1


def reg2bins(beg: int, end: int, min_shift: int = 14, depth: int = 5) -> list[int]:
    """Bins overlapping ``[beg, end)``, the SAM/CSI specification's algorithm."""
    end = max(end, beg + 1)
    bins: list[int] = []
    end -= 1
    t = 0
    s = min_shift + depth * 3
    for level in range(depth + 1):
        b = t + (beg >> s)
        e = t + (end >> s)
        bins.extend(range(b, e + 1))
        s -= 3
        t += 1 << (level * 3)
    return bins


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, fmt: str) -> tuple:
        size = struct.calcsize(fmt)
        if self.pos + size > len(self.data):
            raise IndexFormatError("index ends early")
        out = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += size
        return out

    def one(self, fmt: str) -> int:
        return self.take(fmt)[0]

    def raw(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise IndexFormatError("index ends early")
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out


def bgzf_decompress(data: bytes, limit: int | None = None, max_output: int | None = None) -> bytes:
    """Concatenated gzip members (BGZF) decompressed, up to ``limit`` bytes.

    A truncated last member (the caller read a prefix of the file) is decoded
    as far as it goes.

    Never inflates more than ``max_output`` bytes (default
    :data:`MAX_DECOMPRESSED_BYTES`): the input comes from a data collection, and
    a few MB of crafted gzip can expand to gigabytes. With a ``limit`` at or
    under the cap the output is cut there, as asked; past the cap it is an
    :class:`IndexFormatError`, never a partial result read as a whole one.
    """
    max_output = MAX_DECOMPRESSED_BYTES if max_output is None else max_output
    cap = max_output if limit is None else min(limit, max_output)
    out = bytearray()
    buf = data
    while buf:
        d = zlib.decompressobj(31)
        try:
            # One byte past the cap tells a stream that overflows it from one
            # that ends exactly on it.
            out += d.decompress(buf, cap - len(out) + 1)
        except zlib.error as exc:
            if out:
                break
            raise IndexFormatError(f"not BGZF/gzip data: {exc}") from exc
        if len(out) > cap:
            if limit is not None and limit <= max_output:
                return bytes(out[:limit])
            raise IndexFormatError(
                f"decompresses past {max_output // (1024 * 1024)} MB; refused as an index"
            )
        if limit is not None and len(out) >= limit:
            break
        if not d.eof:
            break
        buf = d.unused_data
    return bytes(out)


def _maybe_gunzip(data: bytes) -> bytes:
    return bgzf_decompress(data) if data[:2] == b"\x1f\x8b" else data


def _tabix_names(blob: bytes) -> list[str]:
    return [n.decode("utf-8", "replace") for n in blob.split(b"\x00") if n]


def parse_index(data: bytes) -> BinningIndex:
    """A BAI, TBI or CSI file's bytes (compressed or not) as a :class:`BinningIndex`."""
    raw = _maybe_gunzip(data)
    magic = raw[:4]
    r = _Reader(raw)
    r.raw(4)
    if magic == b"BAI\x01":
        n_ref = r.one("<i")
        return BinningIndex("BAI", 14, 5, [_bai_ref(r) for _ in range(n_ref)])
    if magic == b"TBI\x01":
        n_ref, _fmt, _cs, _cb, _ce, _meta, _skip, l_nm = r.take("<8i")
        names = _tabix_names(r.raw(l_nm))
        refs = [_bai_ref(r) for _ in range(n_ref)]
        return BinningIndex("TBI", 14, 5, refs, names)
    if magic == b"CSI\x01":
        min_shift, depth, l_aux = r.take("<3i")
        aux = r.raw(l_aux)
        names: list[str] = []
        if l_aux >= 28:
            # Tabix-style CSI: the aux block is the tabix header.
            l_nm = struct.unpack_from("<i", aux, 24)[0]
            names = _tabix_names(aux[28 : 28 + l_nm])
        n_ref = r.one("<i")
        refs = []
        for _ in range(n_ref):
            ref = RefIndex()
            for _ in range(r.one("<i")):
                b, loffset, n_chunk = r.take("<IQi")
                ref.loffsets[b] = loffset
                ref.bins[b] = [r.take("<QQ") for _ in range(n_chunk)]  # type: ignore[misc]
            refs.append(ref)
        return BinningIndex("CSI", min_shift, depth, refs, names)
    raise IndexFormatError(f"not a BAI/TBI/CSI index (magic {magic!r})")


def _bai_ref(r: _Reader) -> RefIndex:
    ref = RefIndex()
    for _ in range(r.one("<i")):
        b, n_chunk = r.take("<Ii")
        ref.bins[b] = [r.take("<QQ") for _ in range(n_chunk)]  # type: ignore[misc]
    n_intv = r.one("<i")
    ref.linear = list(r.take(f"<{n_intv}Q")) if n_intv else []
    return ref


def bam_ref_names(header_bytes: bytes) -> list[str]:
    """Reference names of a BAM, from a prefix of the (BGZF) file holding its header."""
    raw = bgzf_decompress(header_bytes)
    if raw[:4] != b"BAM\x01":
        raise IndexFormatError("not a BAM file")
    r = _Reader(raw)
    r.raw(4)
    l_text = r.one("<i")
    r.raw(l_text)
    n_ref = r.one("<i")
    names = []
    for _ in range(n_ref):
        l_name = r.one("<i")
        names.append(r.raw(l_name).rstrip(b"\x00").decode("utf-8", "replace"))
        r.one("<i")  # l_ref
    return names


# --- assembly sizes ------------------------------------------------------------

TWOBIT_MAGIC = 0x1A412743


def twobit_index(head: bytes) -> tuple[str, list[tuple[str, int]]]:
    """``(byte order, [(name, record offset)])`` from a 2bit file's first bytes.

    Raises :class:`IndexFormatError` when ``head`` does not hold the whole
    index; the caller reads a longer prefix (the index needs at most
    ``16 + count * (1 + 255 + 8)`` bytes).
    """
    if len(head) < 16:
        raise IndexFormatError("2bit header ends early")
    for order in ("<", ">"):
        if struct.unpack_from(f"{order}I", head, 0)[0] == TWOBIT_MAGIC:
            break
    else:
        raise IndexFormatError("not a 2bit file")
    version, count = struct.unpack_from(f"{order}II", head, 4)
    offset_fmt = "Q" if version == 1 else "I"
    pos = 16
    entries = []
    for _ in range(count):
        if pos >= len(head):
            raise IndexFormatError("2bit index ends early")
        n = head[pos]
        name = head[pos + 1 : pos + 1 + n].decode("ascii", "replace")
        pos += 1 + n
        size = struct.calcsize(offset_fmt)
        if pos + size > len(head):
            raise IndexFormatError("2bit index ends early")
        entries.append((name, struct.unpack_from(f"{order}{offset_fmt}", head, pos)[0]))
        pos += size
    return order, entries


def twobit_count(head: bytes) -> int:
    """How many sequences a 2bit file holds (from its 16-byte header)."""
    if len(head) < 16:
        raise IndexFormatError("2bit header ends early")
    for order in ("<", ">"):
        if struct.unpack_from(f"{order}I", head, 0)[0] == TWOBIT_MAGIC:
            return struct.unpack_from(f"{order}I", head, 8)[0]
    raise IndexFormatError("not a 2bit file")


def fai_sizes(text: str) -> list[tuple[str, int]]:
    """``[(name, length)]`` of a FASTA index (``.fai``)."""
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip().isdigit():
            out.append((parts[0], int(parts[1])))
    return out


def chrom_sizes_text(sizes: list[tuple[str, int]]) -> str:
    return "".join(f"{name}\t{length}\n" for name, length in sizes)


def parse_chrom_sizes(text: str) -> list[tuple[str, int]]:
    out = []
    for line in text.splitlines():
        parts = line.strip().split("\t")
        if len(parts) >= 2 and parts[1].isdigit():
            out.append((parts[0], int(parts[1])))
    return out


def parse_aliases(text: str) -> list[set[str]]:
    """Alias groups of a refName alias table (one row of synonyms per line)."""
    groups = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        names = {n for n in re.split(r"\t", line.strip()) if n}
        if len(names) > 1:
            groups.append(names)
    return groups


# --- loci ----------------------------------------------------------------------

_LOCUS = re.compile(
    r"^\s*(?P<ref>[^:\s]+)(?::(?P<start>[\d,]+)(?:(?:-|\.\.)(?P<end>[\d,]+))?)?\s*$"
)


@dataclass(frozen=True)
class Locus:
    ref: str
    start: int  # 0-based
    end: int | None  # exclusive; None = to the end of the reference

    def widened(self, length: int | None) -> Locus:
        """The locus plus its own width on each side: the browser fetches the
        blocks around the view, not only the view."""
        if self.end is None:
            return self
        width = max(self.end - self.start, 1)
        end = self.end + width
        if length is not None:
            end = min(end, length)
        return Locus(self.ref, max(self.start - width, 0), end)

    def label(self) -> str:
        if self.end is None:
            return self.ref
        return f"{self.ref}:{self.start + 1:,}-{self.end:,}"


def parse_locus(text: str | None) -> Locus | None:
    """A JBrowse locus string (``chr8:6,000,000-14,000,000``, ``ctgA:1..20``, ``chr1``)."""
    if not text:
        return None
    # A multi-region opening ("a:1-2 b:3-4") frames its first region.
    first = str(text).split()[0] if str(text).split() else ""
    m = _LOCUS.match(first)
    if not m:
        return None
    ref = m.group("ref")
    if m.group("start") is None:
        return Locus(ref, 0, None)
    start = int(m.group("start").replace(",", ""))
    end_s = m.group("end")
    end = int(end_s.replace(",", "")) if end_s else start
    if end < start:
        start, end = end, start
    return Locus(ref, max(start - 1, 0), end)


def ref_candidates(ref: str, aliases: Sequence[set[str]] = ()) -> list[str]:
    """Names ``ref`` may carry in a file: itself, its aliases, with/without ``chr``."""
    out = [ref]
    for group in aliases:
        if ref in group:
            out.extend(sorted(group - {ref}))
    more = []
    for name in out:
        if name.lower().startswith("chr"):
            more.append(name[3:])
        else:
            more.append(f"chr{name}")
        if name in ("M", "chrM"):
            more.extend(["MT", "chrMT"])
        if name in ("MT", "chrMT"):
            more.extend(["M", "chrM"])
    seen: list[str] = []
    for name in out + more:
        if name not in seen:
            seen.append(name)
    return seen


def find_ref(names: list[str], ref: str, aliases: Sequence[set[str]] = ()) -> int:
    """Index of ``ref`` among a file's reference ``names``, or -1."""
    lookup = {n: i for i, n in enumerate(names)}
    for cand in ref_candidates(ref, aliases):
        if cand in lookup:
            return lookup[cand]
    return -1
