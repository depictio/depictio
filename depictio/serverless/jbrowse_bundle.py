"""Ship a genome browser session's files inside a static bundle.

Live, the embedded JBrowse reads its assembly, track and index files through
the API (``/jbrowse/tracks|assembly|preset|ucsc/...``), by byte range. A
bundle has no API, so producer A freezes the session ``render_jbrowse``
returns and hands it here with an :data:`Opener` that reads those same files
server-side. Each file the budget admits is shipped in ``inline_blobs`` and its
location in the session is rewritten to ``BUNDLE_ORIGIN + key``, a URL the
static runtime's fetch shim answers from memory (``static-runtime/jbrowse/
bundleFetch.ts``, ``depictio-static-core/src/bundledFiles.ts``): the browser
mounted offline is the real one, reading real files.

What is shipped, in this order, while the budget lasts:

1. The assembly. Its sequence whole when it fits (a viral or bacterial 2bit);
   otherwise only the chromosome lengths (the 2bit's ``chromSizesLocation``, a
   FASTA ``.fai`` or the 2bit's own index), behind a ``ChromSizesAdapter``: the
   tracks draw, the bases do not. Its refName aliases when they fit.
2. The tracks the session opens with, then the others (they stay in the track
   selector). A track's files are shipped whole when small; an indexed BAM or
   tabix file (VCF/BED/GFF/bedGraph) too big for that is sliced to the
   session's opening locus — the index whole, plus only the 256 KiB pages of
   the data file the index points to for the locus widened by its own width on
   each side (JBrowse's range cache reads whole pages, so whole pages are what
   it asks for). A read past the slice fails in the track with a message
   naming the region the bundle holds.
3. Anything else whole, if it fits (bigWig, bigBed, plain BED/GFF, CRAM).

A track that does not fit (or cannot be read) is dropped from the session and
listed in ``bundle.omitted`` with the reason, which the tier detail repeats. A
session whose assembly could not be shipped at all is not ``renderable``: the
runtime then shows the session table, as before, with that reason.

Producer-agnostic: the opener is the only part that knows where files live.
"""

from __future__ import annotations

import copy
import hashlib
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from depictio.serverless.genome_index import (
    BGZF_MAX_BLOCK,
    IndexFormatError,
    Locus,
    bam_ref_names,
    chrom_sizes_text,
    fai_sizes,
    find_ref,
    parse_aliases,
    parse_chrom_sizes,
    parse_index,
    parse_locus,
    twobit_count,
    twobit_index,
)
from depictio.serverless.objects import ObjectBudget

#: The host the runtime's fetch shim answers. ``.invalid`` never resolves
#: (RFC 2606), so a file the shim does not know cannot reach the network.
BUNDLE_ORIGIN = "https://bundle.depictio.invalid/jbrowse/"
#: JBrowse's RemoteFileWithRangeCache page (``@jbrowse/core`` util/io): every
#: ranged read is rounded out to whole pages of this size.
PAGE_SIZE = 256 * 1024
#: Files up to this size ship whole, never sliced.
SMALL_FILE_BYTES = 1024 * 1024

#: Per-component budget, raw bytes before base64, inside the bundle's object
#: budget (``DEPICTIO_STATIC_OBJECTS_MAX_MB``), which images and structures
#: share.
JBROWSE_MAX_MB_ENV = "DEPICTIO_STATIC_JBROWSE_MAX_MB"
JBROWSE_MAX_MB_DEFAULT = 16

#: Sequence counts past this are not read one record at a time for their sizes.
_TWOBIT_MAX_SEQS = 5000

BUNDLE_FORMAT_VERSION = 1


class FileSource(Protocol):
    """One file of a session, readable by byte range."""

    label: str

    def size(self) -> int: ...

    def read(self, start: int, end: int) -> bytes:
        """Bytes ``[start, end]``, inclusive."""
        ...


class SourceRefused(Exception):
    """A location the opener will not (or cannot) read; ``str()`` says why."""


#: ``uri -> FileSource``; raises :class:`SourceRefused`.
Opener = Callable[[str], FileSource]


def jbrowse_cap_bytes() -> int:
    try:
        mb = max(0, int(os.environ.get(JBROWSE_MAX_MB_ENV, JBROWSE_MAX_MB_DEFAULT)))
    except ValueError:
        mb = JBROWSE_MAX_MB_DEFAULT
    return mb * 1024 * 1024


def _mb(n: float) -> str:
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB" if n >= 1024 else f"{int(n)} B"
    return f"{n / 1024 / 1024:.1f} MB"


@dataclass
class Budget:
    """The component's share, inside the bundle's object budget."""

    objects: ObjectBudget
    cap: int = field(default_factory=jbrowse_cap_bytes)
    used: int = 0

    def admits(self, n: int) -> bool:
        return self.used + n <= self.cap and self.objects.admits(n)

    def left(self) -> int:
        return max(0, min(self.cap - self.used, self.objects.cap - self.objects.used))

    def take(self, n: int, key: str | None) -> bool:
        """Charge ``n`` bytes; True when the blob is new to the bundle (a blob
        another tile already shipped costs the bundle nothing more)."""
        self.used += n
        if key is not None and key in self.objects.seen:
            return False
        if key is not None:
            self.objects.seen.add(key)
        self.objects.used += n
        return True

    def give_back(self, n: int, key: str | None) -> None:
        self.used -= n
        self.objects.used -= n
        if key is not None:
            self.objects.seen.discard(key)

    def over(self, n: int) -> str:
        """Why ``n`` bytes do not fit (the caller states ``n``)."""
        if n > self.objects.per_object:
            return (
                f"over the {_mb(self.objects.per_object)} per-file cap "
                "(DEPICTIO_STATIC_OBJECT_MAX_MB)"
            )
        return (
            f"over the {_mb(self.left())} left of the budget "
            f"({_mb(self.cap)} per genome browser, {JBROWSE_MAX_MB_ENV}; "
            f"{_mb(self.objects.cap)} of files per bundle, DEPICTIO_STATIC_OBJECTS_MAX_MB)"
        )


# --- file plans ----------------------------------------------------------------


@dataclass
class FilePlan:
    """How one location is shipped: whole, or as page runs of the data file."""

    uri: str
    source: FileSource
    size: int
    #: None: whole. Else ``[(first_page, count)]``, ascending, disjoint.
    pages: list[tuple[int, int]] | None = None
    region: str | None = None
    #: Bytes already read while planning (index files, small files).
    data: bytes | None = None
    #: Replacement content (chrom sizes derived from a .fai or a 2bit).
    synthetic: bytes | None = None

    @property
    def shipped_bytes(self) -> int:
        if self.synthetic is not None:
            return len(self.synthetic)
        if self.pages is None:
            return self.size
        return sum(_run_bytes(first, count, self.size) for first, count in self.pages)

    def key(self) -> str:
        spec = f"{self.uri}|{self.pages}|{len(self.synthetic or b'')}"
        return "jbf_" + hashlib.sha256(spec.encode()).hexdigest()[:20]

    def load(self) -> bytes:
        if self.synthetic is not None:
            return self.synthetic
        if self.pages is None:
            if self.data is None:
                self.data = self.source.read(0, self.size - 1) if self.size else b""
            return self.data
        out = bytearray()
        for first, count in self.pages:
            start = first * PAGE_SIZE
            end = min((first + count) * PAGE_SIZE, self.size) - 1
            out += self.source.read(start, end)
        return bytes(out)


def _run_bytes(first: int, count: int, size: int) -> int:
    return max(0, min((first + count) * PAGE_SIZE, size) - first * PAGE_SIZE)


def pages_for(ranges: Iterable[tuple[int, int]], size: int) -> list[tuple[int, int]]:
    """The page runs covering byte ``ranges`` (inclusive ends) of a ``size``-byte file."""
    last_page = max((size - 1) // PAGE_SIZE, 0)
    pages: set[int] = set()
    for start, end in ranges:
        start = max(0, start)
        end = min(end, size - 1)
        if end < start:
            continue
        pages.update(range(start // PAGE_SIZE, min(end // PAGE_SIZE, last_page) + 1))
    runs: list[tuple[int, int]] = []
    for p in sorted(pages):
        if runs and runs[-1][0] + runs[-1][1] == p:
            runs[-1] = (runs[-1][0], runs[-1][1] + 1)
        else:
            runs.append((p, 1))
    return runs


# --- session walking -----------------------------------------------------------


def _is_location(node: Any) -> bool:
    return (
        isinstance(node, dict)
        and isinstance(node.get("uri"), str)
        and (node.get("locationType") in (None, "UriLocation"))
    )


def locations(node: Any, path: tuple[Any, ...] = ()) -> list[tuple[tuple[Any, ...], dict]]:
    """Every ``UriLocation`` under ``node``, with its path."""
    out: list[tuple[tuple[Any, ...], dict]] = []
    if _is_location(node):
        return [(path, node)]
    if isinstance(node, dict):
        for k, v in node.items():
            out.extend(locations(v, (*path, k)))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(locations(v, (*path, i)))
    return out


def _set_path(root: Any, path: tuple[Any, ...], value: Any) -> None:
    node = root
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value


def _bundled_location(key: str) -> dict[str, str]:
    return {"uri": BUNDLE_ORIGIN + key, "locationType": "UriLocation"}


#: Adapters a slice can serve: (data location key, index kind) — the index
#: is ``adapter.index.location`` (BAM's ``index`` too).
_SLICEABLE: dict[str, str] = {
    "BamAdapter": "bamLocation",
    "VcfTabixAdapter": "vcfGzLocation",
    "BedTabixAdapter": "bedGzLocation",
    "Gff3TabixAdapter": "gffGzLocation",
    "GtfTabixAdapter": "gtfGzLocation",
    "BedGraphTabixAdapter": "bedGraphGzLocation",
}

_FORMAT_NAMES = {
    "BamAdapter": "BAM",
    "CramAdapter": "CRAM",
    "VcfTabixAdapter": "VCF",
    "VcfAdapter": "VCF",
    "BedTabixAdapter": "BED",
    "BedAdapter": "BED",
    "BigBedAdapter": "bigBed",
    "BigWigAdapter": "bigWig",
    "Gff3TabixAdapter": "GFF3",
    "Gff3Adapter": "GFF3",
    "GtfAdapter": "GTF",
    "GtfTabixAdapter": "GTF",
    "BedGraphTabixAdapter": "bedGraph",
    "BedGraphAdapter": "bedGraph",
    "TwoBitAdapter": "2bit",
    "IndexedFastaAdapter": "FASTA",
    "BgzipFastaAdapter": "FASTA",
}


@dataclass
class Omitted:
    track_id: str
    name: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"track_id": self.track_id, "name": self.name, "reason": self.reason}


@dataclass
class BundleResult:
    payload: dict[str, Any]
    renderable: bool
    reason: str | None
    shipped_tracks: int
    total_tracks: int
    sliced: int
    shipped_bytes: int
    sequence: str
    region: str | None
    omitted: list[Omitted]

    def detail(self) -> str:
        """The tier-detail sentence."""
        if not self.renderable:
            return f"export-time session only (assembly, locus, track table): {self.reason}"
        parts = [
            f"the genome browser renders offline from {self.shipped_tracks} of "
            f"{self.total_tracks} track(s) shipped in the bundle ({_mb(self.shipped_bytes)}"
            + (f", {self.sliced} sliced to {self.region}" if self.sliced else "")
            + "), frozen at the default filter state",
            self.sequence,
        ]
        if self.omitted:
            shown = "; ".join(f"{o.name}: {o.reason}" for o in self.omitted[:3])
            more = f" (and {len(self.omitted) - 3} more)" if len(self.omitted) > 3 else ""
            parts.append(f"left out: {shown}{more}")
        return "; ".join(parts)


class _Shipper:
    def __init__(
        self,
        opener: Opener,
        budget: Budget,
        inline_blobs: dict[str, str] | None,
        dry_run: bool,
    ):
        self.opener = opener
        self.budget = budget
        self.inline_blobs = inline_blobs
        self.dry_run = dry_run
        self.files: dict[str, dict[str, Any]] = {}
        self.by_uri: dict[str, str] = {}
        self.sources: dict[str, FileSource] = {}
        self.shipped_bytes = 0
        #: Blobs this session added to the bundle (``(key, bytes)``), to undo.
        self.added: list[tuple[str | None, int]] = []

    def rollback(self) -> None:
        """Take back every blob this session added: the session will not use them."""
        for key, n in self.added:
            self.budget.give_back(n, key)
            if key is not None and self.inline_blobs is not None:
                self.inline_blobs.pop(key, None)
        self.added = []

    def source(self, uri: str) -> FileSource:
        src = self.sources.get(uri)
        if src is None:
            src = self.opener(uri)
            self.sources[uri] = src
        return src

    def whole(self, uri: str) -> FilePlan:
        src = self.source(uri)
        return FilePlan(uri=uri, source=src, size=src.size())

    def ship(self, plans: list[FilePlan]) -> list[str]:
        """Pack ``plans`` (already admitted) into blobs; returns their keys."""
        from depictio.serverless.objects import pack_object

        keys = []
        for plan in plans:
            key = plan.key()
            if plan.pages is None and plan.synthetic is None and plan.uri in self.by_uri:
                keys.append(self.by_uri[plan.uri])
                continue
            if key in self.files:
                keys.append(key)
                continue
            n = plan.shipped_bytes
            blob_key = None
            if not self.dry_run:
                data = plan.load()
                n = len(data)
                blob_key, b64, _ = pack_object(data, compress=False)
                blob_key = "jb_" + blob_key.removeprefix("obj_")
                if self.inline_blobs is not None:
                    self.inline_blobs[blob_key] = b64
            if self.budget.take(n, blob_key):
                self.added.append((blob_key, n))
            self.shipped_bytes += n
            entry: dict[str, Any] = {
                "blob": blob_key or "",
                "size": len(plan.synthetic) if plan.synthetic is not None else plan.size,
                "pages": [list(r) for r in plan.pages] if plan.pages is not None else None,
                "page_size": PAGE_SIZE,
                "label": plan.source.label,
            }
            if plan.region:
                entry["region"] = plan.region
            self.files[key] = entry
            if plan.pages is None and plan.synthetic is None:
                self.by_uri[plan.uri] = key
            keys.append(key)
        return keys

    def cost(self, plans: list[FilePlan]) -> int:
        return sum(
            0
            if (p.pages is None and p.synthetic is None and p.uri in self.by_uri)
            else p.shipped_bytes
            for p in plans
        )


# --- the assembly --------------------------------------------------------------


@dataclass
class AssemblyOutcome:
    renderable: bool
    sequence_shipped: bool
    sentence: str
    ref_names: list[str]
    ref_lengths: dict[str, int]
    aliases: list[set[str]]
    reason: str | None = None


def _sizes_from_twobit(src: FileSource) -> list[tuple[str, int]]:
    head = src.read(0, 15)
    count = twobit_count(head)
    if count > _TWOBIT_MAX_SEQS:
        raise IndexFormatError(f"2bit holds {count} sequences")
    span = 16 + count * (1 + 255 + 8)
    head = src.read(0, min(span, src.size()) - 1)
    order, entries = twobit_index(head)
    sizes = []
    for name, offset in entries:
        raw = src.read(offset, offset + 3)
        sizes.append((name, int.from_bytes(raw, "little" if order == "<" else "big")))
    return sizes


def _bundle_assembly(
    assembly: dict[str, Any], shipper: _Shipper, budget: Budget
) -> AssemblyOutcome:
    seq = assembly.get("sequence") if isinstance(assembly.get("sequence"), dict) else None
    adapter = (seq or {}).get("adapter") if seq else None
    name = str(assembly.get("name") or "")
    aliases: list[set[str]] = []
    if not isinstance(adapter, dict):
        return AssemblyOutcome(False, False, "", [], {}, [], f"assembly {name!r} has no sequence")
    atype = str(adapter.get("type") or "")
    sizes: list[tuple[str, int]] | None = None
    sequence_shipped = False
    sentence = ""
    reason: str | None = None

    # 1. The sequence whole, when it fits.
    locs = locations(adapter)
    if atype == "FromConfigSequenceAdapter" or not locs:
        sequence_shipped = True
        sentence = "reference sequence inline in the session"
    else:
        try:
            plans = [shipper.whole(loc["uri"]) for _, loc in locs]
            cost = shipper.cost(plans)
            if all(budget.objects.per_object >= p.size for p in plans) and budget.admits(cost):
                keys = shipper.ship(plans)
                for (path, _), key in zip(locs, keys, strict=True):
                    _set_path(adapter, path, _bundled_location(key))
                sequence_shipped = True
                sentence = f"reference sequence shipped ({_mb(cost)})"
            else:
                fmt = _FORMAT_NAMES.get(atype, atype)
                reason = f"reference sequence ({fmt}, {_mb(cost)}) not shipped: {budget.over(cost)}"
        except (SourceRefused, IndexFormatError, OSError) as exc:
            reason = f"reference sequence not shipped: unreadable ({exc})"

    # 2. Otherwise the chromosome lengths alone.
    if not sequence_shipped:
        try:
            sizes = _assembly_sizes(adapter, atype, shipper)
        except (SourceRefused, IndexFormatError, OSError, UnicodeDecodeError) as exc:
            return AssemblyOutcome(
                False,
                False,
                "",
                [],
                {},
                [],
                f"{reason}, and its chromosome lengths could not be read ({exc})",
            )
        if not sizes:
            return AssemblyOutcome(False, False, "", [], {}, [], f"{reason}; no chromosome lengths")
        text = chrom_sizes_text(sizes).encode()
        plan = FilePlan(
            uri=f"chrom-sizes:{name}",
            source=_Named(f"{name} chromosome lengths"),
            size=len(text),
            synthetic=text,
        )
        if not budget.admits(len(text)):
            return AssemblyOutcome(
                False,
                False,
                "",
                [],
                {},
                [],
                f"{reason}; the chromosome lengths ({_mb(len(text))}) are {budget.over(len(text))}",
            )
        (key,) = shipper.ship([plan])
        seq["adapter"] = {  # type: ignore[index]
            "type": "ChromSizesAdapter",
            "chromSizesLocation": _bundled_location(key),
        }
        sentence = f"{reason}; the tracks are drawn over the chromosome lengths, without bases"

    # 3. refName aliases, when they fit (the tracks may name chromosomes otherwise).
    alias_conf = assembly.get("refNameAliases")
    alias_locs = locations(alias_conf) if isinstance(alias_conf, dict) else []
    if alias_locs:
        try:
            plans = [shipper.whole(loc["uri"]) for _, loc in alias_locs]
            cost = shipper.cost(plans)
            if budget.admits(cost):
                for p in plans:
                    p.data = p.source.read(0, p.size - 1) if p.size else b""
                    aliases.extend(parse_aliases(p.data.decode("utf-8", "replace")))
                keys = shipper.ship(plans)
                for (path, _), key in zip(alias_locs, keys, strict=True):
                    _set_path(alias_conf, path, _bundled_location(key))
            else:
                assembly.pop("refNameAliases", None)
                sentence += f"; refName aliases left out ({_mb(cost)}, {budget.over(cost)})"
        except (SourceRefused, OSError) as exc:
            assembly.pop("refNameAliases", None)
            sentence += f"; refName aliases left out (unreadable: {exc})"
    # Cytobands and other assembly extras are decoration: dropped when not shipped.
    for extra in ("cytobands",):
        conf = assembly.get(extra)
        extra_locs = locations(conf) if isinstance(conf, dict) else []
        if not extra_locs:
            continue
        try:
            plans = [shipper.whole(loc["uri"]) for _, loc in extra_locs]
            if budget.admits(shipper.cost(plans)):
                keys = shipper.ship(plans)
                for (path, _), key in zip(extra_locs, keys, strict=True):
                    _set_path(conf, path, _bundled_location(key))
                continue
        except (SourceRefused, OSError):
            pass
        assembly.pop(extra, None)

    lengths = dict(sizes or [])
    return AssemblyOutcome(True, sequence_shipped, sentence, list(lengths), lengths, aliases)


class _Named:
    """A synthetic file's label holder (it is never read)."""

    def __init__(self, label: str):
        self.label = label

    def size(self) -> int:  # pragma: no cover - synthetic plans carry their bytes
        return 0

    def read(self, start: int, end: int) -> bytes:  # pragma: no cover
        raise OSError("synthetic file")


def _assembly_sizes(
    adapter: dict[str, Any], atype: str, shipper: _Shipper
) -> list[tuple[str, int]]:
    """Chromosome lengths from the smallest file that has them."""
    small = 8 * 1024 * 1024
    for key in ("chromSizesLocation",):
        loc = adapter.get(key)
        if _is_location(loc):
            src = shipper.source(loc["uri"])
            n = src.size()
            if n > small:
                raise IndexFormatError(f"chrom sizes file is {_mb(n)}")
            return parse_chrom_sizes(src.read(0, n - 1).decode("utf-8"))
    if atype in ("IndexedFastaAdapter", "BgzipFastaAdapter"):
        loc = adapter.get("faiLocation")
        if not _is_location(loc):
            fasta = adapter.get("fastaLocation")
            if _is_location(fasta):
                loc = {"uri": f"{fasta['uri']}.fai", "locationType": "UriLocation"}
        if _is_location(loc):
            src = shipper.source(loc["uri"])
            n = src.size()
            if n > small:
                raise IndexFormatError(f".fai is {_mb(n)}")
            return fai_sizes(src.read(0, n - 1).decode("utf-8"))
    if atype == "TwoBitAdapter":
        loc = adapter.get("twoBitLocation")
        if _is_location(loc):
            return _sizes_from_twobit(shipper.source(loc["uri"]))
    if atype == "ChromSizesAdapter":
        raise IndexFormatError("chrom sizes file not readable")
    raise IndexFormatError(f"no chromosome lengths in a {atype}")


# --- tracks --------------------------------------------------------------------


def _track_format(adapter: dict[str, Any]) -> str:
    atype = str(adapter.get("type") or "")
    return _FORMAT_NAMES.get(atype, atype or "track")


def _slice_plans(
    adapter: dict[str, Any],
    shipper: _Shipper,
    locus: Locus,
    asm: AssemblyOutcome,
) -> tuple[list[tuple[tuple[Any, ...], FilePlan]], str] | None:
    """The plans for an index-sliced track, or None when the adapter cannot be sliced."""
    atype = str(adapter.get("type") or "")
    data_key = _SLICEABLE.get(atype)
    if not data_key or not _is_location(adapter.get(data_key)):
        return None
    index_conf = adapter.get("index")
    index_loc = index_conf.get("location") if isinstance(index_conf, dict) else None
    if not _is_location(index_loc):
        return None
    data_uri = adapter[data_key]["uri"]
    index_plan = shipper.whole(index_loc["uri"])
    if index_plan.size > 64 * 1024 * 1024:
        raise IndexFormatError(f"index is {_mb(index_plan.size)}")
    index_plan.data = index_plan.source.read(0, index_plan.size - 1)
    idx = parse_index(index_plan.data)
    data_src = shipper.source(data_uri)
    size = data_src.size()
    first = idx.first_data_block()
    head_end = (first if first is not None else 0) + 2 * BGZF_MAX_BLOCK - 1
    names = idx.names
    if not names:
        if atype != "BamAdapter":
            raise IndexFormatError("the index names no references")
        names = bam_ref_names(data_src.read(0, min(head_end, size - 1)))
    ref_id = find_ref(names, locus.ref, asm.aliases)
    if ref_id < 0:
        raise IndexFormatError(f"{locus.ref} is not a reference of this file")
    length = asm.ref_lengths.get(locus.ref)
    region = locus.widened(length)
    end = region.end if region.end is not None else 1 << 29
    ranges = [(0, head_end), *idx.block_ranges_for(ref_id, region.start, end)]
    data_plan = FilePlan(
        uri=data_uri,
        source=data_src,
        size=size,
        pages=pages_for(ranges, size),
        region=region.label(),
    )
    return [((data_key,), data_plan), (("index", "location"), index_plan)], region.label()


def _bundle_track(
    conf: dict[str, Any],
    shipper: _Shipper,
    budget: Budget,
    locus: Locus | None,
    asm: AssemblyOutcome,
    small_file_bytes: int = SMALL_FILE_BYTES,
) -> tuple[bool, str | None, bool]:
    """Ship one track's files; ``(kept, reason, sliced)``."""
    adapter = conf.get("adapter")
    if not isinstance(adapter, dict):
        return True, None, False
    locs = locations(adapter)
    if not locs:
        return True, None, False  # inline features (the rank track): nothing to ship
    atype = str(adapter.get("type") or "")
    fmt = _track_format(adapter)
    if atype == "CramAdapter" and not asm.sequence_shipped:
        return (
            False,
            "CRAM decodes its reads against the reference sequence, which is not in the bundle",
            False,
        )
    try:
        whole = [shipper.whole(loc["uri"]) for _, loc in locs]
    except (SourceRefused, OSError) as exc:
        return False, f"{fmt} unreadable ({exc})", False
    whole_cost = shipper.cost(whole)
    per_file_ok = all(p.size <= budget.objects.per_object for p in whole)

    def ship_whole() -> tuple[bool, str | None, bool]:
        keys = shipper.ship(whole)
        for (path, _), key in zip(locs, keys, strict=True):
            _set_path(adapter, path, _bundled_location(key))
        return True, None, False

    if whole_cost <= small_file_bytes and per_file_ok and budget.admits(whole_cost):
        return ship_whole()
    sliced_reason: str | None = None
    if locus is not None and atype in _SLICEABLE:
        try:
            planned = _slice_plans(adapter, shipper, locus, asm)
        except (SourceRefused, IndexFormatError, OSError) as exc:
            planned = None
            sliced_reason = f"cannot be sliced ({exc})"
        if planned is not None:
            plans, _label = planned
            cost = shipper.cost([p for _, p in plans])
            if all(
                p.shipped_bytes <= budget.objects.per_object for _, p in plans
            ) and budget.admits(cost):
                keys = shipper.ship([p for _, p in plans])
                for (path, _), key in zip(plans, keys, strict=True):
                    _set_path(adapter, path, _bundled_location(key))
                return True, None, True
            sliced_reason = (
                f"sliced to {plans[0][1].region}, {_mb(cost)}: still {budget.over(cost)}"
            )
    if per_file_ok and budget.admits(whole_cost):
        return ship_whole()
    why = f"{fmt}, {_mb(whole_cost)}: {budget.over(whole_cost)}"
    if sliced_reason:
        why += f"; {sliced_reason}"
    elif atype not in _SLICEABLE:
        why += f" ({fmt} is shipped whole or not at all: only BAM and tabix files are sliced)"
    elif locus is None:
        why += " (no opening locus to slice it to)"
    return False, why, False


def bundle_session(
    payload: dict[str, Any],
    opener: Opener,
    objects: ObjectBudget,
    inline_blobs: dict[str, str] | None,
    *,
    dry_run: bool = False,
    cap: int | None = None,
    small_file_bytes: int = SMALL_FILE_BYTES,
) -> BundleResult:
    """Ship ``payload``'s files (``render_jbrowse``'s answer) and rewrite it.

    ``dry_run`` plans without reading any data page or writing a blob (index
    files are read: the plan needs them), for the preflight.
    """
    out = copy.deepcopy(payload)
    budget = Budget(objects=objects) if cap is None else Budget(objects=objects, cap=cap)
    shipper = _Shipper(opener, budget, inline_blobs, dry_run)
    tracks = [t for t in out.get("tracks") or [] if isinstance(t, dict)]
    total = len(tracks)
    locus = parse_locus(out.get("location"))

    assembly = out.get("assembly") if isinstance(out.get("assembly"), dict) else {}
    asm = _bundle_assembly(assembly, shipper, budget)

    def finish(
        renderable: bool, reason: str | None, kept: list[dict], omitted: list[Omitted], sliced: int
    ) -> BundleResult:
        kept_ids = {str(t.get("trackId")) for t in kept}
        if renderable:
            out["tracks"] = kept
            out["shown_track_ids"] = [i for i in out.get("shown_track_ids") or [] if i in kept_ids]
            out["track_rows"] = [
                r for r in out.get("track_rows") or [] if str(r.get("track_id")) in kept_ids
            ]
            out["sv_track_ids"] = [i for i in out.get("sv_track_ids") or [] if i in kept_ids]
        out["bundle"] = {
            "version": BUNDLE_FORMAT_VERSION,
            "renderable": renderable,
            "reason": reason,
            "files": shipper.files if renderable else {},
            "omitted": [o.as_dict() for o in omitted],
            "region": locus.label() if locus else None,
            "sequence": asm.sentence or None,
        }
        if not renderable:
            shipper.rollback()
        return BundleResult(
            payload=out,
            renderable=renderable,
            reason=reason,
            shipped_tracks=len(kept),
            total_tracks=total,
            sliced=sliced,
            shipped_bytes=shipper.shipped_bytes if renderable else 0,
            sequence=asm.sentence,
            region=(locus.widened(asm.ref_lengths.get(locus.ref)).label() if locus else None),
            omitted=omitted,
        )

    if not asm.renderable:
        return finish(False, asm.reason, [], [], 0)

    shown = [str(i) for i in out.get("shown_track_ids") or []]
    order = {tid: i for i, tid in enumerate(shown)}
    ranked = sorted(
        enumerate(tracks),
        key=lambda it: (order.get(str(it[1].get("trackId")), len(order)), it[0]),
    )
    kept_at: list[tuple[int, dict]] = []
    omitted: list[Omitted] = []
    sliced = 0
    for at, conf in ranked:
        ok, why, was_sliced = _bundle_track(conf, shipper, budget, locus, asm, small_file_bytes)
        if ok:
            kept_at.append((at, conf))
            sliced += int(was_sliced)
        else:
            omitted.append(
                Omitted(
                    str(conf.get("trackId") or ""),
                    str(conf.get("name") or conf.get("trackId") or ""),
                    why or "not shipped",
                )
            )
    kept = [conf for _, conf in sorted(kept_at, key=lambda it: it[0])]
    if total and not kept:
        return finish(
            False,
            "no track fits the bundle (" + "; ".join(o.reason for o in omitted[:2]) + ")",
            [],
            omitted,
            0,
        )
    return finish(True, None, kept, omitted, sliced)
