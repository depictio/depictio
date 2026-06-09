"""CLI subcommand for standalone recipe execution and discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

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
    pipeline_version: Annotated[
        str | None,
        typer.Option(
            "--version",
            "-v",
            help="Pipeline version for version-specific recipe (e.g. 2.14.0). "
            "Uses shared recipe when omitted.",
        ),
    ] = None,
    output: Annotated[
        str | None, typer.Option("--output", "-o", help="Save result to parquet file")
    ] = None,
    head: Annotated[int, typer.Option("--head", "-n", help="Number of rows to display")] = 20,
) -> None:
    """Run a recipe against local data with all 4 validation checkpoints."""
    from depictio.cli.cli.utils.rich_utils import console
    from depictio.recipes import (
        RecipeError,
        load_recipe,
        resolve_sources,
        validate_schema,
    )

    try:
        # Checkpoint 1: load
        module = load_recipe(recipe_name, pipeline_version)
        source_count = len(module.SOURCES)
        console.print(
            f"  [green]:white_check_mark:[/green] Loaded recipe: {recipe_name} ({source_count} source(s))"
        )

        # Checkpoint 2: resolve
        sources = resolve_sources(module, data_dir)
        for ref, df in sources.items():
            console.print(
                f"  [green]:white_check_mark:[/green] Resolved source '{ref}': {df.height} rows x {df.width} columns"
            )

        # Check for unresolved dc_ref sources
        dc_ref_sources = [s for s in module.SOURCES if s.dc_ref is not None]
        if dc_ref_sources:
            refs = ", ".join(s.ref for s in dc_ref_sources)
            console.print(
                f"  [yellow]Skipped dc_ref sources (not available standalone): {refs}[/yellow]"
            )
            console.print(
                "  [dim]Note: dc_ref sources are resolved during 'depictio data process'[/dim]"
            )
            raise typer.Exit(code=0)

        # Checkpoint 3: transform
        result = module.transform(sources)
        if not isinstance(result, pl.DataFrame):
            console.print(
                f"  [red]:x: transform() returned {type(result).__name__}, expected DataFrame[/red]"
            )
            raise typer.Exit(code=1)
        if result.is_empty():
            console.print("  [red]:x: transform() produced empty DataFrame[/red]")
            raise typer.Exit(code=1)
        console.print(
            f"  [green]:white_check_mark:[/green] Transform produced {result.height} rows x {result.width} columns"
        )

        # Checkpoint 4: schema
        validate_schema(result, module.EXPECTED_SCHEMA, recipe_name)
        schema_str = ", ".join(f"{c}({t})" for c, t in module.EXPECTED_SCHEMA.items())
        console.print(f"  [green]:white_check_mark:[/green] Schema valid: {schema_str}")

        # Display result (raw repr so it stays copy/paste-friendly)
        console.print("")
        console.print(str(result.head(head)))

        # Optionally save
        if output:
            out_path = Path(output)
            if out_path.suffix == ".parquet":
                result.write_parquet(out_path)
            elif out_path.suffix == ".csv":
                result.write_csv(out_path)
            else:
                result.write_parquet(out_path)
            console.print(f"\n  [green]Saved to {out_path}[/green]")

    except RecipeError as e:
        console.print(f"  [red]:x: FAILED: {e}[/red]")
        raise typer.Exit(code=1)
    except typer.Exit:
        # Re-raise control-flow exits (e.g. dc_ref skip with code=0) so they
        # aren't swallowed by the broad handler below. typer 0.26 vendors its
        # own click, so typer.Exit is no longer a click.exceptions.Exit.
        raise
    except Exception as e:
        logger.exception("Recipe execution failed")
        console.print(f"  [red]:x: ERROR: {e}[/red]")
        raise typer.Exit(code=1)


@app.command("list")
def recipe_list() -> None:
    """List all available shared recipes."""
    from depictio.cli.cli.utils.rich_utils import render_records_table
    from depictio.recipes import list_recipes

    recipes = list_recipes()
    if not recipes:
        render_records_table([])
        return

    render_records_table(
        [{"Recipe": name} for name in recipes], title=f"Available recipes ({len(recipes)})"
    )


@app.command("info")
def recipe_info(
    recipe_name: Annotated[
        str, typer.Argument(help="Recipe name (e.g. nf-core/ampliseq/alpha_diversity.py)")
    ],
    pipeline_version: Annotated[
        str | None,
        typer.Option(
            "--version",
            "-v",
            help="Pipeline version for version-specific recipe (e.g. 2.14.0). "
            "Uses shared recipe when omitted.",
        ),
    ] = None,
) -> None:
    """Show recipe details: docstring, sources, and expected schema."""
    from depictio.cli.cli.utils.rich_utils import console, render_records_table
    from depictio.recipes import RecipeError, load_recipe

    try:
        module = load_recipe(recipe_name, pipeline_version)
    except RecipeError as e:
        console.print(f"[red]:x: Error: {e}[/red]")
        raise typer.Exit(code=1)

    # Docstring
    doc = module.__doc__ or "(no description)"
    console.print(f"[bold]Recipe:[/bold] {recipe_name}")
    if pipeline_version:
        console.print(f"[bold]Version:[/bold] {pipeline_version}")
    console.print(f"[bold]Description:[/bold] {doc.strip()}")

    # Sources
    render_records_table(
        [
            {
                "Source": s.ref,
                "Location": f"dc_ref={s.dc_ref}" if s.dc_ref else s.path,
                "Format": "—" if s.dc_ref else s.format,
            }
            for s in module.SOURCES
        ],
        title=f"Sources ({len(module.SOURCES)})",
    )

    # Schema
    render_records_table(
        [{"Column": col, "Type": str(dtype)} for col, dtype in module.EXPECTED_SCHEMA.items()],
        title=f"Expected output schema ({len(module.EXPECTED_SCHEMA)} columns)",
    )
