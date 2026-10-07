"""
Dashboard CLI commands.

Provides three simple commands for dashboard YAML management:
- validate: Validate a YAML file locally (and optionally against server schema)
- import: Import YAML to server (project from YAML or --project override)
- export: Export dashboard from server to YAML
"""

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import quote

import httpx
import typer
from rich.console import Console

from depictio.cli.cli.utils.server_target import DashboardServerOption, resolve_server

if TYPE_CHECKING:
    from depictio.models.models.dashboards import DashboardDataLite

app = typer.Typer(help="Dashboard management commands")
console = Console()

# The option these commands took before --server. Still accepted, out of the help.
LegacyConfigOption = Annotated[str | None, typer.Option("--config", "-c", hidden=True)]
# Overrides the configuration's api_base_url when given.
ApiUrlOption = Annotated[str | None, typer.Option("--api", hidden=True)]

# Start of the error validate_schema_online returns when the server does not answer.
_UNREACHABLE = "Server unreachable"

# What --project takes: a MongoDB ObjectId, checked here so a typo is not a raw 422.
_PROJECT_ID = re.compile(r"[0-9a-fA-F]{24}")

# After a configuration that loaded but cannot authenticate a request.
_CONFIG_HINT = "[yellow]Hint: pass --server local or a CLI configuration file[/yellow]"

# Mapping from delta table column types to the canonical COLUMN_TYPES used in constants.py
_DELTA_TO_COLUMN_TYPE: dict[str, str] = {
    "string": "object",
    "utf8": "object",
    "object": "object",
    "int64": "int64",
    "int32": "int64",
    "float32": "float64",
    "float64": "float64",
    "bool": "bool",
    "boolean": "bool",
    "date": "datetime",
    "datetime": "datetime",
    "time": "timedelta",
    "timedelta": "timedelta",
    "category": "category",
}


def _resolve_dc_id_from_project(project_data: dict, workflow_tag: str, dc_tag: str) -> str | None:
    """Find DC ID from a project document given workflow_tag and dc_tag."""
    wf_name = workflow_tag.split("/", 1)[1] if "/" in workflow_tag else workflow_tag
    for wf in project_data.get("workflows", []):
        engine = wf.get("engine", {}).get("name", "")
        full_tag = f"{engine}/{wf.get('name', '')}" if engine else wf.get("name", "")
        if wf.get("name") != wf_name and full_tag != workflow_tag:
            continue
        for dc in wf.get("data_collections", []):
            if dc.get("data_collection_tag") == dc_tag:
                # API serialises ObjectId as "id" (not "_id")
                dc_id = dc.get("id") or dc.get("_id")
                return str(dc_id) if dc_id else None
    return None


def validate_schema_online(
    lite: "DashboardDataLite",
    api_url: str,
    headers: dict[str, str],
    project_id: str | None = None,
) -> list[dict[str, str]]:
    """Online validation: resolve DC schema and check column names / aggregation / interactive types.

    The project is ``project_id`` when given (import's --project, which the import
    itself uses too), else the YAML's project_tag. Without either there is nothing
    to check against: callers say so before calling.

    For each component with workflow_tag + data_collection_tag + column_name:
    - Checks column_name exists in the server delta table schema.
    - When column_type is not provided, infers it from the server schema and
      validates aggregation × inferred_type (cards) or
      interactive_component_type × inferred_type (interactives).

    Returns a list of error dicts (empty = all pass).
    """
    from depictio.models.components.constants import (
        AGGREGATION_COMPATIBILITY,
        INTERACTIVE_COMPATIBILITY,
    )
    from depictio.models.components.lite import CardLiteComponent, InteractiveLiteComponent

    errors: list[dict[str, str]] = []

    if not project_id and not lite.project_tag:
        return errors

    # Fetch project document
    project_label = project_id or lite.project_tag
    try:
        if project_id:
            resp = httpx.get(
                f"{api_url}/depictio/api/v1/projects/get/from_id",
                params={"project_id": project_id},
                headers=headers,
                timeout=15,
            )
        else:
            # Quoted: a '#' or '?' in the name would otherwise end the path.
            resp = httpx.get(
                f"{api_url}/depictio/api/v1/projects/get/from_name/"
                f"{quote(str(lite.project_tag), safe='')}",
                headers=headers,
                timeout=15,
            )
        if resp.status_code != 200:
            return [
                {
                    "component_id": "-",
                    "field": "-",
                    "message": f"Cannot resolve project '{project_label}': HTTP {resp.status_code}",
                }
            ]
        project_data = resp.json()
    except httpx.RequestError as exc:
        return [{"component_id": "-", "field": "-", "message": f"{_UNREACHABLE}: {exc}"}]

    # Cache: (workflow_tag, dc_tag) → {column_name: delta_type} or None (unresolvable)
    schema_cache: dict[tuple[str, str], dict[str, str] | None] = {}

    for comp in lite.components:
        if isinstance(comp, dict):
            continue  # Pydantic already caught these

        comp_tag = getattr(comp, "tag", None) or comp.__class__.__name__
        wf_tag = getattr(comp, "workflow_tag", "") or ""
        dc_tag = getattr(comp, "data_collection_tag", "") or ""

        if not wf_tag or not dc_tag:
            continue

        cache_key = (wf_tag, dc_tag)

        if cache_key not in schema_cache:
            dc_id = _resolve_dc_id_from_project(project_data, wf_tag, dc_tag)
            if dc_id is None:
                errors.append(
                    {
                        "component_id": comp_tag,
                        "field": "wf/dc_tag",
                        "message": f"workflow='{wf_tag}' dc='{dc_tag}' not found in project '{project_label}'",
                    }
                )
                schema_cache[cache_key] = None
                continue

            try:
                spec_resp = httpx.get(
                    f"{api_url}/depictio/api/v1/deltatables/specs/{dc_id}",
                    headers=headers,
                    timeout=15,
                )
                if spec_resp.status_code != 200:
                    schema_cache[cache_key] = None
                    continue
                schema_cache[cache_key] = {
                    col["name"]: col["type"] for col in spec_resp.json() if "name" in col
                }
            except httpx.RequestError:
                schema_cache[cache_key] = None
                continue

        schema = schema_cache[cache_key]
        if not schema:
            continue

        column_name: str | None = getattr(comp, "column_name", None)
        if not column_name:
            continue

        if column_name not in schema:
            errors.append(
                {
                    "component_id": comp_tag,
                    "field": "column_name",
                    "message": (
                        f"Column '{column_name}' not found in '{wf_tag}/{dc_tag}'. "
                        f"Available: {', '.join(sorted(schema.keys()))}"
                    ),
                }
            )
            continue

        # Only infer type when user did not supply column_type
        user_column_type: str | None = getattr(comp, "column_type", None)
        if user_column_type:
            continue  # Already validated offline by Pydantic

        inferred_type = _DELTA_TO_COLUMN_TYPE.get(schema[column_name])
        if not inferred_type:
            continue

        if isinstance(comp, CardLiteComponent):
            valid_aggs = AGGREGATION_COMPATIBILITY.get(inferred_type, [])
            if valid_aggs and comp.aggregation not in valid_aggs:
                errors.append(
                    {
                        "component_id": comp_tag,
                        "field": "aggregation",
                        "message": (
                            f"aggregation='{comp.aggregation}' is not valid for column '{column_name}' "
                            f"(server type: '{inferred_type}'). Valid: {', '.join(valid_aggs)}"
                        ),
                    }
                )
        elif isinstance(comp, InteractiveLiteComponent):
            valid_types = INTERACTIVE_COMPATIBILITY.get(inferred_type, [])
            if not valid_types:
                errors.append(
                    {
                        "component_id": comp_tag,
                        "field": "interactive_type",
                        "message": (
                            f"No interactive component supports column '{column_name}' "
                            f"(server type: '{inferred_type}')"
                        ),
                    }
                )
            elif comp.interactive_component_type not in valid_types:
                errors.append(
                    {
                        "component_id": comp_tag,
                        "field": "interactive_type",
                        "message": (
                            f"'{comp.interactive_component_type}' not valid "
                            f"for column '{column_name}' (type: '{inferred_type}'). "
                            f"Valid: {', '.join(valid_types)}"
                        ),
                    }
                )

    return errors


def _format_validation_error(error: Any) -> dict[str, str]:
    """Format a single validation error for display."""
    if isinstance(error, dict):
        if error.get("type") == "component_error":
            # Structured error from validate_components_domain (one per component)
            return {
                "component_id": error.get("tag") or "-",
                "field": error.get("loc") or "-",
                "message": error.get("msg") or str(error),
            }
        loc = error.get("loc", ())
        msg = error.get("msg", str(error))
        field = ".".join(str(x) for x in loc) if loc else "-"
        return {"component_id": "-", "field": field, "message": msg}
    # Fallback for unexpected types
    return {"component_id": "-", "field": "-", "message": str(error)}


def _make_error_result(message: str) -> dict[str, Any]:
    """Create a validation result for a single error."""
    return {
        "valid": False,
        "errors": [{"component_id": "-", "field": "-", "message": message}],
        "warnings": [],
    }


def _connect(config_path: str, api_url: str | None) -> tuple[str, dict[str, str]]:
    """The API URL and auth headers of the server ``config_path`` names; ``api_url`` wins.

    With ``api_url`` the configuration only lends its token, so the line naming the
    server the command talks to names ``api_url``, not the configuration's URL.
    """
    from depictio.cli.cli.utils.common import (
        cli_config_file,
        display_path,
        generate_api_headers,
        load_depictio_config,
    )
    from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement

    cli_config = load_depictio_config(yaml_config_path=config_path, quiet=bool(api_url))
    if api_url:
        # On stderr: a note about a hidden option, like the notes on renamed ones.
        rich_print_checked_statement(
            f"Server: {api_url} (from --api, instead of {cli_config.api_base_url} in "
            f"{display_path(cli_config_file(config_path))})",
            "info",
            stderr=True,
        )
    return api_url or str(cli_config.api_base_url), generate_api_headers(cli_config)


def _say_local_server_hint(config_path: str) -> None:
    """After a connection error: for a stopped local server, how to start it."""
    from depictio.cli.cli.utils.common import local_server_hint

    hint = local_server_hint(config_path)
    if hint:
        console.print(f"[yellow]Hint: {hint}[/yellow]")


def validate_yaml_with_pydantic(yaml_file: Path) -> dict[str, Any]:
    """Validate a YAML file using DashboardDataLite Pydantic model.

    Domain constraints (visu_type, column_type, aggregation×column_type,
    interactive_type×column_type, mode/code_content, selection fields) are
    enforced by model validators — they run automatically here.

    Args:
        yaml_file: Path to YAML file

    Returns:
        Dict with 'valid', 'errors', 'warnings' keys
    """
    from depictio.models.models.dashboards import DashboardDataLite

    try:
        content = yaml_file.read_text(encoding="utf-8")
        is_valid, errors = DashboardDataLite.validate_yaml(content)
        formatted_errors = [_format_validation_error(e) for e in errors]
        return {"valid": is_valid, "errors": formatted_errors, "warnings": []}
    except FileNotFoundError:
        return _make_error_result(f"File not found: {yaml_file}")
    except Exception as e:
        return _make_error_result(str(e))


def validate_yaml_string_with_pydantic(yaml_content: str) -> dict[str, Any]:
    """Validate a YAML string using DashboardDataLite Pydantic model."""
    from depictio.models.models.dashboards import DashboardDataLite

    try:
        is_valid, errors = DashboardDataLite.validate_yaml(yaml_content)
        formatted_errors = [_format_validation_error(e) for e in errors]
        return {"valid": is_valid, "errors": formatted_errors, "warnings": []}
    except Exception as e:
        return _make_error_result(str(e))


@app.command()
def validate(
    yaml_file: Annotated[Path, typer.Argument(help="Path to YAML dashboard file")],
    server: DashboardServerOption = None,
    config_path: LegacyConfigOption = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="No effect, kept for the scripts that pass it. For detailed logs, put -v "
            "before the command: depictio -v dashboard validate ...",
        ),
    ] = False,
    offline: Annotated[
        bool,
        typer.Option(
            "--offline",
            help="Skip server schema validation (column names, inferred types, aggregation compatibility)",
        ),
    ] = False,
    api_url: ApiUrlOption = None,
) -> None:
    """Validate a dashboard YAML file.

    Runs two levels of validation:

    1. Schema + domain (always): required fields, enum values, cross-field rules
       (visu_type, mode/code_content, aggregation×column_type, etc.)

    2. Server schema (when a server is configured): resolves each component's
       workflow_tag + data_collection_tag against the server delta table schema, checks
       that column_name exists, and validates aggregation/interactive_component_type
       against the inferred column type. Without --server it is skipped when neither
       $DEPICTIO_CLI_CONFIG_PATH nor ~/.depictio/CLI.yaml exists, and what that default
       server reports is shown as warnings only. Use --offline to skip it.

    Example:
        depictio dashboard validate dashboard.yaml --server local
        depictio dashboard validate dashboard.yaml --server admin_config.yaml --offline
        depictio dashboard validate dashboard.yaml  # offline unless a default server is set up
    """

    from depictio.cli.cli.utils.common import (
        CLIConfigError,
        cli_config_file,
        display_path,
        read_depictio_config,
    )
    from depictio.models.models.dashboards import DashboardDataLite

    # Only a server the user named must answer: the default one is checked when
    # present, and nothing it reports fails an offline-valid file.
    explicit = bool(server or config_path)
    config_file = resolve_server(server, config_path, legacy_option="--config")

    if not yaml_file.exists():
        console.print(f"[red]Error: File not found: {yaml_file}[/red]")
        raise typer.Exit(1)

    console.print(f"Validating: {yaml_file}")

    # --- Pass 1: offline schema + domain ---
    console.print("  [dim]Pass 1: schema + domain constraints[/dim]")
    result = validate_yaml_with_pydantic(yaml_file)

    all_errors: list[dict[str, str]] = list(result["errors"])

    if not result["valid"]:
        console.print("[red]✗ Schema/domain validation failed[/red]")
        _print_error_table(all_errors)
        raise typer.Exit(1)

    console.print("  [green]✓ Schema + domain OK[/green]")

    # --- Pass 2: server schema validation ---
    default_file = None if explicit else cli_config_file(config_file)
    if offline:
        console.print("  [dim]Pass 2: skipped (--offline)[/dim]")
    elif default_file and not os.path.isfile(default_file):
        console.print(
            "  [dim]Pass 2: skipped (no --server, and no configuration at "
            f"{display_path(default_file)})[/dim]"
        )
    else:
        console.print("  [dim]Pass 2: server schema validation[/dim]")
        try:
            if not explicit:
                # Read silently first: a default configuration that cannot be used
                # skips this pass instead of failing the command.
                read_depictio_config(config_file)
            server_url, headers = _connect(config_file, api_url)

            yaml_content = yaml_file.read_text(encoding="utf-8")
            lite = DashboardDataLite.from_yaml(yaml_content)
            if not lite.project_tag:
                online_errors = None
                console.print(
                    "  [yellow]⚠ Server schema check skipped: the YAML has no project_tag "
                    "to look its data collections up in[/yellow]"
                )
            else:
                online_errors = validate_schema_online(lite, server_url, headers)

            if online_errors is None:
                pass
            elif not online_errors:
                console.print("  [green]✓ Server schema OK[/green]")
            elif _is_unreachable(online_errors):
                if explicit:
                    all_errors.extend(online_errors)
                    console.print(f"  [red]✗ Server schema: {server_url} is unreachable[/red]")
                else:
                    console.print(
                        f"  [yellow]⚠ Server schema check skipped: {server_url} is "
                        "unreachable[/yellow]"
                    )
                _say_local_server_hint(config_file)
            elif explicit:
                all_errors.extend(online_errors)
                console.print(f"  [red]✗ Server schema: {len(online_errors)} error(s)[/red]")
            else:
                # Nobody named this server: a project it lacks or a token it refuses
                # says nothing about the file, so what it reports does not fail it.
                console.print(
                    f"  [yellow]⚠ Server schema: {len(online_errors)} warning(s) from the "
                    f"default server {server_url}, not counted as errors: name it with "
                    "--server to make them count[/yellow]"
                )
                _print_error_table(online_errors, title="Server schema warnings")
        except typer.Exit:
            # The configuration --server named cannot be used: load_depictio_config said so.
            raise
        except CLIConfigError as e:
            console.print(f"  [yellow]⚠ Server schema check skipped: {e}[/yellow]")
        except Exception as e:
            if explicit:
                # A server the user named must answer, whatever stopped it.
                console.print(f"  [red]✗ Server schema check failed: {e}[/red]")
                raise typer.Exit(1) from e
            console.print(f"  [yellow]⚠ Server schema check skipped: {e}[/yellow]")

    if all_errors:
        console.print(f"\n[red]✗ Validation failed ({len(all_errors)} error(s))[/red]")
        _print_error_table(all_errors)
        raise typer.Exit(1)

    console.print("\n[green]✓ Validation passed[/green]")
    raise typer.Exit(0)


def _is_unreachable(errors: list[dict[str, str]]) -> bool:
    """Whether validate_schema_online stopped because the server did not answer."""
    return len(errors) == 1 and errors[0]["message"].startswith(_UNREACHABLE)


def _print_error_table(errors: list[dict[str, str]], title: str = "Validation Errors") -> None:
    """Print validation errors as a Rich table."""
    from rich.table import Table

    table = Table(title=title)
    table.add_column("Component", style="cyan")
    table.add_column("Field", style="magenta")
    table.add_column("Message", style="red")
    for error in errors:
        table.add_row(
            error.get("component_id") or "-",
            error.get("field") or "-",
            error.get("message") or "-",
        )
    console.print(table)


@app.command("import")
def import_yaml(
    yaml_file: Annotated[Path, typer.Argument(help="Path to YAML dashboard file")],
    server: DashboardServerOption = None,
    config_path: LegacyConfigOption = None,
    project: Annotated[
        str | None,
        typer.Option("--project", "-p", help="Project ID (overrides project_tag in YAML)"),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Overwrite existing dashboard with same title in project"),
    ] = False,
    api_url: ApiUrlOption = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate only, don't import")] = False,
    offline: Annotated[
        bool,
        typer.Option(
            "--offline",
            help="Skip online checks (column name validation against server DC schema)",
        ),
    ] = False,
) -> None:
    """Import a dashboard YAML file to the server.

    The project is determined in this order:
    1. --project option (if provided)
    2. project_tag field in the YAML file

    Imports into the server --server names, else the one $DEPICTIO_CLI_CONFIG_PATH
    or ~/.depictio/CLI.yaml describes (none needed for --dry-run validation).

    Example:
        # Validate without a server
        depictio dashboard import dashboard.yaml --dry-run

        # Import into the server `depictio local up` runs
        depictio dashboard import dashboard.yaml --server local

        # Overwrite existing dashboard with same title
        depictio dashboard import dashboard.yaml --server admin_config.yaml --overwrite

        # Override with explicit project ID
        depictio dashboard import dashboard.yaml --server admin_config.yaml --project 646b0f3c1e4a2d7f8e5b8c9a

        # Skip online column validation
        depictio dashboard import dashboard.yaml --server admin_config.yaml --offline
    """
    from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
    from depictio.models.models.dashboards import DashboardDataLite

    config_file = resolve_server(server, config_path, legacy_option="--config")

    if project is not None and not _PROJECT_ID.fullmatch(project):
        rich_print_checked_statement(
            f"--project takes a project ID, 24 hexadecimal characters: '{project}' is not one. "
            "To name the project, set project_tag in the YAML instead.",
            "error",
        )
        raise typer.Exit(1)

    if not yaml_file.exists():
        console.print(f"[red]Error: File not found: {yaml_file}[/red]")
        raise typer.Exit(1)

    # Step 1: Validate locally (schema + domain)
    console.print(f"[cyan]Validating:[/cyan] {yaml_file}")
    console.print("  [dim]Checks: schema + domain constraints[/dim]")
    if offline:
        console.print("  [dim]Mode: offline (column name check skipped)[/dim]")

    result = validate_yaml_with_pydantic(yaml_file)

    if not result["valid"]:
        console.print("[red]✗ Validation failed[/red]")
        for error in result["errors"]:
            console.print(f"  [red]- {error['message']}[/red]")
        raise typer.Exit(1)

    console.print("[green]✓ Validation passed[/green]")

    # Load YAML content
    yaml_content = yaml_file.read_text(encoding="utf-8")
    lite = DashboardDataLite.from_yaml(yaml_content)

    console.print(f"  Title: {lite.title}")
    console.print(f"  Components: {len(lite.components)}")

    # Show project source
    if project:
        console.print(f"  Project: {project} (from --project)")
    elif lite.project_tag:
        console.print(f"  Project: {lite.project_tag} (from YAML project_tag)")
    else:
        console.print(
            "[yellow]  Warning: No project specified. "
            "Use --project or add project_tag to YAML.[/yellow]"
        )

    if dry_run:
        console.print("\n[yellow]Dry run mode - skipping import[/yellow]")
        raise typer.Exit(0)

    # Step 2: Load CLI config for authentication. It names its server itself.
    console.print()
    try:
        api_url, headers = _connect(config_file, api_url)
    except typer.Exit:
        # A configuration it cannot use: load_depictio_config said which, and why.
        console.print("[yellow]Hint: Use --dry-run for local validation without a server[/yellow]")
        raise
    except Exception as e:
        console.print(f"[red]Error loading CLI config: {e}[/red]")
        console.print(_CONFIG_HINT)
        raise typer.Exit(1)

    # Step 2b: Server schema validation (default, skip with --offline)
    if offline:
        pass
    elif not (project or lite.project_tag):
        console.print(
            "\n[yellow]⚠ Server schema check skipped: no --project, and no project_tag "
            "in the YAML to look its data collections up in[/yellow]"
        )
    else:
        console.print("\n[cyan]Validating column names against server schema...[/cyan]")
        # The project the import goes to: --project when given, as for the import itself.
        online_errors = validate_schema_online(lite, api_url, headers, project_id=project)
        if online_errors:
            console.print(
                f"[red]✗ Server schema validation failed ({len(online_errors)} error(s))[/red]"
            )
            _print_error_table(online_errors)
            if _is_unreachable(online_errors):
                _say_local_server_hint(config_file)
            raise typer.Exit(1)
        console.print("[green]✓ Server schema OK[/green]")

    # Step 3: Import to API
    project_display = project or lite.project_tag or "server lookup"
    action = "Updating" if overwrite else "Importing"
    console.print(f"\n[cyan]{action} dashboard (project: {project_display})...[/cyan]")

    url = f"{api_url}/depictio/api/v1/dashboards/import/yaml"

    try:
        # Build query params (small values only)
        params: dict[str, str | bool] = {}
        if project:
            params["project_id"] = project
        if overwrite:
            params["overwrite"] = True

        with httpx.Client(timeout=60) as client:
            response = client.post(
                url,
                params=params,
                content=yaml_content,
                headers={**headers, "Content-Type": "text/plain"},
            )

            if response.status_code != 200:
                console.print(f"[red]✗ Import failed: HTTP {response.status_code}[/red]")
                try:
                    error_detail = response.json().get("detail", response.text)
                except Exception:
                    error_detail = response.text
                console.print(f"  {error_detail}")
                raise typer.Exit(1)

            data = response.json()
            action_done = "updated" if data.get("updated") else "imported"
            console.print(f"[green]✓ Dashboard {action_done} successfully![/green]")
            console.print(f"  Dashboard ID: {data.get('dashboard_id')}")
            console.print(f"  Title: {data.get('title')}")
            console.print(f"  Project ID: {data.get('project_id')}")
            dash_url = data.get("dash_url") or api_url.replace("/depictio/api/v1", "")
            console.print(
                f"\n[cyan]View at:[/cyan] {dash_url}/dashboard/{data.get('dashboard_id')}"
            )

    except httpx.ConnectError:
        console.print(f"[red]Error: Cannot connect to API at {api_url}[/red]")
        from depictio.cli.cli.utils.common import local_server_hint

        hint = local_server_hint(config_file) or "Make sure the Depictio API server is running"
        console.print(f"[yellow]Hint: {hint}[/yellow]")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def export(
    dashboard_id: Annotated[str, typer.Argument(help="Dashboard ID to export")],
    server: DashboardServerOption = None,
    config_path: LegacyConfigOption = None,
    output: Annotated[Path, typer.Option("--output", "-o", help="Output file path")] = Path(
        "dashboard.yaml"
    ),
    api_url: ApiUrlOption = None,
) -> None:
    """Export a dashboard from the server to a YAML file.

    Downloads the dashboard configuration and saves it as a minimal YAML file
    suitable for version control and re-import.

    Example:
        depictio dashboard export 6824cb3b89d2b72169309737 --server local
        depictio dashboard export 6824cb3b89d2b72169309737 --server admin_config.yaml -o my-dashboard.yaml
    """
    config_file = resolve_server(server, config_path, legacy_option="--config")

    # Load CLI config for authentication. It names its server itself.
    try:
        api_url, headers = _connect(config_file, api_url)
    except typer.Exit:
        # No configuration file: load_depictio_config named the one it looked for.
        raise
    except Exception as e:
        console.print(f"[red]Error loading CLI config: {e}[/red]")
        console.print(_CONFIG_HINT)
        raise typer.Exit(1)

    # Quoted like any value in a path: a '/' or '?' in it would reach another route.
    url = f"{api_url}/depictio/api/v1/dashboards/{quote(dashboard_id, safe='')}/yaml"
    console.print(f"[cyan]Exporting dashboard {dashboard_id}...[/cyan]")

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        console.print(f"[red]Error: HTTP {e.response.status_code}[/red]")
        console.print(f"  {e.response.text}")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        console.print(f"[red]Error: {e}[/red]")
        if isinstance(e, httpx.ConnectError):
            _say_local_server_hint(config_file)
        raise typer.Exit(1)

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(response.text, encoding="utf-8")
    except OSError as e:
        # A directory, a read-only location: the export is lost either way, so say
        # where it could not go rather than end on a traceback.
        from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement

        rich_print_checked_statement(f"Cannot write the dashboard to {output}: {e}", "error")
        raise typer.Exit(1) from e
    console.print(f"[green]✓ Dashboard exported to: {output}[/green]")
