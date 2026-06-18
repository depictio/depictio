#!/usr/bin/env python
"""Recursive file inventory for a divergent nf-core route directory.

Walks a pipeline output dir and, for every file, records: relative path, a glob
that generalises per-sample names, the detected format (sniffed, not assumed),
and — for tabular files (csv/tsv/parquet) — header columns, row count, and a few
sample rows. Output is JSON (or a compact markdown table) for curating a
ROUTE_INVENTORY doc.

This is a read-only inventory aid for the route-modelling scoping work; it does
NOT ingest anything or touch depictio.

Usage:
    depictio/cli/.venv/bin/python dev/nf-core-validation/inventory_route.py \
        ~/Data/viralrecon/validation-runs-3.0.0/run_nanopore --json out.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import polars as pl

# Directories that are provenance / scratch, not dashboard data sources.
EXCLUDE_DIRS = {".nextflow", "work", "tmp"}
# pipeline_info is provenance but params*.json drives route detection — keep a note.
NOTE_DIRS = {"pipeline_info"}

SAMPLE_ID_RE = re.compile(r"SAMPLE[_-]?\d+|sample[_-]?\d+", re.IGNORECASE)


def detect_format(path: Path) -> str:
    """Sniff a coarse format from extension + (for ambiguous text) a byte peek."""
    ext = path.suffix.lower()
    mapping = {
        ".parquet": "parquet",
        ".csv": "csv",
        ".tsv": "tsv",
        ".json": "json",
        ".nwk": "newick",
        ".newick": "newick",
        ".html": "html",
        ".bam": "bam",
        ".bai": "bam-index",
        ".vcf": "vcf",
        ".gz": "gzip",
        ".bed": "bed",
        ".fa": "fasta",
        ".fasta": "fasta",
        ".fastq": "fastq",
        ".png": "png",
        ".pdf": "pdf",
        ".svg": "svg",
        ".log": "log",
        ".yml": "yaml",
        ".yaml": "yaml",
    }
    if ext in mapping:
        return mapping[ext]
    if ext in {".txt", ".tab"}:
        # Peek at the first line to decide tab vs comma vs other.
        try:
            first = path.open("r", errors="replace").readline()
            if "\t" in first:
                return "tsv"
            if "," in first:
                return "csv"
        except Exception:
            pass
        return "text"
    return ext.lstrip(".") or "other"


def globify(rel: str) -> str:
    """Replace per-sample tokens with * so the glob matches across samples."""
    return SAMPLE_ID_RE.sub("*", rel)


def read_tabular(path: Path, fmt: str) -> dict:
    """Return columns, row count, and up to 3 sample rows for a tabular file."""
    try:
        if fmt == "parquet":
            df = pl.read_parquet(path)
        else:
            sep = "\t" if fmt == "tsv" else ","
            df = pl.read_csv(
                path, separator=sep, infer_schema_length=200, truncate_ragged_lines=True
            )
    except Exception as e:  # noqa: BLE001 — best-effort inventory, report the error
        return {"error": f"{type(e).__name__}: {e}"}
    head = df.head(3)
    return {
        "columns": df.columns,
        "n_rows": df.height,
        "n_cols": df.width,
        "sample_rows": head.to_dicts(),
    }


def inventory(root: Path) -> dict:
    files: list[dict] = []
    excluded: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        top = rel.split("/", 1)[0]
        parts = set(rel.split("/"))
        if parts & EXCLUDE_DIRS or top in EXCLUDE_DIRS:
            excluded.append(rel)
            continue
        fmt = detect_format(p)
        entry: dict = {
            "path": rel,
            "glob": globify(rel),
            "format": fmt,
            "size_bytes": p.stat().st_size,
            "note_dir": top in NOTE_DIRS,
        }
        if fmt in {"csv", "tsv", "parquet"} and p.stat().st_size > 0:
            entry["tabular"] = read_tabular(p, fmt)
        files.append(entry)
    return {"root": str(root), "n_files": len(files), "files": files, "excluded": excluded}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", help="Route directory to inventory")
    ap.add_argument("--json", help="Write full JSON inventory to this path")
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 1

    result = inventory(root)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2, default=str))
        print(f"Wrote {result['n_files']} file entries to {args.json}")
    else:
        print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
