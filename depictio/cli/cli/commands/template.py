"""Template authoring commands.

``depictio template export`` freezes an existing project + its dashboards into
a reusable template bundle (the inverse of ``depictio ingest --template``). The
server does the heavy lifting (sanitization, re-parameterization, tag-based
dashboard export, round-trip check); the CLI unpacks the returned archive into
a ``<template_id>/`` directory ready to drop into ``depictio/projects/``.

``depictio template compose`` writes one offline from what the catalog
recognises in a results directory: what ``depictio ingest`` composes by itself
when no bundled template fits a run.
"""

import io
import re
import zipfile
from pathlib import Path
from typing import Annotated, Optional

import httpx
import typer
from rich.console import Console

from depictio.cli.cli.utils.renamed import pick_renamed
from depictio.cli.cli.utils.server_target import ServerOption, resolve_server

app = typer.Typer()
console = Console()

_DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _members_within(archive: zipfile.ZipFile, target: Path) -> list[str]:
    """Names in ``archive`` once every one is confirmed to land inside ``target``.

    Raises ``ValueError`` naming the first member that would not: an absolute
    name, a ``..`` segment, or a resolved path that leaves the directory
    (zip-slip). Checked before any byte is written, so a hostile bundle
    leaves nothing behind.
    """
    root = target.resolve()
    names = archive.namelist()
    for name in names:
        parts = [p for p in re.split(r"[\\/]+", name) if p]
        if (
            not parts
            or name.startswith(("/", "\\"))
            or _DRIVE_PREFIX_RE.match(name)
            or ".." in parts
            or not (root / Path(*parts)).resolve().is_relative_to(root)
        ):
            raise ValueError(f"member '{name}' would be written outside {target}")
    return names


TEMPLATE_PANEL = "Template"
OUTPUT_PANEL = "Output"

# The options these commands took before --server and --data-dir. Still accepted, out of the help.
LegacyConfigOption = Annotated[str | None, typer.Option("--config", "-c", hidden=True)]
ApiUrlOption = Annotated[str | None, typer.Option("--api", hidden=True)]
LegacyDataRootOption = Annotated[str | None, typer.Option("--data-root", hidden=True)]


@app.command()
def export(
    project_id: Annotated[str, typer.Argument(help="Project ID to export")],
    template_id: Annotated[
        str,
        typer.Option(
            "--template-id",
            "-t",
            help="Template id, e.g. 'my-lab/rnaseq-qc/1'",
            rich_help_panel=TEMPLATE_PANEL,
        ),
    ],
    server: ServerOption = None,
    config_path: LegacyConfigOption = None,
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory to unpack the bundle into",
            rich_help_panel=OUTPUT_PANEL,
        ),
    ] = Path("."),
    version: Annotated[
        str,
        typer.Option("--version", help="Template version", rich_help_panel=TEMPLATE_PANEL),
    ] = "1.0.0",
    description: Annotated[
        Optional[str],
        typer.Option("--description", help="Template description", rich_help_panel=TEMPLATE_PANEL),
    ] = None,
    data_dir: Annotated[
        Optional[str],
        typer.Option(
            "--data-dir",
            help="Local path prefix to re-parameterize as {DATA_ROOT} in the template",
            rich_help_panel=TEMPLATE_PANEL,
        ),
    ] = None,
    data_root: LegacyDataRootOption = None,
    api_url: ApiUrlOption = None,
) -> None:
    """Export a project + its dashboards as a template bundle.

    The inverse of `depictio ingest --template`: the bundle can be ingested on
    another dataset.

    Example:
        depictio template export 6824cb3b89d2b72169309737 \\
          --template-id my-lab/rnaseq-qc/1 --server admin_config.yaml -o depictio/projects
    """
    data_dir = pick_renamed(data_dir, data_root, "--data-dir", "--data-root")
    console.print("[cyan]Loading CLI configuration...[/cyan]")
    config_file = resolve_server(server, config_path, legacy_option="--config")
    try:
        from depictio.cli.cli.utils.common import generate_api_headers, load_depictio_config

        cli_config = load_depictio_config(yaml_config_path=config_file)
        headers = generate_api_headers(cli_config)
        if api_url is None:
            api_url = str(cli_config.api_base_url)
    except Exception as e:
        console.print(f"[red]Error loading CLI config: {e}[/red]")
        console.print("[yellow]Hint: pass --server local or a CLI configuration file[/yellow]")
        raise typer.Exit(1)

    url = f"{api_url}/depictio/api/v1/projects/{project_id}/export_template"
    payload = {
        "template_id": template_id,
        "version": version,
        "description": description,
        "data_root": data_dir,
    }
    console.print(f"[cyan]Exporting project {project_id} as template '{template_id}'...[/cyan]")

    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        console.print(f"[red]Error: HTTP {e.response.status_code}[/red]")
        console.print(f"  {e.response.text}")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    target = output_dir / template_id
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            # Validate every member before creating anything: a bundle that
            # tries to escape the target directory must leave no trace.
            names = _members_within(archive, target)
            target.mkdir(parents=True, exist_ok=True)
            archive.extractall(target)
    except zipfile.BadZipFile:
        console.print("[red]Error: the server response is not a valid zip bundle[/red]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]Refusing to unpack the bundle: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓ Template bundle written to: {target}[/green]")
    for name in sorted(names):
        console.print(f"  - {name}")
    console.print(
        "[cyan]Drop the directory into depictio/projects/ (or a template search path) "
        "and it is auto-discovered.[/cyan]"
    )


@app.command("compose")
def compose(
    data_root: Annotated[Path, typer.Argument(help="Results directory to compose a dashboard for")],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Write the template here, to edit it and ingest with it: `depictio ingest "
            "<dir> --template <out>`. Default: where `depictio ingest` keeps composed templates",
        ),
    ] = None,
    include_unknown: Annotated[
        bool,
        typer.Option(
            "--include-unknown",
            help="Also include the tabular files the catalog does not recognise",
        ),
    ] = False,
    include: Annotated[
        list[str] | None,
        typer.Option(
            "--include",
            help="Include the unrecognised files matching this glob (relative to the "
            "directory); repeatable",
        ),
    ] = None,
    project_name: Annotated[
        str | None, typer.Option("--project", help="Name of the project to create")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="List everything left out, with the reason")
    ] = False,
):
    """Compose a template from the files the catalog recognises in a results directory.

    Offline: nothing is ingested. Prints what was recognised, the tabs and key
    metrics of the dashboard, what was left out and why, and the tabular files
    nothing recognised with what each could show. This is what `depictio ingest
    <dir>` does by itself when no bundled template fits the run.
    """
    from depictio.cli.cli.utils.compose import ComposedTemplate, compose_template, print_report
    from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
    from depictio.models.models.run_info import read_run_info

    if not data_root.is_dir():
        rich_print_checked_statement(f"{data_root} is not a directory", "error")
        raise typer.Exit(code=1)
    info = read_run_info(data_root)
    result = compose_template(
        data_root,
        out_dir=output,
        include_unknown=include_unknown,
        include=include or (),
        project_name=project_name,
        pipeline_name=info.pipeline_name if info else None,
        pipeline_version=info.pipeline_version if info else None,
        engine=info.engine if info else None,
    )
    print_report(result, verbose=verbose)
    if not isinstance(result, ComposedTemplate):
        rich_print_checked_statement(
            f"Nothing in {data_root} is recognised by the catalog: no template written.",
            "warning",
        )
        raise typer.Exit(code=1)
    rich_print_checked_statement(f"Template written to {result.template_dir}", "success")
    rich_print_checked_statement(
        f"Ingest it: depictio ingest {data_root} --template {result.template_dir}",
        "info",
    )


def _load_metadata(template: str):
    """(TemplateMetadata, path) for a template id or path; exits on a load error."""
    import yaml
    from pydantic import ValidationError

    from depictio.cli.cli.utils.templates import locate_template
    from depictio.models.models.templates import TemplateMetadata

    try:
        path = locate_template(template)
    except FileNotFoundError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1)
    raw = yaml.safe_load(path.read_text()) or {}
    try:
        return TemplateMetadata(**(raw.get("template") or {})), path
    except ValidationError as exc:
        console.print(f"[red]✗ {path}: the template does not load[/red]")
        for err in exc.errors():
            where = ".".join(str(p) for p in err["loc"])
            console.print(f"  [red]{where}: {err['msg']}[/red]")
        raise typer.Exit(1)


def _print_check(result, *, verbose: bool) -> None:
    from rich.table import Table

    from depictio.cli.cli.utils.template_check import TemplateCheck

    assert isinstance(result, TemplateCheck)
    console.print(f"\n[bold]{result.template_id}[/bold]  [dim]{result.path or ''}[/dim]")
    table = Table(show_lines=False, pad_edge=False)
    table.add_column("variable", style="bold")
    table.add_column("set by")
    table.add_column("default run" if result.schema_checked else "", justify="center")
    if result.fired is not None:
        table.add_column("this run", justify="center")
    table.add_column("when set → template")
    mark = {True: "[green]set[/green]", False: "[dim]–[/dim]", None: ""}
    by = {
        "rule": "[cyan]{how}[/cyan]",
        "auto": "[magenta]auto[/magenta]: {how}",
        "user": "[yellow]--var[/yellow]",
        "required": "[yellow]required[/yellow]",
    }
    for row in result.rows:
        if row.source in ("user", "required") and not row.effects and not verbose:
            continue
        cells = [row.name, by[row.source].format(how=row.how), mark[row.on_default_run]]
        if result.fired is not None:
            cells.append(mark[row.on_this_run])
        cells.append("\n".join(row.effects) or "[dim]in paths only[/dim]")
        table.add_row(*cells)
    console.print(table)
    if result.fired is not None:
        if result.fired:
            console.print("[bold]This run fires:[/bold]")
            for f in result.fired:
                console.print(f"  • [cyan]{f.condition}[/cyan] → {f.effect}")
        else:
            console.print("[bold]This run fires no conditional[/bold]: the full template applies.")
    for var, missing in result.unknown_params.items():
        console.print(
            f"[red]✗ {var} reads {', '.join(missing)}: not a parameter of this release[/red]"
        )
    if result.schema_checked and not result.unknown_params:
        console.print("[green]✓ every param a rule reads exists in this release[/green]")
    if result.suspect_skip_params:
        console.print(
            "[yellow]! skip_* params no rule reads, whose tool the template names:[/yellow] "
            + ", ".join(result.suspect_skip_params)
        )
        console.print(
            "  [dim]a run with one of them may lack files the template reads: check with "
            "`depictio ingest <run> --dry-run`, then add a rule and a conditional "
            "(docs/template-params.md)[/dim]"
        )
    others = len(result.unread_skip_params) - len(result.suspect_skip_params)
    if others:
        console.print(f"  [dim]{others} other skip_* params name nothing the template reads[/dim]")


@app.command("check")
def check(
    template: Annotated[
        str | None,
        typer.Argument(
            help="Template id (nf-core/rnaseq/3.26.0, nf-core/rnaseq) or path. "
            "Omitted with --run: the template `depictio ingest` would pick"
        ),
    ] = None,
    run: Annotated[
        Path | None,
        typer.Option("--run", help="A results directory: its pipeline_info/params_<ts>.json"),
    ] = None,
    params: Annotated[
        Path | None,
        typer.Option("--params", help="A params JSON (nf-core's params_<ts>.json)"),
    ] = None,
    var: Annotated[
        list[str] | None,
        typer.Option("--var", help="KEY=VALUE as given to `depictio ingest`; repeatable"),
    ] = None,
    schema: Annotated[
        Path | None,
        typer.Option("--schema", help="The pipeline's nextflow_schema.json (a local checkout)"),
    ] = None,
    fetch_schema: Annotated[
        bool,
        typer.Option(
            "--fetch-schema",
            help="Fetch the template release's nextflow_schema.json from GitHub (nf-core only)",
        ),
    ] = False,
    all_templates: Annotated[
        bool, typer.Option("--all", help="Every bundled template, one line each")
    ] = False,
    schema_cache: Annotated[
        Path | None, typer.Option("--schema-cache", help="Keep fetched schemas here")
    ] = None,
    against: Annotated[
        str | None,
        typer.Option(
            "--against",
            help="A newer release (3.27.0) or its nextflow_schema.json: which rules it "
            "breaks or flips, which skip_* flags it adds",
        ),
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Also list variables no conditional reads")
    ] = False,
) -> None:
    """Check a template's variables against a pipeline's parameters.

    Lists each variable and what sets it: a `from_params` rule on the run's
    params, the outputs themselves (auto), or the user (`--var`). With
    `--schema`/`--fetch-schema`: every param a rule reads must exist in the
    release, each rule is evaluated on a default run, and the release's skip_*
    params no rule reads are listed. With `--run`/`--params`: which rules hold for
    that run and which conditionals fire. Offline unless --fetch-schema.

    Examples:
        depictio template check nf-core/rnaseq/3.26.0 --fetch-schema
        depictio template check --run results/ --var TRACKS_URI=s3://bucket/run
        depictio template check ./my-template --schema ../rnaseq/nextflow_schema.json
        depictio template check nf-core/rnaseq/3.26.0 --against 3.27.0
    """
    import json

    import yaml

    from depictio.cli.cli.utils.data_root import as_data_root
    from depictio.cli.cli.utils.template_check import check_template, nfcore_target
    from depictio.cli.cli.utils.template_check import fetch_schema as fetch
    from depictio.cli.cli.utils.templates import (
        _introspect_pipeline_params,
        _pick_input_file,
        _projects_roots,
        _read_run_params,
        detect_template_from_run_dir,
    )

    explicit: dict[str, str] = {}
    for item in var or []:
        if "=" not in item:
            console.print(f"[red]--var must be KEY=VALUE, got {item!r}[/red]")
            raise typer.Exit(1)
        key, value = item.split("=", 1)
        explicit[key.strip()] = value.strip()

    run_params: dict | None = None
    if params is not None:
        loaded = json.loads(params.read_text())
        run_params = loaded if isinstance(loaded, dict) else {}
    elif run is not None:
        run_params = _read_run_params(run, full_dump_only=True)
        if not run_params:
            console.print(f"[yellow]! no pipeline_info/params_*.json under {run}[/yellow]")
        # What `depictio ingest` finds in the outputs, never over an explicit --var.
        auto = {"DATA_ROOT": str(run), **explicit}
        _introspect_pipeline_params(run, auto, _read_run_params(run))
        samplesheet = _pick_input_file(
            as_data_root(run), "samplesheet", (".csv", ".tsv", ".tab", ".txt")
        )
        if samplesheet:
            auto.setdefault("SAMPLESHEET_FILE", samplesheet)
        explicit = auto

    if all_templates:
        root = next(r for r in _projects_roots() if r.is_dir())
        ids = [str(p.parent) for p in sorted(root.glob("**/template.yaml"))]
    elif template is not None:
        ids = [template]
    elif run is not None:
        detected, _info = detect_template_from_run_dir(run)
        if detected is None:
            console.print(f"[red]✗ no bundled template fits {run}: pass one[/red]")
            raise typer.Exit(1)
        console.print(f"[cyan]{run} → {detected}[/cyan]")
        ids = [detected]
    else:
        console.print("[red]Pass a template, --run or --all[/red]")
        raise typer.Exit(1)

    failed = unreachable = 0
    for template_ref in ids:
        meta, path = _load_metadata(template_ref)
        has_rules = any(v.from_params is not None for v in meta.variables)
        target = nfcore_target(meta.template_id)
        schema_doc = None
        if schema is not None:
            schema_doc = json.loads(schema.read_text())
        elif (fetch_schema or against) and target is not None:
            try:
                schema_doc = fetch(*target, cache=schema_cache)
            except Exception as exc:  # noqa: BLE001 - reported; fatal only for rules
                console.print(f"[yellow]? {meta.template_id}: no schema ({exc})[/yellow]")
                unreachable += has_rules
        # What the template reads: its collections and dashboards, not its
        # `template:` metadata (provenance lists params) and not its comments.
        docs = [
            yaml.safe_load(f.read_text()) or {}
            for f in [path, *sorted(path.parent.glob("dashboards/*.yaml"))]
        ]
        docs[0] = {k: v for k, v in docs[0].items() if k != "template"}
        text = "\n".join(json.dumps(d) for d in docs)
        result = check_template(
            meta,
            path=path,
            schema=schema_doc,
            run_params=run_params,
            run_vars=explicit or None,
            template_text=text,
        )
        if len(ids) > 1:
            _print_summary_line(result)
        else:
            _print_check(result, verbose=verbose)
        failed += not result.ok
        if against and schema_doc is not None:
            failed += not _print_release_drift(meta, schema_doc, against, target, schema_cache)
    if len(ids) > 1:
        console.print(
            f"\n{len(ids)} templates, {failed} with unknown params, "
            f"{unreachable} schemas unreachable (templates with rules)"
        )
    raise typer.Exit(1 if failed else 2 if unreachable else 0)


def _print_release_drift(meta, old_schema: dict, against: str, target, cache) -> bool:
    """Print what a newer release changes for the template's rules; True when nothing breaks."""
    import json

    from depictio.cli.cli.utils.template_check import compare_releases, fetch_schema

    if Path(against).is_file():
        new_schema, label = json.loads(Path(against).read_text()), against
    elif target is not None:
        new_schema, label = fetch_schema(target[0], against, cache=cache), against
    else:
        console.print(
            "[red]--against: give a nextflow_schema.json for a non nf-core template[/red]"
        )
        return False
    old_label = target[1] if target else "the template's release"
    drift = compare_releases(meta, old_schema, new_schema)
    console.print()
    for line in drift.markdown(old_label, label):
        console.print(line.replace("`", ""), markup=False, highlight=False)
    return drift.ok


def _print_summary_line(result) -> None:
    """One template in an --all listing."""
    status = "[red]✗[/red]" if not result.ok else "[green]✓[/green]"
    unknown = "".join(
        f" [red]{v} reads {', '.join(m)}: not a param[/red]"
        for v, m in result.unknown_params.items()
    )
    skips = (
        f" [yellow]to check: {', '.join(result.suspect_skip_params)}[/yellow]"
        if result.suspect_skip_params
        else ""
    )
    routes = sum(bool(r.effects) for r in result.rows if r.source != "rule")
    console.print(
        f"{status} {result.template_id:<52} rules {result.rule_count:>2} · "
        f"routes via --var/auto {routes:>2}{skips}{unknown}"
    )
