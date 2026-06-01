"""CLI subcommand for the bioinformatics tool→viz catalog.

Discovery + validation of the declarative catalog (``depictio/catalog/*.yaml``)
and an offline scaffolder that turns an nf-core module ``meta.yml`` into a draft
catalog entry the contributor then completes (fingerprint columns + viz roles).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml

app = typer.Typer()


@app.command("list")
def catalog_list() -> None:
    """List every tool + output (mode) in the bundled catalog."""
    from depictio.models.components.advanced_viz.catalog import load_catalog_entries

    entries = load_catalog_entries()
    if not entries:
        typer.echo("No catalog entries found.")
        return
    typer.echo(f"Catalog tools ({len(entries)}):")
    for entry in entries:
        ident = entry.tool.biotools_id or "-"
        typer.echo(f"\n  {entry.tool.id}  ({entry.tool.name})  biotools:{ident}")
        for out in entry.outputs:
            mode = f" [{out.mode}]" if out.mode else ""
            viz = ", ".join(out.feeds_viz) if out.feeds_viz else "—"
            fp = (
                ",".join(out.fingerprint.required_columns)
                if out.fingerprint and out.fingerprint.required_columns
                else "(no fingerprint)"
            )
            typer.echo(f"      - {out.id}{mode}")
            typer.echo(f"          reshape={out.reshape.kind}  feeds: {viz}")
            typer.echo(f"          fingerprint: {fp}")


@app.command("validate")
def catalog_validate(
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Validate a single YAML file instead of the bundle"),
    ] = None,
) -> None:
    """Validate catalog YAML against the schema (CI-friendly: non-zero on error)."""
    from depictio.models.components.advanced_viz.catalog import (
        CATALOG_DIR,
        CatalogEntry,
        load_entries_from_dir,
    )

    try:
        if path:
            raw = yaml.safe_load(Path(path).read_text())
            CatalogEntry.model_validate(raw)
            typer.echo(f"  OK: {path}")
        else:
            entries = load_entries_from_dir(CATALOG_DIR)
            typer.echo(f"  OK: {len(entries)} catalog entries valid in {CATALOG_DIR}")
    except Exception as exc:
        typer.echo(f"  INVALID: {exc}")
        raise typer.Exit(code=1)


@app.command("import-meta")
def catalog_import_meta(
    meta_path: Annotated[
        str, typer.Argument(help="Path to an nf-core module meta.yml to scaffold from")
    ],
    output: Annotated[
        str | None, typer.Option("--output", "-o", help="Write the scaffold YAML here")
    ] = None,
) -> None:
    """Scaffold a draft catalog entry from an nf-core module ``meta.yml``.

    Infers tool identity, bio.tools id, EDAM formats and file patterns. Leaves
    ``fingerprint`` and ``feeds_viz`` for you to complete — those can't be
    derived from module metadata alone.
    """
    from depictio.models.components.advanced_viz.catalog import meta_yml_to_entry

    meta = yaml.safe_load(Path(meta_path).read_text())
    entry = meta_yml_to_entry(meta)
    text = yaml.safe_dump(
        entry.model_dump(exclude_none=True, exclude_defaults=True),
        sort_keys=False,
    )
    if output:
        Path(output).write_text(text)
        typer.echo(f"  Wrote scaffold to {output}")
        typer.echo("  TODO: fill in each output's fingerprint.required_columns + feeds_viz.")
    else:
        typer.echo(text)
