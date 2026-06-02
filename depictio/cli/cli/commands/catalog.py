"""CLI for the bio-catalog: the tool→recipe→component linking table.

Discovery (`list`/`info`), recognition (`match`), recipe-output lookup
(`columns`), JSON-Schema export (`schema`), and a full CI-friendly `validate`
that grounds every `renders_as` role against the recipe's real output columns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer()


@app.command("list")
def catalog_list() -> None:
    """List every tool + output with its recipe and render targets."""
    from depictio.models.components.advanced_viz.catalog import load_catalog_entries

    entries = load_catalog_entries()
    if not entries:
        typer.echo("No catalog entries found.")
        return
    typer.echo(f"Catalog tools ({len(entries)}):")
    for entry in entries:
        typer.echo(f"\n  {entry.id}  ({entry.name})  [{len(entry.outputs)} output(s)]")
        for out in entry.outputs:
            mode = f"/{out.mode}" if out.mode else ""
            renders = ", ".join(r.kind or r.component for r in out.renders_as) or "—"
            src = out.recipe or ("columns" if out.columns else "—")
            typer.echo(f"      - {out.id}{mode}  [{src}]  → {renders}")


@app.command("info")
def catalog_info(
    tool_id: Annotated[str, typer.Argument(help="Tool id, e.g. qiime2 or pangolin")],
) -> None:
    """Show one tool's identity (clickable URLs) + every output in detail."""
    from depictio.models.components.advanced_viz.catalog import load_catalog_entries

    entry = next((e for e in load_catalog_entries() if e.id == tool_id), None)
    if entry is None:
        typer.echo(f"No tool '{tool_id}'. Try `depictio catalog list`.")
        raise typer.Exit(code=1)
    typer.echo(f"{entry.name}  ({entry.id})")
    typer.echo(f"  {entry.description}")
    if entry.homepage:
        typer.echo(f"  homepage:  {entry.homepage}")
    if entry.biotools_url:
        typer.echo(f"  bio.tools: {entry.biotools_url}")
    if entry.nf_core_url:
        typer.echo(f"  nf-core:   {entry.nf_core_url}")
    for t in entry.edam_topics:
        typer.echo(f"  EDAM:      {t}")
    for out in entry.outputs:
        mode = f"  [{out.mode}]" if out.mode else ""
        typer.echo(f"\n  ── {out.id}{mode}")
        typer.echo(f"     {out.description}")
        typer.echo(f"     find:    {out.find.model_dump(exclude_none=True)}")
        if out.recipe:
            typer.echo(f"     recipe:  {out.recipe}")
        if out.columns:
            typer.echo(f"     columns: {', '.join(f'{c}:{t}' for c, t in out.columns.items())}")
        for r in out.renders_as:
            tgt = f"{r.component}:{r.kind}" if r.kind else r.component
            roles = f"  roles={r.roles}" if r.roles else ""
            typer.echo(f"     render:  {tgt}{roles}")


@app.command("columns")
def catalog_columns(
    recipe: Annotated[str, typer.Argument(help="Recipe ref, e.g. nf-core/ampliseq/ancombc.py")],
) -> None:
    """Print the output columns a recipe produces (to help write `roles`)."""
    from depictio.models.components.advanced_viz.catalog import recipe_output_columns

    try:
        cols = recipe_output_columns(recipe)
    except Exception as exc:
        typer.echo(f"  could not read recipe {recipe!r}: {exc}")
        raise typer.Exit(code=1)
    typer.echo(f"Output columns of {recipe}:")
    for c in cols:
        typer.echo(f"  - {c}")


@app.command("validate")
def catalog_validate(
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Validate a single tool folder/file instead"),
    ] = None,
) -> None:
    """Validate the catalog (CI-friendly: non-zero on error).

    Beyond schema validation, grounds every recipe output's `renders_as` roles
    against the recipe's real output columns, and checks recipes resolve.
    """
    import yaml

    from depictio.models.components.advanced_viz.catalog import (
        CATALOG_DIR,
        CatalogEntry,
        load_entries_from_dir,
        recipe_output_columns,
    )
    from depictio.models.components.advanced_viz.catalog import (
        _load_tool_dir as load_tool_dir,
    )

    target = Path(path) if path else CATALOG_DIR
    try:
        if target.is_dir() and (target / "module.yaml").exists():
            entries = [load_tool_dir(target)]
        elif target.is_dir():
            entries = load_entries_from_dir(target)
        else:
            entries = [CatalogEntry.model_validate(yaml.safe_load(target.read_text()))]
    except Exception as exc:
        typer.echo(f"  INVALID ({target}): {exc}")
        raise typer.Exit(code=1)

    # Ground recipe-output roles against the recipe's real output columns.
    problems: list[str] = []
    for entry in entries:
        for out in entry.outputs:
            if not out.recipe:
                continue
            try:
                cols = set(recipe_output_columns(out.recipe))
            except Exception as exc:
                problems.append(f"{out.id}: recipe {out.recipe} → {exc}")
                continue
            for r in out.renders_as:
                missing = set(r.roles.values()) - cols
                if missing:
                    problems.append(
                        f"{out.id} render {r.kind or r.component}: role(s) bind to "
                        f"{sorted(missing)} absent from recipe output {sorted(cols)}"
                    )
    if problems:
        typer.echo(f"  INVALID ({target}):")
        for p in problems:
            typer.echo(f"    - {p}")
        raise typer.Exit(code=1)

    typer.echo(f"  OK: {len(entries)} catalog tool(s) valid in {target}")


@app.command("match")
def catalog_match(
    run_dir: Annotated[str, typer.Argument(help="A pipeline run directory to scan")],
) -> None:
    """Recognise which catalog outputs are present in a run directory."""
    from depictio.models.components.advanced_viz.catalog import match_run_dir

    matches = match_run_dir(run_dir)
    if not matches:
        typer.echo(f"No catalogued tool outputs found under {run_dir}")
        return
    typer.echo(f"Recognised {len(matches)} file(s) in {run_dir}:")
    for hit in matches:
        typer.echo(f"  {hit.path}  →  {hit.tool_id} / {hit.output_id}")


@app.command("schema")
def catalog_schema(
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Write the JSON Schema here (default: stdout)"),
    ] = None,
) -> None:
    """Emit the JSON Schema for a catalog file (regenerate the committed copy)."""
    import json

    from depictio.models.components.advanced_viz.catalog import CatalogEntry

    text = json.dumps(CatalogEntry.model_json_schema(), indent=2) + "\n"
    if output:
        Path(output).write_text(text)
        typer.echo(f"  Wrote JSON Schema to {output}")
    else:
        typer.echo(text)
