from importlib.metadata import PackageNotFoundError, version

import click
import typer


def register_standalone_commands(app: typer.Typer):
    @app.command("version")
    def version_cmd():
        """Show version information"""
        try:
            package_version = version("depictio-cli")  # Replace with your actual package name
            typer.echo(f"Depictio CLI version: {package_version}")
        except PackageNotFoundError:
            typer.echo("Depictio CLI version: unknown (not installed)")

    @app.command("commands")
    def commands_cmd(ctx: typer.Context):
        """Show the full command reference as a grouped table.

        Introspects the live command tree, so it always matches what the CLI
        actually exposes. Maintainer/CI tooling under the hidden ``dev`` group is
        omitted (run ``depictio dev --help`` to see it).
        """
        from rich.console import Console
        from rich.table import Table

        # The root Click group — every registered command/group hangs off this,
        # so the table stays in sync automatically (no hardcoded command list).
        root = ctx.find_root().command

        def short_help(cmd: click.Command) -> str:
            return (cmd.get_short_help_str(limit=70) or "").strip()

        def visible(group: click.Group) -> list[tuple[str, click.Command]]:
            return [
                (name, group.commands[name])
                for name in group.list_commands(ctx)
                if not group.commands[name].hidden
            ]

        console = Console()
        table = Table(
            title="depictio — command reference",
            title_style="bold",
            header_style="bold cyan",
            show_lines=False,
            expand=False,
        )
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description")

        top_level = []  # standalone commands (run, version, commands)
        groups = []  # (name, Group)
        for name, cmd in visible(root):
            if isinstance(cmd, click.Group):
                groups.append((name, cmd))
            else:
                top_level.append((name, cmd))

        # Standalone commands first (run sorted to the top — it is the entry point).
        top_level.sort(key=lambda nc: (nc[0] != "run", nc[0]))
        for name, cmd in top_level:
            table.add_row(f"[bold]{name}[/bold]", short_help(cmd))

        # One section per command group, with a styled group header row.
        for gname, group in groups:
            table.add_section()
            table.add_row(
                f"[bold magenta]{gname}[/bold magenta]", f"[dim]{short_help(group)}[/dim]"
            )
            for sname, sub in visible(group):
                if isinstance(sub, click.Group):
                    # One nested level (kept for safety; user-facing tree is flat).
                    for ssname, ssub in visible(sub):
                        table.add_row(f"  {gname} {sname} {ssname}", short_help(ssub))
                else:
                    table.add_row(f"  {gname} {sname}", short_help(sub))

        console.print(table)
        console.print(
            "[dim]Run any command with [/dim][cyan]--help[/cyan][dim] for full options. "
            "Maintainer tooling lives under [/dim][cyan]depictio dev[/cyan][dim].[/dim]"
        )
