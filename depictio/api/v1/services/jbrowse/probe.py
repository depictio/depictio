"""Find a region of a track that holds data, from its index alone.

A browser opened on a fixed locus (a gene, a contig) often shows empty tracks.
This reads the few kilobytes of index a track already has, never the data:

- BAM: the reference with the most reads (the BAI's pseudo-bin 37450 carries
  the mapped-read count), named from the BAM header;
- VCF / BED / GFF (tabix): the first reference with data, named by the TBI (or
  the CSI's tabix header);
- bigWig / bigBed: the first data block, named by the chromosome tree.

Within a reference the window is the densest bin of the index (the one whose
chunks span the most bytes). Everything is read through ``remote_read`` ranges,
so a track in Depictio's bucket and one read in place behave alike. Any failure
(an unreadable index, a format not handled, a truncated file) returns None and
the caller falls back to its next opening level. Results are cached per
(collection, data version, file).
"""

from __future__ import annotations

import struct
import threading
import time
import zlib

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services import remote_read
from depictio.api.v1.services.jbrowse.tracks import TrackRow, TracksDC, s3_base_folder

# Pseudo-bin of a BAI / TBI reference: its second chunk is (mapped, unmapped).
PSEUDO_BIN = 37450
_MAX_INDEX_BYTES = 64 * 1024 * 1024
_MAX_HEADER_BYTES = 4 * 1024 * 1024
_MAX_INFLATED_BYTES = 256 * 1024 * 1024
# A bin wider than this names its contig rather than a region (see ``_window``);
# a bigWig block is cut to ``_MAX_BLOCK_WINDOW``, which a data block of a dense
# track would otherwise exceed.
_MAX_SPAN = 1 << 25
_MAX_BLOCK_WINDOW = 65_536
_MAX_TRACKS_PROBED = 3

_CACHE_TTL_S = 600.0
_CACHE_MAX = 512
_cache: dict[tuple[str, int | None, str], tuple[float, str | None]] = {}
_cache_lock = threading.Lock()


class ProbeError(Exception):
    """The index could not be parsed; never leaves this module."""


# --------------------------------------------------------------------------
# Byte helpers
# --------------------------------------------------------------------------


def _read(src: remote_read.ByteSource, start: int, length: int) -> bytes:
    size = remote_read.source_size(src)
    if start >= size:
        return b""
    end = min(start + length, size) - 1
    return b"".join(remote_read.open_range(src, remote_read.ByteRange(start, end)))


def _inflate_bgzf(data: bytes, limit: int = _MAX_INFLATED_BYTES) -> bytes:
    """Concatenated gzip members (BGZF) inflated; a truncated tail is dropped."""
    out: list[bytes] = []
    total = 0
    buf = data
    while buf and total < limit:
        decoder = zlib.decompressobj(31)
        try:
            chunk = decoder.decompress(buf)
        except zlib.error:
            break
        out.append(chunk)
        total += len(chunk)
        if not decoder.eof:
            break
        buf = decoder.unused_data
    return b"".join(out)


def _window(name: str, start: int, span: int) -> str:
    """``name:start-end`` of ``span`` bases from the 0-based ``start``.

    A span past ``_MAX_SPAN`` (a bin that covers most of the contig) says
    little about where the data is: the whole contig is named instead.
    """
    if span > _MAX_SPAN:
        return name
    return f"{name}:{start + 1}-{start + max(span, 1)}"


# --------------------------------------------------------------------------
# Binning index (BAI / TBI / CSI)
# --------------------------------------------------------------------------


def _bin_window(bin_id: int, min_shift: int, depth: int) -> tuple[int, int, int]:
    """(level, start, span) of a bin; level ``depth`` is the leaf level."""
    for level in range(depth, -1, -1):
        offset = ((1 << (3 * level)) - 1) // 7
        if bin_id >= offset:
            span = 1 << (min_shift + 3 * (depth - level))
            return level, (bin_id - offset) * span, span
    raise ProbeError(f"bin {bin_id} out of range")


def _densest_bin(bins: list[tuple[int, int]], min_shift: int, depth: int) -> tuple[int, int] | None:
    """(start, span) of the deepest, then largest, bin among ``(bin, size)``."""
    best: tuple[int, int, int, int] | None = None  # (level, size, start, span)
    for bin_id, size in bins:
        if bin_id == PSEUDO_BIN:
            continue
        level, start, span = _bin_window(bin_id, min_shift, depth)
        if best is None or (level, size) > (best[0], best[1]):
            best = (level, size, start, span)
    return None if best is None else (best[2], best[3])


def _ref_bins(
    buf: bytes, p: int, csi: bool, collect: bool
) -> tuple[list[tuple[int, int]], int, int]:
    """(bins as ``(bin, chunk bytes)``, mapped reads, next position) of one reference.

    ``collect`` False only counts: chunks are jumped over, which is what picking
    the reference needs. ``mapped`` is read from the pseudo-bin (-1 when absent).
    """
    (n_bin,) = struct.unpack_from("<i", buf, p)
    p += 4
    bins: list[tuple[int, int]] = []
    mapped = -1
    for _ in range(n_bin):
        (bin_id,) = struct.unpack_from("<I", buf, p)
        p += 4
        if csi:
            p += 8  # loffset
        (n_chunk,) = struct.unpack_from("<i", buf, p)
        p += 4
        if bin_id == PSEUDO_BIN and n_chunk == 2:
            mapped = struct.unpack_from("<Q", buf, p + 16)[0]
        elif collect:
            size = 0
            for beg, end in struct.iter_unpack("<QQ", buf[p : p + 16 * n_chunk]):
                size += max(end - beg, 0)
            bins.append((bin_id, size))
        p += 16 * n_chunk
        if p > len(buf):
            raise ProbeError("truncated index")
    return bins, mapped, p


def _bai_reference(buf: bytes) -> tuple[int, list[tuple[int, int]]]:
    """(index of the reference with the most reads, its bins) of a BAI."""
    if buf[:4] != b"BAI\x01":
        raise ProbeError("not a BAI")
    (n_ref,) = struct.unpack_from("<i", buf, 4)
    p = 8
    best: tuple[int, int, int] | None = None  # (mapped, ref, start position)
    for ref in range(n_ref):
        start = p
        _, mapped, p = _ref_bins(buf, p, csi=False, collect=False)
        (n_intv,) = struct.unpack_from("<i", buf, p)
        p += 4 + 8 * n_intv
        if mapped > 0 and (best is None or mapped > best[0]):
            best = (mapped, ref, start)
    if best is None:
        raise ProbeError("no mapped reads in the index")
    bins, _, _ = _ref_bins(buf, best[2], csi=False, collect=True)
    return best[1], bins


def _tabix_names(block: bytes) -> list[str]:
    """Reference names of a tabix header block (after the ``l_nm`` field)."""
    return [n.decode() for n in block.split(b"\x00") if n]


def _tabix_reference(buf: bytes) -> tuple[str, list[tuple[int, int]], int, int]:
    """(name, bins, min_shift, depth) of the first reference with data of a TBI / CSI."""
    if buf[:4] == b"TBI\x01":
        n_ref, _fmt, _cs, _cb, _ce, _meta, _skip, l_nm = struct.unpack_from("<8i", buf, 4)
        names = _tabix_names(buf[36 : 36 + l_nm])
        p = 36 + l_nm
        min_shift, depth, csi = 14, 5, False
    elif buf[:4] == b"CSI\x01":
        min_shift, depth, l_aux = struct.unpack_from("<3i", buf, 4)
        aux = buf[16 : 16 + l_aux]
        if len(aux) < 28:
            raise ProbeError("CSI without a tabix header")
        (l_nm,) = struct.unpack_from("<i", aux, 24)
        names = _tabix_names(aux[28 : 28 + l_nm])
        (n_ref,) = struct.unpack_from("<i", buf, 16 + l_aux)
        p = 20 + l_aux
        csi = True
    else:
        raise ProbeError("not a TBI or CSI")
    for ref in range(n_ref):
        bins, _, p = _ref_bins(buf, p, csi=csi, collect=True)
        if not csi:
            (n_intv,) = struct.unpack_from("<i", buf, p)
            p += 4 + 8 * n_intv
        if bins and ref < len(names):
            return names[ref], bins, min_shift, depth
    raise ProbeError("no reference holds data")


def _bam_reference_names(head: bytes) -> list[str]:
    data = _inflate_bgzf(head)
    if data[:4] != b"BAM\x01":
        raise ProbeError("not a BAM")
    (l_text,) = struct.unpack_from("<i", data, 4)
    p = 8 + l_text
    (n_ref,) = struct.unpack_from("<i", data, p)
    p += 4
    names: list[str] = []
    for _ in range(n_ref):
        (l_name,) = struct.unpack_from("<i", data, p)
        names.append(data[p + 4 : p + 4 + l_name].rstrip(b"\x00").decode())
        p += 4 + l_name + 4
    return names


def probe_bam(data: remote_read.ByteSource, index: remote_read.ByteSource) -> str:
    """Locus of the reference with the most reads (BAM + BAI)."""
    bai = remote_read.read_all(index, _MAX_INDEX_BYTES)
    ref, bins = _bai_reference(bai)
    names = _bam_reference_names(_read(data, 0, _MAX_HEADER_BYTES))
    if ref >= len(names):
        raise ProbeError("reference outside the BAM header")
    found = _densest_bin(bins, 14, 5)
    if found is None:
        return names[ref]
    return _window(names[ref], *found)


def probe_tabix(index: remote_read.ByteSource) -> str:
    """Locus of the first reference with data (TBI or CSI)."""
    raw = remote_read.read_all(index, _MAX_INDEX_BYTES)
    name, bins, min_shift, depth = _tabix_reference(_inflate_bgzf(raw))
    found = _densest_bin(bins, min_shift, depth)
    if found is None:
        return name
    return _window(name, *found)


# --------------------------------------------------------------------------
# bigWig / bigBed
# --------------------------------------------------------------------------

_BIGWIG_MAGIC = 0x888FFC26
_BIGBED_MAGIC = 0x8789F2EB


def _chrom_names(tree: bytes, ctoff: int, p: int, key_size: int, out: dict[int, str]) -> None:
    leaf, _, count = struct.unpack_from("<BBH", tree, p)
    p += 4
    for _ in range(count):
        key = tree[p : p + key_size].rstrip(b"\x00").decode()
        p += key_size
        if leaf:
            chrom_id, _size = struct.unpack_from("<II", tree, p)
            p += 8
            out[chrom_id] = key
        else:
            (child,) = struct.unpack_from("<Q", tree, p)
            p += 8
            _chrom_names(tree, ctoff, child - ctoff, key_size, out)


def probe_bigwig(data: remote_read.ByteSource) -> str:
    """Locus of the first data block of a bigWig / bigBed."""
    head = _read(data, 0, 64)
    if len(head) < 56:
        raise ProbeError("short bigWig header")
    magic, _ver, _zooms, ctoff, dataoff = struct.unpack_from("<IHHQQ", head, 0)
    if magic not in (_BIGWIG_MAGIC, _BIGBED_MAGIC):
        raise ProbeError("not a little-endian bigWig / bigBed")
    (uncompress_size,) = struct.unpack_from("<I", head, 52)
    tree = _read(data, ctoff, _MAX_HEADER_BYTES)
    key_size = struct.unpack_from("<I", tree, 8)[0]
    names: dict[int, str] = {}
    _chrom_names(tree, ctoff, 32, key_size, names)
    raw = _read(data, dataoff, 65_536 + 8)[8:]
    block = zlib.decompressobj().decompress(raw) if uncompress_size else raw
    chrom_id, start, end = struct.unpack_from("<III", block, 0)
    if chrom_id not in names:
        raise ProbeError("data block names an unknown chromosome")
    return _window(names[chrom_id], start, min(max(end - start, 1000), _MAX_BLOCK_WINDOW))


# --------------------------------------------------------------------------
# Tracks
# --------------------------------------------------------------------------


def probe_source(
    fmt: str, data: remote_read.ByteSource, index: remote_read.ByteSource | None
) -> str | None:
    """Locus holding data for one file, or None (unsupported format, unreadable file)."""
    try:
        if fmt in ("bigwig", "bigbed"):
            return probe_bigwig(data)
        if index is None:
            return None
        if fmt == "bam":
            return probe_bam(data, index)
        if fmt in ("vcf", "bed", "narrowpeak", "broadpeak", "gff3", "bedgraph"):
            return probe_tabix(index)
    except (ProbeError, remote_read.RemoteReadError, struct.error, zlib.error, ValueError) as exc:
        logger.info(f"jbrowse probe: {fmt} not readable: {exc}")
    except Exception as exc:  # noqa: BLE001 - a probe must never fail the view
        logger.warning(f"jbrowse probe: {fmt} failed: {exc}")
    return None


def _cached(key: tuple[str, int | None, str]) -> tuple[bool, str | None]:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL_S:
        return True, hit[1]
    return False, None


def _remember(key: tuple[str, int | None, str], locus: str | None) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[key] = (time.monotonic(), locus)


def probe_track(tdc: TracksDC, track: TrackRow, delta_version: int | None = None) -> str | None:
    """Locus holding data in ``track``, cached per (collection, data version, file)."""
    key = (tdc.dc_id, delta_version, track.uri)
    known, locus = _cached(key)
    if known:
        return locus
    try:
        base = s3_base_folder(tdc.dc_id, tdc.props)
        data = remote_read.resolve_location(track.uri, base)
        index = remote_read.resolve_location(track.index_uri, base) if track.index_uri else None
        locus = probe_source(track.fmt, data, index)
    except remote_read.RemoteReadError as exc:
        logger.info(f"jbrowse probe: {track.track_id} not resolvable: {exc.detail}")
        locus = None
    except Exception as exc:  # noqa: BLE001 - a probe must never fail the view
        logger.warning(f"jbrowse probe: {track.track_id} failed: {exc}")
        locus = None
    _remember(key, locus)
    return locus


def first_region(
    tdc: TracksDC, tracks: list[TrackRow], delta_version: int | None = None
) -> str | None:
    """The first region holding data among the first few ``tracks``, else None."""
    for track in tracks[:_MAX_TRACKS_PROBED]:
        locus = probe_track(tdc, track, delta_version)
        if locus:
            return locus
    return None


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
