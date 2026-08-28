"""CLI for the bio-catalog: the tool→recipe→component linking table.

Discovery (`list`/`info`), recognition (`match`), recipe-output lookup
(`columns`), JSON-Schema export (`schema`), and a full CI-friendly `validate`
that grounds every `renders_as` role against the recipe's real output columns.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer()


@contextlib.contextmanager
def _stdout_off_the_wire() -> Iterator[None]:
    """Keep incidental library output off stdout while building a `--json` payload.

    depictio's logger writes to stdout, so a single DEBUG line in front of the
    payload makes the output unparseable. `genKinds.ts` only checks that stdout
    starts with `{`, so a polluted stream is not an error there — it silently
    falls back to the stale committed snapshot. Redirect during collection; the
    payload itself is written after the block.
    """
    with contextlib.redirect_stdout(sys.stderr):
        yield


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


def _check_fixture_sanity(entries) -> list[str]:
    """Catch fixtures that ground the bindings but say nothing about the tool.

    Both cases have shipped: a fixture with a header and no data (grounds every
    column name, proves nothing), and a demo table pasted in from somewhere else
    — the same file under two different tools. Column-level relevance is a human
    judgement, but "empty" and "this is literally another tool's fixture" are not.
    """
    import hashlib

    problems: list[str] = []
    # digest -> (tool id, output id) of the first output that used it.
    by_digest: dict[str, tuple[str, str]] = {}
    for entry in entries:
        for out in entry.outputs:
            path = out.fixture_file()
            if not path:
                continue
            try:
                data = path.read_bytes()
            except OSError as exc:
                problems.append(f"{out.id}: fixture {out.fixture} → {exc}")
                continue
            # Header + at least one data row. Parquet is binary; leave it alone.
            if path.suffix in (".tsv", ".csv"):
                rows = [line for line in data.splitlines() if line.strip()]
                if len(rows) < 2:
                    problems.append(
                        f"{out.id}: fixture {out.fixture} has no data rows — it grounds every "
                        "binding while showing nothing about the output"
                    )
            digest = hashlib.sha256(data).hexdigest()
            twin = by_digest.get(digest)
            # Sharing a fixture between two outputs of the SAME tool is normal
            # (one file, two views of it); sharing across tools is a copy-paste.
            if twin is not None and twin[0] != entry.id:
                problems.append(
                    f"{out.id}: fixture {out.fixture} is byte-identical to {twin[1]}'s — a "
                    "fixture must be a sample of THIS output"
                )
            by_digest.setdefault(digest, (entry.id, out.id))
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
    import yaml

    from depictio.models.components.advanced_viz.catalog import (
        CATALOG_DIR,
        CatalogEntry,
        check_existence,
        ground_render_dtypes,
        load_entries_from_dir,
        read_fixture_schema,
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
    # A fixture is what every binding is grounded against, so a placeholder one
    # makes the whole entry meaningless while still passing every other check.
    problems.extend(_check_fixture_sanity(entries))
    # Ground each render's bound columns against the real data shape:
    # the fixture (most complete) > the recipe's EXPECTED_SCHEMA > declared columns.
    # Beyond name existence, dtypes are checked too (advanced_viz roles + numeric
    # card aggregations) via `ground_render_dtypes`.
    for entry in entries:
        for out in entry.outputs:
            source = ""
            col_dtypes: dict[str, str] = {}
            fx = out.fixture_file()
            if fx:
                try:
                    col_dtypes = read_fixture_schema(fx)
                    available = set(col_dtypes)
                    source = f"fixture {out.fixture}"
                except Exception as exc:
                    problems.append(f"{out.id}: fixture {out.fixture} → {exc}")
                    continue
                # Author-declared dtypes are authoritative over CSV inference.
                col_dtypes.update(out.columns)
            elif out.recipe:
                try:
                    available = set(recipe_output_columns(out.recipe))
                    source = f"recipe {out.recipe}"
                except Exception as exc:
                    problems.append(f"{out.id}: recipe {out.recipe} → {exc}")
                    continue
            elif out.columns:
                col_dtypes = dict(out.columns)
                available = set(col_dtypes)
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
                    continue
                problems.extend(ground_render_dtypes(out.id, r, col_dtypes))
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
    nf-core/modules list, the EDAM term list and the MultiQC module list, and
    rewrites `depictio/catalog/_index/{nf_core_modules,edam_terms,multiqc_modules}.txt`.
    """
    import csv
    import io
    import json
    import urllib.request

    from depictio.models.components.advanced_viz.catalog import INDEX_DIR

    def _get(url: str) -> bytes:
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
            return resp.read()

    # Modules referenced by bundled catalog entries but absent from
    # nf-core/modules master (e.g. ampliseq-local qiime2) live below this marker
    # and are preserved across refreshes so a refresh doesn't invalidate them.
    local_marker = "# --- catalog-local (preserved across refresh) ---"

    def _preserved_local(path: Path) -> list[str]:
        if not path.exists():
            return []
        after = False
        kept: list[str] = []
        for line in path.read_text().splitlines():
            if line.startswith(local_marker):
                after = True
                continue
            s = line.strip()
            if after and s and not s.startswith("#"):
                kept.append(s)
        return kept

    # nf-core modules: paths like modules/nf-core/<module>/main.nf
    try:
        nf_path = INDEX_DIR / "nf_core_modules.txt"
        local = _preserved_local(nf_path)
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
        extras = sorted(m for m in local if m not in set(modules))
        text = (
            "# Authoritative nf-core module paths (generated by `catalog refresh-index`).\n"
            + "\n".join(modules)
            + "\n"
        )
        if extras:
            text += "\n" + local_marker + "\n" + "\n".join(extras) + "\n"
        nf_path.write_text(text)
        typer.echo(f"  nf_core_modules.txt: {len(modules)} modules (+{len(extras)} catalog-local)")
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

    # MultiQC modules: one directory per supported tool under multiqc/modules/.
    # A tool MultiQC already parses usually reaches depictio through the MultiQC
    # integration, so Tool Studio warns before someone hand-authors a second,
    # parallel entry for it. Advisory only: it never blocks authoring.
    try:
        tree = json.loads(
            _get("https://api.github.com/repos/MultiQC/MultiQC/git/trees/main?recursive=1")
        )
        prefix = "multiqc/modules/"
        mqc = sorted(
            {
                name
                for e in tree.get("tree", [])
                if e.get("type") == "tree"
                and e["path"].startswith(prefix)
                and "/" not in (name := e["path"][len(prefix) :])
                and not name.startswith("__")
            }
        )
        (INDEX_DIR / "multiqc_modules.txt").write_text(
            "# MultiQC modules (generated by `catalog refresh-index`).\n"
            "# Advisory index: a tool listed here is already parsed by MultiQC.\n"
            + "\n".join(mqc)
            + "\n"
        )
        typer.echo(f"  multiqc_modules.txt: {len(mqc)} modules")
    except Exception as exc:
        typer.echo(f"  FAILED MultiQC: {exc}")
        raise typer.Exit(code=1)


# The three shapes a catalog YAML can take, and the model that describes each.
# A folder splits an entry across files, so `module.yaml` and `<output>.yaml`
# each need their OWN schema: pointing them at the whole-entry schema (which
# requires `outputs` and forbids extras) makes every editor flag them as invalid.
_SCHEMA_MODELS = {
    "entry": ("CatalogEntry", "a flat single-file entry (tool fields + `outputs`)"),
    "module": ("CatalogTool", "a folder's `module.yaml` (tool identity only)"),
    "output": ("CatalogOutput", "a folder's `<output>.yaml` (find/recipe/renders_as)"),
}


@dev_app.command("schema")
def catalog_schema(
    model: Annotated[
        str,
        typer.Option(
            "--model",
            "-m",
            help=f"Which shape to describe: {', '.join(_SCHEMA_MODELS)} (default: entry).",
        ),
    ] = "entry",
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Write the JSON Schema here (default: stdout)"),
    ] = None,
) -> None:
    """Emit the JSON Schema for a catalog file (regenerate the committed copy)."""
    import json

    import depictio.models.components.advanced_viz.catalog as catalog_models

    if model not in _SCHEMA_MODELS:
        typer.echo(f"  Unknown --model {model!r}; expected one of {', '.join(_SCHEMA_MODELS)}")
        raise typer.Exit(code=1)
    class_name, _description = _SCHEMA_MODELS[model]
    text = json.dumps(getattr(catalog_models, class_name).model_json_schema(), indent=2) + "\n"
    if output:
        Path(output).write_text(text)
        typer.echo(f"  Wrote {model} JSON Schema to {output}")
    else:
        typer.echo(text)


# advanced_viz kinds whose renderer computes server-side (Celery / heavy libs),
# so a purely client-side tool (e.g. tool-studio) cannot preview them — it
# must show a "verify in depictio" badge instead of a live plot.
_HEAVY_KINDS = frozenset({"embedding", "complex_heatmap", "upset_plot", "sankey", "oncoplot"})


@dev_app.command("kinds")
def catalog_kinds(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit a machine-readable JSON map (for tool-studio)."),
    ] = False,
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Write the JSON here (default: stdout)"),
    ] = None,
) -> None:
    """Emit the advanced_viz kind descriptors (source for tool-studio's kinds.json).

    Shape: ``{"kinds": [ {viz_kind, label, description, icon, category,
    required_roles, roles: {role: {required, dtypes, description}}, heavy} ]}``
    — byte for byte what ``GET /advanced_viz/kinds`` returns, plus ``heavy``.

    That equality is the point: Tool Studio has no backend, so its viz-kind
    picker reads this snapshot where the app reads the endpoint. It used to
    read a narrower map (roles flattened to a dtype list, a title-cased label,
    no description or icon), which is why its picker could not be depictio's.
    ``heavy`` and ``role_names`` are the studio's two additions: those kinds
    are computed by a Celery worker and cannot be previewed client-side at all,
    and the role-name aliases let a backend-less picker rank kinds the way
    ``suggest_viz_kinds`` does server-side.
    """
    import json

    from depictio.models.components.advanced_viz.schemas import ROLE_NAMES, kind_descriptors

    kinds = [
        {
            **descriptor,
            "heavy": descriptor["viz_kind"] in _HEAVY_KINDS,
            # Column names each role commonly goes by. The server ranks kinds
            # against a DC with `suggest_viz_kinds`; a backend-less consumer has
            # to rank them itself, and dtype alone puts every kind at 100%.
            "role_names": {
                role: sorted(names)
                for role, names in ROLE_NAMES.get(descriptor["viz_kind"], {}).items()
            },
        }
        for descriptor in kind_descriptors()
    ]
    kinds.sort(key=lambda k: k["viz_kind"])

    if not as_json:
        # Human-readable summary.
        for kind in kinds:
            flag = " (heavy — no client preview)" if kind["heavy"] else ""
            typer.echo(f"{kind['viz_kind']}{flag}: {', '.join(kind['roles'])}")
        return

    text = json.dumps({"kinds": kinds}, indent=2, sort_keys=True) + "\n"
    if output:
        Path(output).write_text(text)
        typer.echo(f"  Wrote kinds JSON to {output}")
    else:
        typer.echo(text)


@dev_app.command("manifest")
def catalog_manifest(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the machine-readable JSON (for tool-studio)."),
    ] = False,
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Write the JSON here (default: stdout)"),
    ] = None,
) -> None:
    """Emit a JSON snapshot of the existing catalog (source for tool-studio's
    catalog.json). Powers duplicate detection ("this tool already exists") and
    "add a visualization to an existing tool" — so the web app can compare the
    wizard against what is already in `depictio/catalog/` offline.

    Per tool: identity + outputs; per output: id/slug/path_glob, declared
    columns, existing `renders_as`, the repo-relative YAML path and its raw text
    (so the app can append a render and open an update PR), and — when the
    fixture is a small co-located CSV/TSV — its content, so new renders ground
    and preview client-side exactly like an upload.
    """
    import json

    import yaml as _yaml

    from depictio.models.components.advanced_viz.catalog import (
        CATALOG_DIR,
        load_entries_from_dir,
    )

    repo_root = CATALOG_DIR.parents[1]

    def _rel(path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return str(path.relative_to(repo_root))
        except ValueError:
            return str(path)

    def _output_file(src_dir: Path | None, out_id: str) -> tuple[Path | None, str | None]:
        """The output's own YAML file in a folder-based tool (matched by id)."""
        if src_dir is None or not src_dir.is_dir():
            return None, None
        for path in sorted(src_dir.glob("*.yaml")):
            if path.name == "module.yaml":
                continue
            try:
                raw = path.read_text()
                if isinstance(data := _yaml.safe_load(raw), dict) and data.get("id") == out_id:
                    return path, raw
            except Exception:
                continue
        return None, None

    def _fixture_text(path: Path | None) -> str | None:
        """Embed a representative sample of a co-located CSV/TSV fixture (header +
        up to 200 rows) so new renders ground + preview client-side without
        bloating the bundle. Parquet / non-text fixtures stay null."""
        try:
            if not (path and path.exists() and path.suffix.lower() in {".csv", ".tsv"}):
                return None
            lines = path.read_text().splitlines()
            return "\n".join(lines[:201]) + "\n" if lines else None
        except Exception:
            return None

    tools: list[dict[str, object]] = []
    for entry in load_entries_from_dir(CATALOG_DIR):
        outs: list[dict[str, object]] = []
        tool_dir: Path | None = None
        for o in entry.outputs:
            tool_dir = o._source_dir or tool_dir
            yaml_path, raw = _output_file(o._source_dir, o.id)
            dump = o.model_dump(mode="json", exclude_none=True)
            outs.append(
                {
                    **dump,
                    "slug": o.id.removeprefix(f"{entry.id}_"),
                    "path_glob": o.find.path_glob,
                    "yamlPath": _rel(yaml_path),
                    "rawYaml": raw,
                    "fixtureContent": _fixture_text(o.fixture_file()),
                }
            )
        tools.append(
            {
                "id": entry.id,
                "name": entry.name,
                "description": entry.description,
                "homepage": entry.homepage,
                "nf_core_url": entry.nf_core_url,
                "biotools_url": entry.biotools_url,
                "dir": _rel(tool_dir),
                "outputs": outs,
            }
        )

    payload = {"tools": tools}
    if not as_json:
        for t in tools:
            n = sum(
                len(o["renders_as"]) for o in t["outputs"] if isinstance(o.get("renders_as"), list)
            )  # type: ignore[arg-type]
            typer.echo(f"{t['id']}: {len(t['outputs'])} output(s), {n} render(s)")
        return

    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output:
        Path(output).write_text(text)
        typer.echo(f"  Wrote catalog manifest to {output}")
    else:
        typer.echo(text)


@dev_app.command("figure-params")
def catalog_figure_params(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the machine-readable JSON (for tool-studio)."),
    ] = False,
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Write the JSON here (default: stdout)"),
    ] = None,
) -> None:
    """Emit the figure builder's visualization list + per-viz parameter specs.

    This is the exact payload the React figure builder fetches from
    ``/figure/visualizations`` and ``/figure/parameter-discovery/{viz_type}``.
    Tool Studio seeds its builder store with this snapshot so depictio's real
    figure UI renders offline (no backend). Shape::

        { "visualizations": [ {name, label, description, icon, group}, ... ],
          "params": { "<viz_type>": <VisualizationDefinition JSON>, ... } }

    Derived from the pure Plotly-Express introspection in
    ``depictio/api/v1/services/figure/{definitions,parameter_discovery}.py`` —
    the drift-free source the web app snapshots at build time.
    """
    import json

    visualizations: list[dict[str, object]] = []
    params: dict[str, object] = {}
    failed: list[str] = []
    # Parameter discovery logs to stdout on import; keep it off the JSON stream.
    with _stdout_off_the_wire():
        from depictio.api.v1.services.figure.definitions import (
            get_available_visualizations,
            get_visualization_definition,
        )

        for v in get_available_visualizations():
            group = v.group.value if hasattr(v.group, "value") else str(v.group)
            visualizations.append(
                {
                    "name": v.name,
                    "label": v.label,
                    "description": v.description,
                    "icon": v.icon,
                    "group": group,
                }
            )
            try:
                viz_def = get_visualization_definition(v.name.lower())
                params[v.name.lower()] = viz_def.model_dump(mode="json")
            except Exception as exc:  # a single bad viz shouldn't sink the snapshot
                failed.append(v.name)
                typer.echo(f"  WARN: parameter discovery failed for {v.name!r}: {exc}", err=True)
    # A partial snapshot silently degrades the offline figure builder, so make it
    # a hard failure rather than a warning nobody reads.
    if failed:
        typer.echo(f"  INVALID: parameter discovery failed for {sorted(failed)}", err=True)
        raise typer.Exit(code=1)

    payload = {"visualizations": visualizations, "params": params}

    if not as_json:
        for item in visualizations:
            n = len(params.get(str(item["name"]).lower(), {}).get("parameters", []))  # type: ignore[union-attr]
            typer.echo(f"{item['name']}: {n} parameters")
        return

    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output:
        Path(output).write_text(text)
        typer.echo(f"  Wrote figure-params JSON to {output}")
    else:
        typer.echo(text)
