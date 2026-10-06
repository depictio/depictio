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

        def short_help(cmd) -> str:
            return (cmd.get_short_help_str(limit=70) or "").strip()

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

        table = Table(
            title="depictio command reference",
            title_style="bold",
            header_style="bold cyan",
            show_lines=False,
            expand=False,
        )
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description")

        def add_subcommands(group, path: str) -> None:
            for name, sub in visible(group):
                table.add_row(f"  {path} {name}", short_help(sub))
                if is_group(sub):
                    add_subcommands(sub, f"{path} {name}")

        # The root lists its commands panel by panel, as `depictio --help` shows
        # them: one section per panel, headed by its name.
        panel = None
        for name, cmd in visible(root):
            cmd_panel = getattr(cmd, "rich_help_panel", None) or "Commands"
            if cmd_panel != panel:
                if panel is not None:
                    table.add_section()
                table.add_row(f"[bold magenta]{cmd_panel}[/bold magenta]", "")
                panel = cmd_panel
            table.add_row(f"[bold]{name}[/bold]", short_help(cmd))
            if is_group(cmd):
                add_subcommands(cmd, name)

        console.print(table)
        console.print(
            "[dim]Run any command with [/dim][cyan]--help[/cyan][dim] for full options. "
            "Maintainer tooling lives under [/dim][cyan]depictio dev[/cyan][dim].[/dim]"
        )
