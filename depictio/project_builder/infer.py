"""What a picked file probably is, and the scan rule that would pick it and its kin.

The builder's first guess, which the user then edits: a tag, a data collection
type, single vs recursive, a glob and the scan regex it stands for, the table
format, and any catalog tool that already knows the file.

The glob → regex translation is the composer's (``compose.glob_regex``): a
pattern without ``/`` becomes a basename regex, and ``**/x`` matches ``x`` at
any depth, which is exactly how the recursive scan reads a regex (basename
first, then the run-relative path when the regex spells one).
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from depictio.cli.cli.utils.compose import TABULAR, glob_regex, match_files, slug
from depictio.cli.cli.utils.data_root import DataRoot
from depictio.models.local_access import is_multiqc_output
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.roots import confine_rel
from depictio.project_builder.stores import describe_store, is_ome_tiff, is_store_name

# Data collection types the builder authors (the last two when this Depictio has them).
DC_TYPES = (
    "table",
    "multiqc",
    "image",
    "indexed_file",
    "geojson",
    "phylogeny",
    "genomic_tracks",
    "bioimage",
)
# Stands where the varying segment of a generalised glob was, until it is the wildcard.
_WILDCARD_MARK = "DEPICTIOWILDCARDMARK"

PHYLOGENY_SUFFIXES = {
    ".nwk": "newick",
    ".newick": "newick",
    ".tree": "newick",
    ".nex": "nexus",
    ".nexus": "nexus",
}
GEOJSON_SUFFIXES = frozenset({".geojson"})
# Longest suffix first: ".vcf.gz" before ".gz".
INDEXED_SUFFIXES: dict[str, str] = {
    ".vcf.gz": "vcf",
    ".bam": "bam",
    ".bw": "bigwig",
    ".bigwig": "bigwig",
    ".bb": "bigbed",
    ".bigbed": "bigbed",
    ".gff3.gz": "gff3",
    ".gff.gz": "gff3",
    ".fa": "fasta",
    ".fasta": "fasta",
    ".fna": "fasta",
    ".bed.gz": "tabix",
    ".bedgraph.gz": "tabix",
}


def _suffixes(name: str) -> tuple[str, str]:
    """``(suffix, inner)``: the last suffix, and the one under a ``.gz``."""
    path = PurePosixPath(name.lower())
    suffix = path.suffix
    inner = PurePosixPath(path.stem).suffix if suffix == ".gz" else suffix
    return suffix, inner


def table_format(name: str) -> tuple[str | None, str | None]:
    """``(format, separator)`` of a tabular file by its name; ``(None, None)`` otherwise."""
    _suffix, inner = _suffixes(name)
    found = TABULAR.get(inner)
    return (found[0], found[1]) if found else (None, None)


def indexed_format(name: str) -> str | None:
    lowered = name.lower()
    for suffix in sorted(INDEXED_SUFFIXES, key=len, reverse=True):
        if lowered.endswith(suffix):
            return INDEXED_SUFFIXES[suffix]
    return None


def guess_type(name: str) -> str:
    """The data collection type a file named ``name`` most likely feeds."""
    if is_multiqc_output(name, is_dir=False) and name.endswith(".parquet"):
        return "multiqc"
    if is_ome_tiff(name) or is_store_name(name):
        return "bioimage"
    suffix, _inner = _suffixes(name)
    if suffix in PHYLOGENY_SUFFIXES:
        return "phylogeny"
    if suffix in GEOJSON_SUFFIXES:
        return "geojson"
    if indexed_format(name):
        return "indexed_file"
    return "table"


def _wildcard_token(names: list[str]) -> str:
    """Sibling path segments as one glob token: the literal name when they agree,
    else their common prefix, ``*`` and common suffix (``S1.tsv``/``S2.tsv`` → ``S*.tsv``)."""
    unique = list(dict.fromkeys(names))
    if len(unique) == 1:
        return unique[0]

    def common_prefix(items: list[str]) -> str:
        first = items[0]
        for index, char in enumerate(first):
            if any(len(item) <= index or item[index] != char for item in items):
                return first[:index]
        return first

    prefix = common_prefix(unique)
    suffix = common_prefix([item[::-1] for item in unique])[::-1]
    # Where the two overlap (S1.tsv, S11.tsv), the suffix keeps what the prefix
    # leaves of the shortest name, so the extension survives: S1*.tsv.
    room = min(len(item) for item in unique) - len(prefix)
    if len(suffix) > room:
        suffix = suffix[len(suffix) - room :] if room > 0 else ""
    return f"{prefix}*{suffix}"


def anti_unify(paths: list[str]) -> str:
    """The glob that generalises example paths (config by example).

    One example cannot say what varies, so it becomes ``**/<name>``. Examples
    at one depth are generalised segment by segment (``star/S1/quant.tsv`` and
    ``star/S2/quant.tsv`` → ``star/*/quant.tsv``); at mixed depths only the
    file name is kept, at any depth.
    """
    if not paths:
        raise ValueError("anti_unify needs at least one path")
    parts = [PurePosixPath(path).parts for path in paths]
    if len(paths) == 1:
        return f"**/{parts[0][-1]}"
    if len({len(p) for p in parts}) == 1:
        return "/".join(_wildcard_token(list(column)) for column in zip(*parts))
    return f"**/{_wildcard_token([p[-1] for p in parts])}"


def _tag_for(rel: str) -> str:
    """A tag from a path: the file stem, prefixed by its top folder when it has one."""
    path = PurePosixPath(rel)
    stem = path.name
    for suffix in sorted({".gz", *TABULAR, *PHYLOGENY_SUFFIXES, *GEOJSON_SUFFIXES}, key=len):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    stem = stem.split(".", 1)[0] if stem.count(".") else stem
    top = path.parts[0] if len(path.parts) > 1 else ""
    if top and top.lower() not in stem.lower():
        return slug(f"{top}_{stem}")
    return slug(stem)


def path_wildcard(glob: str) -> dict[str, Any] | None:
    """The one varying segment of a generalised glob as a ``{sample}`` wildcard.

    ``star/*/quant.tsv`` (examples differing in one folder) becomes the scan
    regex ``^star/{sample}/quant\\.tsv$`` with ``sample`` matching that folder,
    so each file's rows carry the folder they came from. The wildcard takes the
    whole varying part, shared start included (``S*.tsv`` gives ``S1``, not
    ``1``), and stops before the shared end. None when the glob varies in more
    than one place, or at mixed depths (``**``).
    """
    parts = glob.split("/")
    varying = [i for i, part in enumerate(parts) if "*" in part]
    if "**" in parts or len(varying) != 1 or parts[varying[0]].count("*") != 1:
        return None
    suffix = parts[varying[0]].split("*", 1)[1]
    parts[varying[0]] = _WILDCARD_MARK + suffix
    pattern = glob_regex("/".join(parts)).replace(_WILDCARD_MARK, "{sample}")
    regex = "[^/]+?" if suffix else "[^/]+"
    return {"pattern": pattern, "wildcards": [{"name": "sample", "regex": regex}]}


def _entry(root: DataRoot, rel: str):
    """The listing entry of ``rel`` in its folder, or None."""
    parent, _sep, name = rel.rpartition("/")
    return next((entry for entry in root.children(parent) if entry.name == name), None)


def _unavailable(dc_type: str) -> list[str]:
    from depictio.project_builder.capabilities import UNAVAILABLE, available_types

    return [] if dc_type in available_types() else [UNAVAILABLE[dc_type]]


def _suggested_format(name: str, dc_type: str, table: str | None) -> str | None:
    if dc_type in ("table", "image"):
        return table
    if dc_type == "phylogeny":
        return PHYLOGENY_SUFFIXES.get(_suffixes(name)[0])
    if dc_type == "indexed_file":
        return indexed_format(name)
    return None


def suggest(root: DataRoot, rel: str, examples: list[str] | None = None) -> dict[str, Any]:
    """The builder's first guess for a data collection reading ``rel``.

    ``examples``: other files the user says belong to the same collection;
    with them the guess is a recursive scan over the glob that generalises all
    of them. Without, a single-file scan, with a ``**/<name>`` glob ready for
    when the user switches to recursive. A ``*.zarr`` store is picked like a
    file and suggested as a bioimage, with what its top level shows.
    """
    from depictio.project_builder.capabilities import available_types
    from depictio.project_builder.tracks import infer_index_uri, infer_track_format

    rel = confine_rel(rel)
    others = [confine_rel(example) for example in examples or [] if example]
    entry = _entry(root, rel) if rel else None
    if entry is None or not root.exists(rel):
        raise BuilderRefused(404, f"'{rel}' is not a file of the data root.", "file_missing")
    name = PurePosixPath(rel).name
    if entry.is_dir and not is_store_name(name):
        raise BuilderRefused(
            400, f"'{rel}' is a folder: pick a file, or a .zarr store.", "folder_picked"
        )
    dc_type = guess_type(name)
    fmt, separator = table_format(name)
    warnings: list[str] = []
    store = None
    tracks = None
    if dc_type == "bioimage":
        if entry.is_dir:
            store = describe_store(root, rel)
            fmt = store["format"]
        else:
            fmt = "ome-tiff"
        warnings += _unavailable("bioimage")
    elif dc_type == "indexed_file" and "genomic_tracks" in available_types():
        track_format = infer_track_format(name)
        if track_format:
            dc_type = "genomic_tracks"
            index = infer_index_uri(rel, track_format)
            tracks = {
                "format": track_format,
                "index": index if index and root.exists(index) else None,
            }

    if dc_type in ("indexed_file", "genomic_tracks") and not others:
        # One file per sample is the norm: every file of that kind, anywhere.
        glob = "**/*" + name[len(name.split(".", 1)[0]) :]
    elif dc_type == "multiqc" and not others:
        glob = rel
    else:
        glob = anti_unify([rel, *others])
    recursive = bool(others) or dc_type in ("indexed_file", "multiqc")

    catalog = []
    seen: set[tuple[str, str]] = set()
    for match in match_files([] if entry.is_dir else [rel]):
        key = (match.tool_id, match.output_id)
        if key in seen:
            continue
        seen.add(key)
        catalog.append(
            {"tool_id": match.tool_id, "output_id": match.output_id, "renders": match.renders}
        )

    return {
        "path": rel,
        "tag": _tag_for(rel),
        "type": dc_type,
        "mode": "recursive" if recursive else "single",
        "glob": glob,
        "regex": glob_regex(glob),
        "format": fmt if dc_type == "bioimage" else _suggested_format(name, dc_type, fmt),
        "separator": separator if dc_type in ("table", "image") else None,
        "catalog": catalog,
        "multiqc": dc_type == "multiqc",
        "store": store,
        "tracks": tracks,
        "path_wildcard": path_wildcard(glob) if others else None,
        "warnings": warnings,
    }
