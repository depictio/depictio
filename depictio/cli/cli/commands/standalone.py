from typing import Any

import typer


def register_standalone_commands(app: typer.Typer):
    @app.command("version")
    def version_cmd():
        """Show the installed depictio version."""
        from depictio.cli.cli.utils.telemetry import cli_version

        typer.echo(f"Depictio CLI version: {cli_version()}")

    @app.command("commands")
    def commands_cmd(ctx: typer.Context):
        """Show every command and subcommand in one table.

        Introspects the live command tree, so it always matches what the CLI
        actually exposes. Maintainer/CI tooling under the hidden `dev` group is
        omitted (run `depictio dev --help` to see it).
        """
        from rich.table import Table

        from depictio.cli.cli.utils.rich_utils import console

        # The root Click group: every registered command/group hangs off it, so the
        # table stays in sync automatically (no hardcoded command list).
        root = ctx.find_root().command

        def visible(group) -> list:
            return [
                (name, group.commands[name])
                for name in group.list_commands(ctx)
                if not group.commands[name].hidden
            ]

        def is_group(cmd) -> bool:
            # Duck-typed: Typer's groups are built on its own copy of Click, so they
            # are not click.Group instances.
            return hasattr(cmd, "commands")

        # (label, command or None for a panel heading, starts a new section): collected
        # first, so the descriptions can take whatever width the labels leave.
        rows: list[tuple[str, Any, bool]] = []

        def add_subcommands(group, path: str) -> None:
            for name, sub in visible(group):
                rows.append((f"  {path} {name}", sub, False))
                if is_group(sub):
                    add_subcommands(sub, f"{path} {name}")

        # The root lists its commands panel by panel, as `depictio --help` shows
        # them: one section per panel, headed by its name.
        panel = None
        for name, cmd in visible(root):
            cmd_panel = getattr(cmd, "rich_help_panel", None) or "Commands"
            if cmd_panel != panel:
                rows.append((f"[bold magenta]{cmd_panel}[/bold magenta]", None, panel is not None))
                panel = cmd_panel
            rows.append((f"[bold]{name}[/bold]", cmd, False))
            if is_group(cmd):
                add_subcommands(cmd, name)

        # The terminal's width less the widest label and the table's borders and
        # padding (7 columns), so each description fits on its row.
        label_width = max(console.measure(label).maximum for label, _, _ in rows)
        limit = max(console.width - label_width - 7, 30)

        table = Table(
            title="depictio command reference",
            title_style="bold",
            header_style="bold cyan",
            show_lines=False,
            expand=False,
        )
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description")
        for label, cmd, new_section in rows:
            if new_section:
                table.add_section()
            short_help = (cmd.get_short_help_str(limit=limit) or "").strip() if cmd else ""
            table.add_row(label, short_help)

        console.print(table)
        console.print(
            "[dim]Run any command with [/dim][cyan]--help[/cyan][dim] for full options. "
            "Maintainer tooling lives under [/dim][cyan]depictio dev[/cyan][dim].[/dim]"
        )
