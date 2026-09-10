"""Data Manifest authoring commands.

``depictio manifest from-table`` pivots a wide sample table into the manifest's
long form. An nf-core samplesheet is one pivot away from a manifest: both map an
entity id to its files, but a samplesheet puts one *column* per file role
(``fastq_1``, ``fastq_2``) while a manifest puts one *row* per file with the
role in ``type``.

    sample,fastq_1,fastq_2          id,type,url,run
    s1,s1_R1.fq,s1_R2.fq     ->     s1,fastq_1,<base>/s1_R1.fq,
                                    s1,fastq_2,<base>/s1_R2.fq,

Users already write samplesheets, so starting from one beats inventing a format
for them to learn.
"""

import csv
import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from depictio.models.models.manifest import is_remote_url

app = typer.Typer()
console = Console()

# Columns that name the entity rather than one of its files.
_ID_HINTS = ("sample", "id", "sample_id", "sampleid", "name", "entity")
# Extensions that make a value obviously a file rather than a label.
_FILE_HINTS = (
    ".csv",
    ".tsv",
    ".txt",
    ".json",
    ".parquet",
    ".fq",
    ".fastq",
    ".gz",
    ".bam",
    ".cram",
    ".vcf",
    ".bed",
    ".bw",
    ".h5",
    ".h5ad",
    ".xlsx",
    ".nwk",
    ".zip",
)


def _read_table(path: Path) -> tuple[list[str], list[dict]]:
    """Read a CSV/TSV into (fieldnames, rows). Delimiter from extension, then sniffing."""
    text = path.read_text()
    if not text.strip():
        raise typer.BadParameter(f"{path} is empty")
    delimiter = "\t" if path.suffix.lower() in (".tsv", ".tab") else ","
    first_line = text.splitlines()[0]
    if delimiter not in first_line:
        # Extension lied (or there is none) — fall back to whichever separator
        # actually appears in the header.
        for candidate in ("\t", ",", ";"):
            if candidate in first_line:
                delimiter = candidate
                break
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    rows = [row for row in reader]
    if not reader.fieldnames:
        raise typer.BadParameter(f"Could not read a header row from {path}")
    return list(reader.fieldnames), rows


def _looks_like_file(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    if "://" in lowered or "/" in lowered:
        return True
    return any(lowered.endswith(ext) for ext in _FILE_HINTS)


def _detect_id_column(fieldnames: list[str]) -> str:
    for name in fieldnames:
        if name.strip().lower() in _ID_HINTS:
            return name
    # No conventional name: the first column is the samplesheet convention.
    return fieldnames[0]


def _detect_file_columns(fieldnames: list[str], rows: list[dict], id_col: str) -> list[str]:
    detected = []
    for name in fieldnames:
        if name == id_col:
            continue
        values = [(row.get(name) or "").strip() for row in rows]
        populated = [v for v in values if v]
        if populated and all(_looks_like_file(v) for v in populated):
            detected.append(name)
    return detected


@app.command("from-table")
def from_table(
    table: Annotated[
        Path, typer.Argument(help="Wide table to pivot (nf-core samplesheet, CSV/TSV)")
    ],
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Output manifest (.json or .csv)")
    ] = Path("manifest.json"),
    id_col: Annotated[
        Optional[str],
        typer.Option(
            "--id-col", help="Entity id column. Auto-detected (sample/id/name) if omitted."
        ),
    ] = None,
    file_cols: Annotated[
        Optional[list[str]],
        typer.Option(
            "--file-cols",
            help="Columns holding file locations, repeatable. Auto-detected if omitted.",
        ),
    ] = None,
    run_col: Annotated[
        Optional[str],
        typer.Option("--run-col", help="Column to use as the manifest 'run' grouping"),
    ] = None,
    base_url: Annotated[
        Optional[str],
        typer.Option(
            "--base-url",
            help=(
                "Prefix joined to relative paths, e.g. s3://my-bucket/run42. "
                "Required when the table holds local paths: a manifest entry must "
                "be a remote URL."
            ),
        ),
    ] = None,
) -> None:
    """Pivot a wide sample table into a Data Manifest.

    Example:
        depictio manifest from-table samplesheet.csv --id-col sample \\
          --base-url s3://my-bucket/run42 -o manifest.json
    """
    if not table.is_file():
        raise typer.BadParameter(f"Table not found: {table}")

    fieldnames, rows = _read_table(table)
    if not rows:
        raise typer.BadParameter(f"{table} has a header but no data rows")

    resolved_id_col = id_col or _detect_id_column(fieldnames)
    if resolved_id_col not in fieldnames:
        raise typer.BadParameter(
            f"--id-col '{resolved_id_col}' is not a column of {table}. Available: {', '.join(fieldnames)}"
        )

    resolved_file_cols = (
        list(file_cols) if file_cols else _detect_file_columns(fieldnames, rows, resolved_id_col)
    )
    unknown = [c for c in resolved_file_cols if c not in fieldnames]
    if unknown:
        raise typer.BadParameter(
            f"--file-cols not present in {table}: {', '.join(unknown)}. "
            f"Available: {', '.join(fieldnames)}"
        )
    if not resolved_file_cols:
        raise typer.BadParameter(
            f"No file columns detected in {table}. Name them explicitly with --file-cols."
        )
    if run_col and run_col not in fieldnames:
        raise typer.BadParameter(f"--run-col '{run_col}' is not a column of {table}")

    console.print(f"[cyan]id column:[/cyan] {resolved_id_col}")
    console.print(f"[cyan]file columns:[/cyan] {', '.join(resolved_file_cols)}")

    prefix = base_url.rstrip("/") if base_url else None
    entries: list[dict] = []
    local_examples: list[str] = []
    for line_no, row in enumerate(rows, start=2):
        entity = (row.get(resolved_id_col) or "").strip()
        if not entity:
            raise typer.BadParameter(f"{table}:{line_no} has an empty '{resolved_id_col}'")
        for column in resolved_file_cols:
            value = (row.get(column) or "").strip()
            if not value:
                # A blank cell is a legitimately absent file (single-end reads),
                # not an error — just no entry for that role.
                continue
            url = value if is_remote_url(value) or "://" in value else None
            if url is None:
                url = f"{prefix}/{value.lstrip('./')}" if prefix else value
                if not is_remote_url(url) and "://" not in url:
                    local_examples.append(value)
            entry = {"id": entity, "type": column, "url": url}
            if run_col:
                entry["run"] = (row.get(run_col) or "").strip() or None
            entries.append(entry)

    if local_examples:
        console.print(
            f"[red]{len(local_examples)} path(s) are local, e.g. {local_examples[0]!r}.[/red]"
        )
        console.print(
            "[yellow]A manifest entry must be an s3:// or https:// URL. Pass --base-url "
            "to prefix these paths, or upload the files first.[/yellow]"
        )
        console.print(
            "[yellow]If the data is already on S3 under a common prefix, you may not need a "
            "manifest at all: point the DC straight at it with "
            "`depictio run --bind TAG=s3://bucket/prefix/*.csv`.[/yellow]"
        )
        raise typer.Exit(1)

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".json":
        out.write_text(json.dumps(entries, indent=2) + "\n")
    else:
        with out.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["id", "type", "url", "run"])
            writer.writeheader()
            for entry in entries:
                writer.writerow({**{"run": None}, **entry})

    types = sorted({e["type"] for e in entries})
    console.print(f"[green]✓ {len(entries)} entries from {len(rows)} rows -> {out}[/green]")
    console.print(f"[cyan]types (one data collection each):[/cyan] {', '.join(types)}")
