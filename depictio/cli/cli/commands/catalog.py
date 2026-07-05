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

# Maintainer / CI commands (catalog authoring, index maintenance, schema export).
# Mounted under the hidden top-level `dev` group — kept out of the user-facing
# `catalog` help, but still callable as `depictio dev catalog <cmd>`.
dev_app = typer.Typer()


@app.command("list")
def catalog_list() -> None:
    """List every tool + output with its recipe and render targets."""
    from depictio.cli.cli.utils.rich_utils import console, render_records_table
    from depictio.models.components.advanced_viz.catalog import load_catalog_entries

    entries = load_catalog_entries()
    if not entries:
        console.print("[yellow]No catalog entries found.[/yellow]")
        return
    # "Tool" is the id you pass to `catalog info <Tool>` (the display name adds
    # nothing — id and name are near-identical — so it's dropped).
    records = [
        {
            "Tool": entry.id,
            "Output": out.id,
            "Keyword": out.mode or "—",
            "Source": out.recipe or ("columns" if out.columns else "—"),
            "Renders as": ", ".join(r.kind or r.component for r in out.renders_as) or "—",
        }
        for entry in entries
        for out in entry.outputs
    ]
    render_records_table(records, title=f"Catalog tools ({len(entries)})")
    example = entries[0].id
    console.print(
        f"\n[dim]Details for one tool:[/dim] [cyan]depictio catalog info <Tool>[/cyan]"
        f"  [dim](e.g. depictio catalog info {example})[/dim]"
    )


@app.command("info")
def catalog_info(
    tool_id: Annotated[str, typer.Argument(help="Tool id, e.g. qiime2 or pangolin")],
) -> None:
    """Show one tool's identity (clickable URLs) + every output in detail."""
    from depictio.cli.cli.utils.rich_utils import console
    from depictio.models.components.advanced_viz.catalog import load_catalog_entries

    entry = next((e for e in load_catalog_entries() if e.id == tool_id), None)
    if entry is None:
        console.print(f"[red]No tool '{tool_id}'.[/red] Try [bold]depictio catalog list[/bold].")
        raise typer.Exit(code=1)
    console.print(f"[bold magenta]{entry.name}[/bold magenta]  ([cyan]{entry.id}[/cyan])")
    console.print(f"  {entry.description}")
    if entry.homepage:
        console.print(f"  [dim]homepage:[/dim]  {entry.homepage}")
    if entry.biotools_url:
        console.print(f"  [dim]bio.tools:[/dim] {entry.biotools_url}")
    if entry.nf_core_url:
        console.print(f"  [dim]nf-core:[/dim]   {entry.nf_core_url}")
    for t in entry.edam_topics:
        console.print(f"  [dim]EDAM:[/dim]      {t}")
    for out in entry.outputs:
        mode = f"  [{out.mode}]" if out.mode else ""
        console.print(f"\n  [bold]── {out.id}{mode}[/bold]")
        console.print(f"     {out.description}")
        if out.mode:
            console.print(f"     [dim]keyword:[/dim] {out.mode}")
        console.print(f"     [dim]find:[/dim]    {out.find.model_dump(exclude_none=True)}")
        if out.recipe:
            console.print(f"     [dim]recipe:[/dim]  {out.recipe}")
        if out.columns:
            console.print(
                f"     [dim]columns:[/dim] {', '.join(f'{c}:{t}' for c, t in out.columns.items())}"
            )
        for r in out.renders_as:
            tgt = f"{r.component}:{r.kind}" if r.kind else r.component
            roles = f"  roles={r.roles}" if r.roles else ""
            console.print(f"     [dim]render:[/dim]  {tgt}{roles}")


def _emit_html(html: str, out_path: Path, message: str, no_open: bool) -> None:
    """Write a self-contained HTML file, report it, and open it in a browser tab."""
    import webbrowser

    out_path.write_text(html)
    typer.echo(message)
    if not no_open:
        webbrowser.open(out_path.resolve().as_uri())


def _serve_html(html: str, label: str, no_open: bool, port: int) -> None:
    """Serve the page from an ephemeral localhost server, open it, and tear down
    on Ctrl-C. Nothing is written to disk — use `--out` to export a file instead."""
    import http.server
    import socketserver
    import webbrowser

    body = html.encode("utf-8")

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — http.server API
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:  # silence per-request logging
            return

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), _Handler) as httpd:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        typer.echo(f"  {label}\n  Serving at {url} — Ctrl-C to stop (use --out to export a file).")
        if not no_open:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            typer.echo("\n  stopped.")


@app.command("preview")
def catalog_preview(
    output_id: Annotated[str, typer.Argument(help="Output id, e.g. qiime2_alpha_diversity")],
    theme: Annotated[str, typer.Option("--theme", "-t", help="Theme: light or dark")] = "light",
    out: Annotated[
        str | None,
        typer.Option(
            "--out", "-o", help="Export the self-contained HTML here instead of serving it"
        ),
    ] = None,
    port: Annotated[
        int, typer.Option("--port", help="Port for the ephemeral server (0 = auto)")
    ] = 0,
    no_open: Annotated[bool, typer.Option("--no-open", help="Do not open a browser tab")] = False,
) -> None:
    """Preview an output's components on its fixture, served on an ephemeral
    localhost server (Ctrl-C to stop); pass ``--out FILE`` to export a portable,
    self-contained HTML instead.

    Renders every ``renders_as`` target through the depictio **React viewer's**
    real ``ComponentRenderer`` (figure/card/table today). The data is computed
    Dash-free from the output's bundled ``fixture``. Needs the prebuilt bundle
    (``cd depictio/viewer && pnpm run build:catalog-preview``).
    """
    from depictio.catalog.payload import CatalogPayloadError, render_html
    from depictio.models.components.advanced_viz.catalog import load_catalog_entries

    pair = next(
        ((e, o) for e in load_catalog_entries() for o in e.outputs if o.id == output_id),
        None,
    )
    if pair is None:
        typer.echo(f"No output '{output_id}'. Try `depictio catalog list`.")
        raise typer.Exit(code=1)
    entry, output = pair

    try:
        html = render_html(output, theme, tool=entry)
    except CatalogPayloadError as exc:
        typer.echo(f"  could not preview {output_id!r}: {exc}")
        raise typer.Exit(code=1)

    if out:
        _emit_html(html, Path(out), f"  Wrote preview to {out}", no_open)
    else:
        _serve_html(html, f"catalog preview: {output_id}", no_open, port)


@app.command("gallery")
def catalog_gallery(
    theme: Annotated[str, typer.Option("--theme", "-t", help="Theme: light or dark")] = "light",
    out: Annotated[
        str | None,
        typer.Option(
            "--out", "-o", help="Export the self-contained HTML here instead of serving it"
        ),
    ] = None,
    port: Annotated[
        int, typer.Option("--port", help="Port for the ephemeral server (0 = auto)")
    ] = 0,
    no_open: Annotated[bool, typer.Option("--no-open", help="Do not open a browser tab")] = False,
) -> None:
    """Browse the whole catalog on one page (every tool's outputs, grouped, with
    component-type badges, fixture chips, search/filter, copyable ``renders_as``),
    served on an ephemeral localhost server (Ctrl-C to stop).

    Clicking an output opens its full live preview (same renderer as
    ``catalog preview``). Pass ``--out FILE`` to export a portable, self-contained
    HTML instead; needs the prebuilt bundle
    (``cd depictio/viewer && pnpm run build:catalog-preview``).
    """
    from depictio.catalog.payload import CatalogPayloadError, render_gallery_html
    from depictio.models.components.advanced_viz.catalog import load_catalog_entries

    entries = load_catalog_entries()
    if not entries:
        typer.echo("No catalog entries found.")
        raise typer.Exit(code=1)

    try:
        html = render_gallery_html(entries, theme)
    except CatalogPayloadError as exc:
        typer.echo(f"  could not build catalog gallery: {exc}")
        raise typer.Exit(code=1)

    n_out = sum(len(e.outputs) for e in entries)
    label = f"catalog gallery ({len(entries)} tools, {n_out} outputs)"
    if out:
        _emit_html(html, Path(out), f"  Wrote {label} to {out}", no_open)
    else:
        _serve_html(html, label, no_open, port)


@dev_app.command("columns")
def catalog_columns(
    recipe: Annotated[str, typer.Argument(help="Recipe ref, e.g. qiime2/ancombc.py")],
) -> None:
    """Print the output columns a recipe produces (to help write `roles`)."""
    from depictio.cli.cli.utils.rich_utils import console, render_records_table
    from depictio.models.components.advanced_viz.catalog import recipe_output_columns

    try:
        cols = recipe_output_columns(recipe)
    except Exception as exc:
        console.print(f"[red]:x: could not read recipe {recipe!r}: {exc}[/red]")
        raise typer.Exit(code=1)
    render_records_table([{"Column": c} for c in cols], title=f"Output columns of {recipe}")


# ---------------------------------------------------------------------------
# Shared validation core (used by both `validate` and the contributor-facing
# `lint`). Kept identical so the local check == the CI gate (nf-core pattern).
# ---------------------------------------------------------------------------


def _load_catalog_target(target: Path):
    """Load catalog entries from a tool folder, a directory of tools, or a flat file."""
    import yaml

    from depictio.models.components.advanced_viz.catalog import (
        CatalogEntry,
        load_entries_from_dir,
    )
    from depictio.models.components.advanced_viz.catalog import (
        _load_tool_dir as load_tool_dir,
    )

    if target.is_dir() and (target / "module.yaml").exists():
        return [load_tool_dir(target)]
    if target.is_dir():
        return load_entries_from_dir(target)
    return [CatalogEntry.model_validate(yaml.safe_load(target.read_text()))]


def _ground_problems(entries) -> list[str]:
    """Existence (nf-core/EDAM) + render column-grounding problems (empty = OK).

    Grounds each render's bound columns against the real data shape:
    the fixture (most complete) > the recipe's EXPECTED_SCHEMA > declared columns.
    """
    from depictio.models.components.advanced_viz.catalog import (
        check_existence,
        read_fixture_columns,
        recipe_output_columns,
    )

    problems: list[str] = check_existence(entries)
    for entry in entries:
        for out in entry.outputs:
            source = ""
            fx = out.fixture_file()
            if fx:
                try:
                    available = set(read_fixture_columns(fx))
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
    return problems


@dev_app.command("validate")
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
    from depictio.models.components.advanced_viz.catalog import CATALOG_DIR

    target = Path(path) if path else CATALOG_DIR
    try:
        entries = _load_catalog_target(target)
    except Exception as exc:
        typer.echo(f"  INVALID ({target}): {exc}")
        raise typer.Exit(code=1)

    problems = _ground_problems(entries)
    if problems:
        typer.echo(f"  INVALID ({target}):")
        for p in problems:
            typer.echo(f"    - {p}")
        raise typer.Exit(code=1)

    typer.echo(f"  OK: {len(entries)} catalog tool(s) valid in {target}")


@dev_app.command("match")
def catalog_match(
    run_dir: Annotated[str, typer.Argument(help="A pipeline run directory to scan")],
) -> None:
    """Recognise which catalog outputs are present in a run directory."""
    from depictio.cli.cli.utils.rich_utils import console, render_records_table
    from depictio.models.components.advanced_viz.catalog import match_run_dir

    matches = match_run_dir(run_dir)
    if not matches:
        console.print(f"[yellow]No catalogued tool outputs found under {run_dir}[/yellow]")
        return
    render_records_table(
        [{"File": str(hit.path), "Tool": hit.tool_id, "Output": hit.output_id} for hit in matches],
        title=f"Recognised {len(matches)} file(s) in {run_dir}",
    )


@dev_app.command("compose")
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
    from depictio.cli.cli.utils.rich_utils import console
    from depictio.models.components.advanced_viz.catalog import compose_run_dir

    by_tool = compose_run_dir(run_dir, confirm_with_versions=confirm_versions)
    if not by_tool:
        console.print(f"[yellow]No catalogued module outputs found under {run_dir}[/yellow]")
        return
    n_viz = sum(len(m.renders) for ms in by_tool.values() for m in ms)
    console.print(
        f"[bold]Proposed dashboard from {run_dir}:[/bold] {len(by_tool)} module(s), {n_viz} viz block(s)"
    )
    for tool_id, matches in sorted(by_tool.items()):
        console.print(f"\n  [cyan]{tool_id}[/cyan]")
        for m in matches:
            renders = ", ".join(m.renders) if m.renders else "—"
            console.print(f"      {m.output_id}  ([dim]{m.path}[/dim])  → {renders}")


@dev_app.command("refresh-index")
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


@dev_app.command("schema")
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


# ---------------------------------------------------------------------------
# Scaffolding: `dev catalog new` — turn a blank page into fill-in-the-blanks
# (nf-core `modules create` style: TODO markers + optional meta.yml prefill).
# ---------------------------------------------------------------------------


def _fetch_nf_core_meta(module: str) -> dict:
    """Fetch + normalise an nf-core module's meta.yml to prefill tool identity."""
    import urllib.request

    import yaml

    url = (
        "https://raw.githubusercontent.com/nf-core/modules/master/"
        f"modules/nf-core/{module}/meta.yml"
    )
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
        raw = yaml.safe_load(resp.read()) or {}
    meta: dict = {
        "name": raw.get("name") or module,
        "description": raw.get("description"),
        "_nf_core_url": (
            f"https://github.com/nf-core/modules/tree/master/modules/nf-core/{module}"
        ),
    }
    for entry in raw.get("tools") or []:
        if isinstance(entry, dict):
            info = next(iter(entry.values()), {}) or {}
            ident = str(info.get("identifier") or "")
            if ident.startswith("biotools:"):
                meta["_biotools_url"] = f"https://bio.tools/{ident.split(':', 1)[1]}"
                break
    return meta


def _infer_columns(path: Path) -> dict[str, str]:
    """Infer {column: polars-dtype-name} from a fixture (for a reference comment)."""
    import polars as pl

    from depictio.models.components.advanced_viz.catalog import ALLOWED_DTYPES

    if path.suffix == ".parquet":
        schema = pl.read_parquet_schema(path)
    else:
        sep = "\t" if path.suffix == ".tsv" else ","
        schema = pl.read_csv(path, separator=sep, n_rows=200).schema
    return {
        name: (s if (s := str(dtype)) in ALLOWED_DTYPES else "String")
        for name, dtype in schema.items()
    }


def _placeholder_tsv() -> str:
    return "sample\tvalue\nsample_1\t1.0\nsample_2\t2.0\n"


def _module_yaml_text(tool: str, meta: dict | None) -> str:
    meta = meta or {}
    lines = [
        "# yaml-language-server: $schema=../catalog.schema.json",
        f"id: {tool}",
        f"name: {meta.get('name') or tool}",
    ]
    if meta.get("_nf_core_url"):
        lines.append(f"nf_core_url: {meta['_nf_core_url']}")
    else:
        lines.append(
            "# TODO: nf_core_url: "
            f"https://github.com/nf-core/modules/tree/master/modules/nf-core/{tool}"
        )
    if meta.get("_biotools_url"):
        lines.append(f"biotools_url: {meta['_biotools_url']}")
    if meta.get("description"):
        lines.append(f"# from meta.yml: {meta['description']}")
    lines.append("# Keep module.yaml lightweight — see depictio/catalog/SCHEMA.md")
    return "\n".join(lines) + "\n"


def _output_yaml_text(
    tool: str, output_id: str, fixture_name: str | None, columns: dict[str, str]
) -> str:
    lines = [
        "# yaml-language-server: $schema=../catalog.schema.json",
        f"id: {output_id}",
        'description: "TODO: describe this output"',
        "# How to recognise the raw file in a scanned run (set filename and/or path_glob):",
        "find:",
        f'  path_glob: "**/{tool}/**/TODO-filename"  # TODO: real glob',
    ]
    if fixture_name:
        lines.append(f"fixture: {fixture_name}")
    if columns:
        lines.append("# Columns inferred from the fixture (reference only — grounding reads the")
        lines.append("# fixture header directly, so you need not declare `columns:` yourself):")
        lines += [f"#   {col}: {dtype}" for col, dtype in columns.items()]
    lines += [
        "# `renders_as` omitted → defaults to a browsable `table` (the no-code floor).",
        "# Uncomment to bind richer components — see depictio/catalog/SCHEMA.md:",
        "# renders_as:",
        "#   - component: figure",
        "#     visu_type: bar            # TODO: box/scatter/bar/histogram/line/heatmap",
        "#     dict_kwargs: { x: TODO-x-col, y: TODO-y-col }",
        "#   - component: card",
        "#     column: TODO-col",
        "#     aggregation: average",
    ]
    return "\n".join(lines) + "\n"


@dev_app.command("new")
def catalog_new(
    tool: Annotated[str, typer.Argument(help="Tool id / folder name, e.g. mosdepth")],
    output: Annotated[
        str, typer.Option("--output", "-o", help="First output name (id = <tool>_<output>)")
    ] = "output",
    from_nf_core: Annotated[
        str | None,
        typer.Option(
            "--from-nf-core",
            help="nf-core module to prefill identity from (fetches its meta.yml), e.g. fastqc",
        ),
    ] = None,
    fixture: Annotated[
        str | None,
        typer.Option(
            "--fixture", help="Sample file (tsv/csv/parquet) to copy in and infer columns from"
        ),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite existing scaffold files")
    ] = False,
) -> None:
    """Scaffold a new catalog tool folder (module.yaml + one output + fixture).

    Generated files carry `# TODO:` markers where a human must decide (the `find`
    glob, richer renders). With `--from-nf-core` the identity is prefilled from
    the module's nf-core meta.yml; with `--fixture` the sample is copied in and
    its columns inferred. Then run
    `depictio dev catalog validate --path depictio/catalog/<tool>`.
    """
    import shutil

    from depictio.models.components.advanced_viz.catalog import CATALOG_DIR

    tool_dir = CATALOG_DIR / tool
    module_path = tool_dir / "module.yaml"
    output_path = tool_dir / f"{output}.yaml"
    output_id = f"{tool}_{output}"

    clashes = [p for p in (module_path, output_path) if p.exists()]
    if clashes and not force:
        joined = ", ".join(str(p) for p in clashes)
        typer.echo(f"  refusing to overwrite existing file(s): {joined}. Re-run with --force.")
        raise typer.Exit(code=1)

    meta: dict | None = None
    if from_nf_core:
        try:
            meta = _fetch_nf_core_meta(from_nf_core)
            typer.echo(f"  fetched nf-core meta.yml for {from_nf_core!r}")
        except Exception as exc:
            typer.echo(
                f"  could not fetch nf-core meta for {from_nf_core!r}: {exc} "
                "(continuing with a minimal skeleton)"
            )

    tool_dir.mkdir(parents=True, exist_ok=True)

    columns: dict[str, str] = {}
    if fixture:
        src = Path(fixture)
        if not src.exists():
            typer.echo(f"  fixture not found: {src}")
            raise typer.Exit(code=1)
        fixture_name = f"{output}{src.suffix}"
        shutil.copy(src, tool_dir / fixture_name)
        try:
            columns = _infer_columns(tool_dir / fixture_name)
        except Exception as exc:
            typer.echo(f"  could not infer columns from fixture: {exc}")
    else:
        fixture_name = f"{output}.tsv"
        (tool_dir / fixture_name).write_text(_placeholder_tsv())
        columns = {"sample": "String", "value": "Float64"}

    module_path.write_text(_module_yaml_text(tool, meta))
    output_path.write_text(_output_yaml_text(tool, output_id, fixture_name, columns))

    typer.echo(f"  scaffolded {tool_dir}:")
    for name in (module_path.name, output_path.name, fixture_name):
        typer.echo(f"    - {name}")
    typer.echo("  next: fill the `# TODO:` markers, then run")
    typer.echo(f"        depictio dev catalog validate --path {tool_dir}")


def _write_snapshots(entries, out_dir: Path) -> None:
    """Write a Dash-free preview-payload JSON per output (a diffable PR preview)."""
    import json

    from depictio.catalog.payload import build_payload

    out_dir.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    for entry in entries:
        for out in entry.outputs:
            try:
                payload = build_payload(out, tool=entry)
            except Exception as exc:  # noqa: BLE001 — preview is best-effort
                skipped += 1
                typer.echo(f"    - skip {out.id}: {exc}")
                continue
            (out_dir / f"{out.id}.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
            )
            written += 1
    typer.echo(f"  snapshots: {written} written, {skipped} skipped → {out_dir}")


@dev_app.command("lint")
def catalog_lint(
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Lint a single tool folder/file instead of all"),
    ] = None,
    snapshot: Annotated[
        str | None,
        typer.Option(
            "--snapshot",
            help="Also write per-output preview-payload JSON snapshots to this directory",
        ),
    ] = None,
) -> None:
    """Contributor-facing catalog check: the SAME gate as CI `validate`, with
    friendlier output and an optional rendered-payload snapshot for PR preview.

    `--snapshot DIR` writes one Dash-free preview payload JSON per output (the
    same blob `catalog preview` renders) so a reviewer can diff the result of a
    contribution without running the app.
    """
    from depictio.models.components.advanced_viz.catalog import CATALOG_DIR

    target = Path(path) if path else CATALOG_DIR
    try:
        entries = _load_catalog_target(target)
    except Exception as exc:
        typer.echo(f"  ✗ INVALID ({target}): {exc}")
        raise typer.Exit(code=1)

    problems = _ground_problems(entries)
    if problems:
        typer.echo(f"  ✗ {len(problems)} problem(s) in {target}:")
        for p in problems:
            typer.echo(f"    - {p}")
        raise typer.Exit(code=1)

    n_out = sum(len(e.outputs) for e in entries)
    typer.echo(f"  ✓ OK: {len(entries)} tool(s), {n_out} output(s) valid in {target}")
    if snapshot:
        _write_snapshots(entries, Path(snapshot))
