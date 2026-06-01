"""CLI subcommand for the bioinformatics tool→viz catalog.

Discovery + validation of the declarative catalog (``depictio/catalog/``),
recognition of files in a run directory (``match``), and an offline scaffolder
that turns an nf-core module ``meta.yml`` into a draft entry (``import-meta``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml

app = typer.Typer()


@app.command("list")
def catalog_list() -> None:
    """List every module + output (one file per output / running mode)."""
    from depictio.models.components.advanced_viz.catalog import load_catalog_entries

    entries = load_catalog_entries()
    if not entries:
        typer.echo("No catalog entries found.")
        return
    typer.echo(f"Catalog modules ({len(entries)}):")
    for entry in entries:
        m = entry.module
        typer.echo(f"\n  {m.id}  ({m.name})  [{len(entry.outputs)} output(s)]")
        for out in entry.outputs:
            mode = f"/{out.mode}" if out.mode else ""
            viz = ", ".join(out.feeds_viz) if out.feeds_viz else "—"
            find_bits = []
            if out.find.filename:
                find_bits.append(f"fn={out.find.filename}")
            if out.find.path_glob:
                find_bits.append(f"path={out.find.path_glob}")
            if out.find.required_columns:
                find_bits.append(f"cols={','.join(out.find.required_columns)}")
            recipe = out.recipe or "—"
            typer.echo(f"      - {out.id}{mode}")
            typer.echo(f"          find: {'  '.join(find_bits)}")
            typer.echo(f"          recipe={recipe}  feeds: {viz}")


@app.command("info")
def catalog_info(
    module_id: Annotated[str, typer.Argument(help="Module id, e.g. qiime2 or pangolin")],
) -> None:
    """Show one module's identity (clickable URLs) + every output in detail."""
    from depictio.models.components.advanced_viz.catalog import load_catalog_entries

    entry = next((e for e in load_catalog_entries() if e.module.id == module_id), None)
    if entry is None:
        typer.echo(f"No module '{module_id}'. Try `depictio catalog list`.")
        raise typer.Exit(code=1)
    m = entry.module
    typer.echo(f"{m.name}  ({m.id})")
    typer.echo(f"  {m.description}")
    if m.homepage:
        typer.echo(f"  homepage:  {m.homepage}")
    if m.biotools_url:
        typer.echo(f"  bio.tools: {m.biotools_url}")
    if m.nf_core_url:
        typer.echo(f"  nf-core:   {m.nf_core_url}")
    for t in m.edam_topics:
        typer.echo(f"  EDAM:      {t}")
    for out in entry.outputs:
        mode = f"  [{out.mode}]" if out.mode else ""
        typer.echo(f"\n  ── {out.id}{mode}")
        typer.echo(f"     {out.description}")
        if out.multiqc_module:
            typer.echo(f"     via MultiQC module: {out.multiqc_module}")
        if out.nf_core_url:
            typer.echo(f"     nf-core:  {out.nf_core_url}")
        typer.echo(
            f"     find:     {out.find.model_dump(exclude_none=True, exclude_defaults=True)}"
        )
        if out.file_schema:
            cols = ", ".join(f"{c}:{t}" for c, t in out.file_schema.items())
            typer.echo(f"     file_schema: {cols}")
        typer.echo(f"     recipe:   {out.recipe or '— (none, raw file is bindable)'}")
        typer.echo(f"     feeds:    {', '.join(out.feeds_viz) or '—'}")


@app.command("validate")
def catalog_validate(
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Validate a single module folder/file instead"),
    ] = None,
) -> None:
    """Validate catalog YAML against the schema (CI-friendly: non-zero on error).

    `--path` accepts the whole catalog dir, a single module folder (with a
    module.yaml), or a single flat-file module.
    """
    import yaml

    from depictio.models.components.advanced_viz.catalog import (
        CATALOG_DIR,
        CatalogEntry,
        load_entries_from_dir,
    )
    from depictio.models.components.advanced_viz.catalog import (
        _load_module_dir as load_module_dir,
    )

    target = Path(path) if path else CATALOG_DIR
    try:
        if target.is_dir() and (target / "module.yaml").exists():
            # a single multi-output module folder
            entries = [load_module_dir(target)]
        elif target.is_dir():
            # the catalog root (or a dir of flat-file modules + module folders)
            entries = load_entries_from_dir(target)
        else:
            # a single flat-file module
            entries = [CatalogEntry.model_validate(yaml.safe_load(target.read_text()))]
    except Exception as exc:
        typer.echo(f"  INVALID ({target}): {exc}")
        raise typer.Exit(code=1)

    # every referenced recipe must resolve to a real file
    from depictio.recipes import resolve_recipe_path

    dangling = []
    for entry in entries:
        for out in entry.outputs:
            if out.recipe:
                try:
                    resolve_recipe_path(out.recipe)
                except Exception:
                    dangling.append(f"{out.id} → {out.recipe}")
    if dangling:
        typer.echo(f"  INVALID ({target}): unresolved recipe reference(s): {dangling}")
        raise typer.Exit(code=1)

    typer.echo(f"  OK: {len(entries)} catalog module(s) valid in {target}")


@app.command("match")
def catalog_match(
    run_dir: Annotated[str, typer.Argument(help="A pipeline run directory to scan")],
) -> None:
    """Recognise which catalog outputs are present in a run directory.

    The catalog analogue of MultiQC's file search: walks the directory and
    reports every file matched by a module output's `find` rules.
    """
    from depictio.models.components.advanced_viz.catalog import match_run_dir

    matches = match_run_dir(run_dir)
    if not matches:
        typer.echo(f"No catalogued tool outputs found under {run_dir}")
        return
    typer.echo(f"Recognised {len(matches)} file(s) in {run_dir}:")
    for hit in matches:
        viz = ", ".join(hit.feeds_viz) if hit.feeds_viz else "—"
        typer.echo(f"  {hit.path}")
        typer.echo(f"      → {hit.module_id} / {hit.output_id}  feeds: {viz}")


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

    Infers module identity (URLs), EDAM formats and a `find` pattern.
    Leaves `file_schema`, `recipe` and `feeds_viz` for you to complete.
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
        typer.echo("  TODO: fill in each output's file_schema + recipe + feeds_viz.")
    else:
        typer.echo(text)


@app.command("schema")
def catalog_schema(
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Write the JSON Schema here (default: stdout)"),
    ] = None,
) -> None:
    """Emit the JSON Schema for a catalog YAML file (the authoritative contract).

    Regenerate the committed ``depictio/catalog/catalog.schema.json`` with::

        depictio catalog schema -o depictio/catalog/catalog.schema.json
    """
    import json

    from depictio.models.components.advanced_viz.catalog import CatalogEntry

    schema = CatalogEntry.model_json_schema()
    text = json.dumps(schema, indent=2) + "\n"
    if output:
        Path(output).write_text(text)
        typer.echo(f"  Wrote JSON Schema to {output}")
    else:
        typer.echo(text)
