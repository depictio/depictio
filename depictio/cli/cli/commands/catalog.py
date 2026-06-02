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


@app.command("preview")
def catalog_preview(
    output_id: Annotated[str, typer.Argument(help="Output id, e.g. qiime2_alpha_diversity")],
    render: Annotated[
        int | None,
        typer.Option("--render", "-r", help="Preview only this render index (default: all)"),
    ] = None,
    out: Annotated[
        str | None,
        typer.Option("--out", "-o", help="Write the HTML here (default: a temp file)"),
    ] = None,
    no_open: Annotated[
        bool,
        typer.Option("--no-open", help="Do not open the HTML in a browser"),
    ] = False,
) -> None:
    """Render an output's components on its fixture → self-contained HTML.

    Builds every ``renders_as`` target (figure/card/table) on the output's
    bundled ``fixture`` and opens an interactive page in the browser — the
    contributor's loop for previewing a viz before opening a PR. No running
    depictio stack required.
    """
    import tempfile
    import webbrowser

    from depictio.catalog.render import render_output_to_html
    from depictio.models.components.advanced_viz.catalog import load_catalog_entries

    output = next(
        (o for e in load_catalog_entries() for o in e.outputs if o.id == output_id),
        None,
    )
    if output is None:
        typer.echo(f"No output '{output_id}'. Try `depictio catalog list`.")
        raise typer.Exit(code=1)

    try:
        page = render_output_to_html(output, render_index=render)
    except Exception as exc:
        typer.echo(f"  could not preview {output_id!r}: {exc}")
        raise typer.Exit(code=1)

    out_path = (
        Path(out) if out else Path(tempfile.gettempdir()) / f"catalog_preview_{output_id}.html"
    )
    out_path.write_text(page)
    typer.echo(f"  Wrote preview to {out_path}")
    if not no_open:
        webbrowser.open(out_path.resolve().as_uri())


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
        check_existence,
        fixture_columns,
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

    # nf-core module + EDAM term existence (against the vendored indices).
    problems: list[str] = check_existence(entries)
    # Ground each render's bound columns against the real data shape:
    # the fixture (most complete) > the recipe's EXPECTED_SCHEMA > declared columns.
    for entry in entries:
        for out in entry.outputs:
            source = ""
            if out.fixture:
                try:
                    available = set(fixture_columns(out.fixture))
                    source = f"fixture {out.fixture}"
                except Exception as exc:
                    problems.append(f"{out.id}: fixture {out.fixture} → {exc}")
                    continue
            elif out.recipe:
                try:
                    available = set(recipe_output_columns(out.recipe))
                    source = f"recipe {out.recipe}"
                except Exception as exc:
                    problems.append(f"{out.id}: recipe {out.recipe} → {exc}")
                    continue
            elif out.columns:
                available = set(out.columns)
                source = "declared columns"
            else:
                continue  # nothing to ground against (non-tabular / binding-less)
            for r in out.renders_as:
                missing = r.bound_columns() - available
                if missing:
                    problems.append(
                        f"{out.id} render {r.kind or r.component}: binds "
                        f"{sorted(missing)} absent from {source} {sorted(available)}"
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


@app.command("compose")
def catalog_compose(
    run_dir: Annotated[str, typer.Argument(help="A run directory to compose a dashboard from")],
    confirm_versions: Annotated[
        bool,
        typer.Option(
            "--confirm-versions",
            help="Restrict to tools listed in the run's software_versions.yml",
        ),
    ] = False,
) -> None:
    """Preview the guided dashboard a run would compose (module → viz).

    Pipeline-agnostic: works for an nf-core pipeline run or a custom workflow
    that reuses nf-core modules. Groups recognised module outputs by tool and
    shows the viz building blocks — a proposal, not a built dashboard.
    """
    from depictio.models.components.advanced_viz.catalog import compose_run_dir

    by_tool = compose_run_dir(run_dir, confirm_with_versions=confirm_versions)
    if not by_tool:
        typer.echo(f"No catalogued module outputs found under {run_dir}")
        return
    n_viz = sum(len(m.renders) for ms in by_tool.values() for m in ms)
    typer.echo(f"Proposed dashboard from {run_dir}: {len(by_tool)} module(s), {n_viz} viz block(s)")
    for tool_id, matches in sorted(by_tool.items()):
        typer.echo(f"\n  {tool_id}")
        for m in matches:
            renders = ", ".join(m.renders) if m.renders else "—"
            typer.echo(f"      {m.output_id}  ({m.path})  → {renders}")


@app.command("refresh-index")
def catalog_refresh_index() -> None:
    """Regenerate the vendored existence indices from authoritative sources.

    Needs network (run by a maintainer, not in offline CI): fetches the
    nf-core/modules list and the EDAM term list, and rewrites
    `depictio/catalog/_index/{nf_core_modules,edam_terms}.txt`.
    """
    import csv
    import io
    import json
    import urllib.request

    from depictio.models.components.advanced_viz.catalog import INDEX_DIR

    def _get(url: str) -> bytes:
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
            return resp.read()

    # nf-core modules: paths like modules/nf-core/<module>/main.nf
    try:
        tree = json.loads(
            _get("https://api.github.com/repos/nf-core/modules/git/trees/master?recursive=1")
        )
        modules = sorted(
            {
                e["path"][len("modules/nf-core/") : -len("/main.nf")]
                for e in tree.get("tree", [])
                if e["path"].startswith("modules/nf-core/") and e["path"].endswith("/main.nf")
            }
        )
        (INDEX_DIR / "nf_core_modules.txt").write_text(
            "# Authoritative nf-core module paths (generated by `catalog refresh-index`).\n"
            + "\n".join(modules)
            + "\n"
        )
        typer.echo(f"  nf_core_modules.txt: {len(modules)} modules")
    except Exception as exc:
        typer.echo(f"  FAILED nf-core: {exc}")
        raise typer.Exit(code=1)

    # EDAM terms: Class ID column of EDAM.csv (operation_/format_/topic_)
    try:
        reader = csv.DictReader(io.StringIO(_get("https://edamontology.org/EDAM.csv").decode()))
        terms = sorted(
            {
                tid
                for row in reader
                if (tid := str(row.get("Class ID", "")).rstrip("/").rsplit("/", 1)[-1]).split("_")[
                    0
                ]
                in {"topic", "operation", "format"}
            }
        )
        (INDEX_DIR / "edam_terms.txt").write_text(
            "# Authoritative EDAM term ids (generated by `catalog refresh-index`).\n"
            + "\n".join(terms)
            + "\n"
        )
        typer.echo(f"  edam_terms.txt: {len(terms)} terms")
    except Exception as exc:
        typer.echo(f"  FAILED EDAM: {exc}")
        raise typer.Exit(code=1)


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
