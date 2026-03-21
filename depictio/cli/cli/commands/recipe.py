"""CLI subcommand for standalone recipe execution and discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import click.exceptions
import polars as pl
import typer

from depictio.cli.cli_logging import logger

app = typer.Typer()


@app.command("run")
def recipe_run(
    recipe_name: Annotated[
        str, typer.Argument(help="Recipe name (e.g. nf-core/ampliseq/alpha_diversity.py)")
    ],
    data_dir: Annotated[
        str, typer.Option("--data-dir", "-d", help="Root directory with workflow output files")
    ],
    output: Annotated[
        str | None, typer.Option("--output", "-o", help="Save result to parquet file")
    ] = None,
    head: Annotated[int, typer.Option("--head", "-n", help="Number of rows to display")] = 20,
) -> None:
    """Run a recipe against local data with all 4 validation checkpoints."""
    from depictio.recipes import (
        RecipeError,
        load_recipe,
        resolve_sources,
        validate_schema,
    )

    try:
        # Checkpoint 1: load
        module = load_recipe(recipe_name)
        source_count = len(module.SOURCES)
        typer.echo(f"  Loaded recipe: {recipe_name} ({source_count} source(s))")

        # Checkpoint 2: resolve
        sources = resolve_sources(module, data_dir)
        for ref, df in sources.items():
            typer.echo(f"  Resolved source '{ref}': {df.height} rows x {df.width} columns")

        # Check for unresolved dc_ref sources
        dc_ref_sources = [s for s in module.SOURCES if s.dc_ref is not None]
        if dc_ref_sources:
            refs = ", ".join(s.ref for s in dc_ref_sources)
            typer.echo(f"  Skipped dc_ref sources (not available standalone): {refs}")
            typer.echo("  Note: dc_ref sources are resolved during 'depictio data process'")
            raise typer.Exit(code=0)

        # Checkpoint 3: transform
        result = module.transform(sources)
        if not isinstance(result, pl.DataFrame):
            typer.echo(f"  ERROR: transform() returned {type(result).__name__}, expected DataFrame")
            raise typer.Exit(code=1)
        if result.is_empty():
            typer.echo("  ERROR: transform() produced empty DataFrame")
            raise typer.Exit(code=1)
        typer.echo(f"  Transform produced {result.height} rows x {result.width} columns")

        # Checkpoint 4: schema
        validate_schema(result, module.EXPECTED_SCHEMA, recipe_name)
        schema_str = ", ".join(f"{c}({t})" for c, t in module.EXPECTED_SCHEMA.items())
        typer.echo(f"  Schema valid: {schema_str}")

        # Display result
        typer.echo("")
        typer.echo(str(result.head(head)))

        # Optionally save
        if output:
            out_path = Path(output)
            if out_path.suffix == ".parquet":
                result.write_parquet(out_path)
            elif out_path.suffix == ".csv":
                result.write_csv(out_path)
            else:
                result.write_parquet(out_path)
            typer.echo(f"\n  Saved to {out_path}")

    except RecipeError as e:
        typer.echo(f"  FAILED: {e}")
        raise typer.Exit(code=1)
    except click.exceptions.Exit:
        raise  # Re-raise typer.Exit / click.Exit (e.g. dc_ref skip with code=0)
    except Exception as e:
        logger.exception("Recipe execution failed")
        typer.echo(f"  ERROR: {e}")
        raise typer.Exit(code=1)


@app.command("list")
def recipe_list() -> None:
    """List all available bundled recipes."""
    from depictio.recipes import list_recipes

    recipes = list_recipes()
    if not recipes:
        typer.echo("No recipes found.")
        return

    typer.echo(f"Available recipes ({len(recipes)}):")
    for name in recipes:
        typer.echo(f"  {name}")


@app.command("info")
def recipe_info(
    recipe_name: Annotated[
        str, typer.Argument(help="Recipe name (e.g. nf-core/ampliseq/alpha_diversity.py)")
    ],
) -> None:
    """Show recipe details: docstring, sources, and expected schema."""
    from depictio.recipes import RecipeError, load_recipe

    try:
        module = load_recipe(recipe_name)
    except RecipeError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    # Docstring
    doc = module.__doc__ or "(no description)"
    typer.echo(f"Recipe: {recipe_name}")
    typer.echo(f"Description: {doc.strip()}")

    # Sources
    typer.echo(f"\nSources ({len(module.SOURCES)}):")
    for s in module.SOURCES:
        if s.dc_ref:
            typer.echo(f"  {s.ref}: dc_ref={s.dc_ref}")
        else:
            typer.echo(f"  {s.ref}: {s.path} ({s.format})")

    # Schema
    typer.echo(f"\nExpected output schema ({len(module.EXPECTED_SCHEMA)} columns):")
    for col, dtype in module.EXPECTED_SCHEMA.items():
        typer.echo(f"  {col}: {dtype}")
