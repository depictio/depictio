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

# Data collection types the builder authors.
DC_TYPES = ("table", "multiqc", "image", "indexed_file", "geojson", "phylogeny")

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
    ".bcf": "vcf",
    ".bam": "bam",
    ".bw": "bigwig",
    ".bigwig": "bigwig",
    ".bb": "bigbed",
    ".bigbed": "bigbed",
    ".gff3.gz": "gff3",
    ".gff.gz": "gff3",
    ".fa": "fasta",
    ".fasta": "fasta",
    ".bed.gz": "tabix",
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
    if len(prefix) + len(suffix) > min(len(item) for item in unique):
        suffix = ""
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


def suggest(root: DataRoot, rel: str, examples: list[str] | None = None) -> dict[str, Any]:
    """The builder's first guess for a data collection reading ``rel``.

    ``examples``: other files the user says belong to the same collection;
    with them the guess is a recursive scan over the glob that generalises all
    of them. Without, a single-file scan, with a ``**/<name>`` glob ready for
    when the user switches to recursive.
    """
    rel = confine_rel(rel)
    others = [confine_rel(example) for example in examples or [] if example]
    if not rel or not root.exists(rel):
        raise BuilderRefused(404, f"'{rel}' is not a file of the data root.", "file_missing")
    name = PurePosixPath(rel).name
    dc_type = guess_type(name)
    fmt, separator = table_format(name)

    if dc_type == "indexed_file" and not others:
        # One file per sample is the norm: every file of that kind, anywhere.
        glob = "**/*" + name[len(name.split(".", 1)[0]) :]
    elif dc_type == "multiqc" and not others:
        glob = rel
    else:
        glob = anti_unify([rel, *others])
    recursive = bool(others) or dc_type in ("indexed_file", "multiqc")

    catalog = []
    seen: set[tuple[str, str]] = set()
    for match in match_files([rel]):
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
        "format": fmt if dc_type in ("table", "image") else indexed_format(name),
        "separator": separator if dc_type in ("table", "image") else None,
        "catalog": catalog,
        "multiqc": dc_type == "multiqc",
    }
